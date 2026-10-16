"""Which event columns a model may read as raw inputs (D29)."""

import polars as pl

ENGINE_COLUMNS = frozenset({"lamport", "partition_id", "seq", "cause_id", "action_id"})


def resolve_allowlist(meta: dict, events: pl.DataFrame) -> list[str]:
    """Raw model inputs for ``events``: ``meta["feature_allowlist"]`` if present, else a default.

    The default is every numeric column that is not ``label``, an ``*_id`` column,
    ``event_id``/``event_time`` or an engine column. An explicit allowlist is an upper bound
    and must name existing columns that are none of those forbidden kinds nor golden columns.
    """
    declared = meta.get("feature_allowlist")
    if declared is None:
        return [
            c
            for c, t in events.schema.items()
            if t.is_numeric()
            and c not in {"label", "event_id", "event_time"}
            and not c.endswith("_id")
            and c not in ENGINE_COLUMNS
        ]
    missing = [c for c in declared if c not in events.columns]
    if missing:
        raise ValueError(f"feature_allowlist names missing columns: {missing}")
    golden = set(meta.get("golden_columns", ()))
    forbidden = [
        c for c in declared if c == "label" or c in golden or c.endswith("_id") or c in ENGINE_COLUMNS
    ]
    if forbidden:
        raise ValueError(f"feature_allowlist contains forbidden columns: {forbidden}")
    wanted = set(declared)
    return [c for c in events.columns if c in wanted]
