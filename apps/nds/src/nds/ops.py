"""status / push / pull over one dataset folder and one remote."""

import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from nds.config import CONFIG_NAME, Config, NdsError
from nds.fingerprint import fingerprint, mode_is_full
from nds.remote import Entry, LocalRemote

OVERWRITE, SKIP, ABORT = "overwrite", "skip", "abort"
ConflictPolicy = Callable[[str, str, str], str]  # (rel, local fp, remote fp) -> action


@dataclass
class Result:
    # rel -> state: new, stored, modified, conflict, pushed, updated, skipped, linked, pulled
    files: dict[str, str] = field(default_factory=dict)


def walk(cfg: Config, include: list[str], exclude: list[str]) -> Iterator[str]:
    for dirpath, dirnames, filenames in os.walk(cfg.root, followlinks=False):
        # a folder with its own nds.yaml is a separate dataset: leave it to its own push
        dirnames[:] = sorted(d for d in dirnames if not (Path(dirpath) / d / CONFIG_NAME).exists())
        for name in sorted(filenames):
            rel = (Path(dirpath) / name).relative_to(cfg.root).as_posix()
            if cfg.selects(rel, include, exclude):
                yield rel


def _points_into(link: Path, remote: LocalRemote, rel: str) -> bool:
    return link.is_symlink() and Path(os.readlink(link)) == remote.file(rel)


def _remote_fp_in_mode(remote: LocalRemote, rel: str, entry: Entry, full: bool) -> str:
    """The remote's fingerprint in the local run's mode, re-reading the remote file if needed."""
    if mode_is_full(entry.fp) == full:
        return entry.fp
    return fingerprint(remote.file(rel), full=full)


def status(cfg: Config, remote, include=(), exclude=(), full=False) -> Result:
    res, stored = Result(), remote.list()
    if not remote.links_back:
        for rel, path, entry in _copy_candidates(cfg, remote, include, exclude, res):
            res.files[rel] = "new" if entry is None else _copy_state(path, entry, full)
        return res
    for rel in walk(cfg, list(include), list(exclude)):
        path, entry = cfg.root / rel, stored.get(rel)
        if path.is_symlink():
            if entry and _points_into(path, remote, rel):
                same = fingerprint(path, full=mode_is_full(entry.fp)) == entry.fp
                res.files[rel] = "stored" if same else "modified"
            else:
                res.files[rel] = "skipped"  # a symlink we did not make
            continue
        if entry is None:
            res.files[rel] = "new"
        else:
            local_fp = fingerprint(path, full=full)
            same = local_fp == _remote_fp_in_mode(remote, rel, entry, full)
            res.files[rel] = "stored" if same else "conflict"
    return res


def push(
    cfg: Config, remote: LocalRemote, policy: ConflictPolicy, include=(), exclude=(), full=False
) -> Result:
    if not remote.links_back:
        return _push_copy(cfg, remote, policy, include, exclude, full)
    res, stored = Result(), remote.list()
    for rel in walk(cfg, list(include), list(exclude)):
        path, entry = cfg.root / rel, stored.get(rel)
        if path.is_symlink():
            if entry and _points_into(path, remote, rel):
                fp = fingerprint(path, full=mode_is_full(entry.fp))
                if fp != entry.fp:  # edited through the link: the remote copy is the truth
                    remote.record(rel, Entry(path.stat().st_size, fp))
                    res.files[rel] = "updated"
                else:
                    res.files[rel] = "stored"
            else:
                res.files[rel] = "skipped"
            continue
        fp = fingerprint(path, full=full)
        if entry is not None:
            remote_fp = _remote_fp_in_mode(remote, rel, entry, full)
            if remote_fp != fp:
                action = policy(rel, fp, remote_fp)
                if action == ABORT:
                    raise NdsError(f"conflict on {rel}: remote has different content; aborting")
                if action == SKIP:
                    res.files[rel] = "conflict"
                    continue
            else:
                _link(path, remote, rel, drop_local=True)
                res.files[rel] = "stored"
                continue
        size = path.stat().st_size
        remote.put(path, rel)
        remote.record(rel, Entry(size, fp))
        _link(path, remote, rel, drop_local=False)
        res.files[rel] = "pushed"
    return res


def _link(path: Path, remote: LocalRemote, rel: str, drop_local: bool) -> None:
    """Replace `path` with a symlink to the remote copy, atomically."""
    target = remote.file(rel)
    if drop_local and target.stat().st_size != path.stat().st_size:
        raise NdsError(
            f"remote copy of {rel} has a different size; refusing to replace the local file"
        )
    tmp = path.with_name(path.name + ".nds-link")
    tmp.unlink(missing_ok=True)
    tmp.symlink_to(target)
    os.replace(tmp, path)


def pull(
    cfg: Config, remote: LocalRemote, policy: ConflictPolicy, include=(), exclude=(), full=False
) -> Result:
    if not remote.links_back:
        return _pull_copy(cfg, remote, policy, include, exclude, full)
    res = Result()
    for rel, entry in sorted(remote.list().items()):
        if not cfg.selects(rel, list(include), list(exclude)):
            continue
        path = cfg.root / rel
        if not remote.file(rel).exists():
            res.files[rel] = "skipped"  # in the manifest but gone from the remote
            continue
        if _points_into(path, remote, rel):
            res.files[rel] = "stored"
            continue
        if path.exists() or path.is_symlink():
            local_fp = fingerprint(path, full=full)
            remote_fp = _remote_fp_in_mode(remote, rel, entry, full)
            if local_fp != remote_fp:
                action = policy(rel, local_fp, remote_fp)
                if action == ABORT:
                    raise NdsError(f"conflict on {rel}: local file differs; aborting")
                if action == SKIP:
                    res.files[rel] = "conflict"
                    continue
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".nds-link")
        tmp.unlink(missing_ok=True)
        tmp.symlink_to(remote.file(rel))
        os.replace(tmp, path)
        res.files[rel] = "linked"
    return res


# --- remotes that copy (ssh): local files stay where they are -------------------------------


def _copy_candidates(cfg, remote, include, exclude, res):
    stored = remote.list()
    for rel in walk(cfg, list(include), list(exclude)):
        path = cfg.root / rel
        if not path.exists():  # a dangling symlink: nothing to copy
            res.files[rel] = "skipped"
            continue
        yield rel, path, stored.get(rel)


def _copy_state(path: Path, entry: Entry, full: bool) -> str:
    # compare in the mode the manifest used, so mixed --full / sampled runs still agree
    return "stored" if fingerprint(path, full=mode_is_full(entry.fp)) == entry.fp else "conflict"


def _push_copy(cfg, remote, policy, include, exclude, full) -> Result:
    res, todo = Result(), []
    for rel, path, entry in _copy_candidates(cfg, remote, include, exclude, res):
        fp = fingerprint(path, full=mode_is_full(entry.fp) if entry else full)
        if entry is not None and fp == entry.fp:
            res.files[rel] = "stored"
            continue
        if entry is not None:
            action = policy(rel, fp, entry.fp)
            if action == ABORT:
                raise NdsError(f"conflict on {rel}: remote has different content; aborting")
            if action == SKIP:
                res.files[rel] = "conflict"
                continue
        todo.append((rel, path.stat().st_size, fp))
    if todo:
        remote.put_many(cfg.root, [rel for rel, _, _ in todo])
        for rel, size, fp in todo:
            remote.record(rel, Entry(size, fp))
            res.files[rel] = "pushed"
        remote.flush()
    return res


def _pull_copy(cfg, remote, policy, include, exclude, full) -> Result:
    res, todo = Result(), []
    for rel, entry in sorted(remote.list().items()):
        if not cfg.selects(rel, list(include), list(exclude)):
            continue
        path = cfg.root / rel
        if path.exists():
            if _copy_state(path, entry, full) == "stored":
                res.files[rel] = "stored"
                continue
            fp = fingerprint(path, full=mode_is_full(entry.fp))
            action = policy(rel, fp, entry.fp)
            if action == ABORT:
                raise NdsError(f"conflict on {rel}: local file differs; aborting")
            if action == SKIP:
                res.files[rel] = "conflict"
                continue
        todo.append(rel)
    remote.get_many(cfg.root, todo)
    for rel in todo:
        res.files[rel] = "pulled"
    return res
