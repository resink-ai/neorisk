"""`datagen replay`: read a dataset's Parquet in canonical order and tee it to sinks."""

from __future__ import annotations

import argparse
import sys
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_PRESET_KEYS = {"first", "last", "from", "to", "types", "sink", "numbers", "batch_rows"}


class UsageError(Exception):
    pass


def parse_time(text: str) -> int:
    """RFC 3339 timestamp or a date (midnight UTC) as integer µs since the epoch."""
    try:
        dt = datetime.fromisoformat(str(text).strip())
    except ValueError:
        raise UsageError(f"bad time {text!r}: use RFC 3339 or a date like 2026-03-01") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return (dt - _EPOCH) // timedelta(microseconds=1)


def _preset(dataset: Path, name: str) -> dict:
    f = dataset.resolve().parent.parent / "datagen.toml"
    if not f.is_file():
        raise UsageError(f"--preset {name}: no datagen.toml at {f}")
    try:
        presets = tomllib.loads(f.read_text()).get("replay", {}).get("presets", {})
    except tomllib.TOMLDecodeError as e:
        raise UsageError(f"{f}: {e}") from None
    if name not in presets:
        raise UsageError(f"unknown preset {name!r} (known: {', '.join(sorted(presets)) or '-'})")
    bad = set(presets[name]) - _PRESET_KEYS
    if bad:
        raise UsageError(f"preset {name!r}: unknown key {min(bad)!r}")
    return dict(presets[name])


def _settings(args: argparse.Namespace) -> dict:
    """Preset keys first, explicit flags override them."""
    s: dict = {}
    if args.preset:
        s.update(_preset(Path(args.dataset), args.preset))
    flags = {"first": args.first, "last": args.last, "from": args.t_from, "to": args.t_to,
             "types": args.types, "sink": args.sink or None, "numbers": args.numbers,
             "batch_rows": args.batch_rows}
    if flags["first"] is not None or flags["last"] is not None:
        s.pop("first", None)
        s.pop("last", None)
    s.update({k: v for k, v in flags.items() if v is not None})
    return s


def _fmt_key(key) -> str:
    if key is None:
        return "-"
    from neorisk_simkit.io.replay.encode import _ts

    return f"{_ts(key[0])}/{key[1]}/{key[2]}/{key[3]}"


def _print_report(reports) -> None:
    for r in reports:
        rate = r.rows / r.seconds if r.seconds > 0 else 0.0
        print(f"sink {r.name}: rows={r.rows} rate={rate:,.0f} rows/s first={_fmt_key(r.first_key)} "
              f"last={_fmt_key(r.last_key)} error={r.error or '-'}", file=sys.stderr)


def cmd_replay(args: argparse.Namespace) -> int:
    from neorisk_simkit.io.replay.planner import (
        MAX_BATCH_ROWS,
        ReplayError,
        ReplayRequest,
        plan_replay,
    )
    from neorisk_simkit.io.replay.reader import iter_batches
    from neorisk_simkit.io.sinks.base import SinkUnavailable, open_sink

    try:
        s = _settings(args)
        types = s.get("types")
        if isinstance(types, str):
            types = [x for x in types.split(",") if x]
        uris = s.get("sink", ["stdout"])
        uris = [uris] if isinstance(uris, str) else list(uris)
        req = ReplayRequest(
            first=s.get("first"), last=s.get("last"),
            t_from=parse_time(s["from"]) if "from" in s else None,
            t_to=parse_time(s["to"]) if "to" in s else None,
            types=tuple(types) if types is not None else None,
            batch_rows=int(s.get("batch_rows", MAX_BATCH_ROWS)))
        plan = plan_replay(Path(args.dataset), req)
        opened = [(*open_sink(uri, bool(s.get("numbers", False)), plan.doc), uri)
                  for uri in uris]
    except (UsageError, ReplayError, SinkUnavailable, FileNotFoundError) as e:
        print(e, file=sys.stderr)
        return 2

    live = []   # (sink, uri)
    reports = []
    failed = False

    def fail(sink, uri: str, e: BaseException) -> None:
        nonlocal failed
        failed = True
        msg = f"{type(e).__name__}: {e}"
        abort = getattr(sink, "abort", None)
        rep = abort(msg) if abort else None
        if rep is None:
            from neorisk_simkit.io.sinks.base import SinkReport

            rep = SinkReport(uri, 0, 0.0, None, None, msg)
        reports.append(rep)

    try:
        for sink, opts, uri in opened:
            try:
                sink.open(plan.schema, opts)
                live.append((sink, uri))
            except Exception as e:  # noqa: BLE001 - one bad sink must not stop the others
                fail(sink, uri, e)
        for batch in iter_batches(plan) if live else ():
            for item in list(live):
                try:
                    item[0].write(batch)
                except Exception as e:  # noqa: BLE001
                    live.remove(item)
                    fail(item[0], item[1], e)
            if all(getattr(sink, "stopped", False) for sink, _ in live):
                break    # every remaining sink lost its reader (closed pipe)
        for sink, uri in live:
            try:
                reports.append(sink.close())
            except Exception as e:  # noqa: BLE001
                fail(sink, uri, e)
    except BaseException:
        for sink, _ in live:
            abort = getattr(sink, "abort", None)
            if abort:
                abort()
        raise
    _print_report(reports)
    return 1 if failed else 0
