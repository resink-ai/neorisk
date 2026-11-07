"""Remote backends: a local folder (move + symlink back) and SSH (copy with rsync)."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from nds.config import NdsError

MANIFEST = ".nds-manifest.jsonl"


@dataclass
class Entry:
    size: int
    fp: str


def _replay(lines) -> dict[str, Entry]:
    """Later lines win. A torn last line from a crash is ignored."""
    out: dict[str, Entry] = {}
    for line in lines:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        out[rec["rel"]] = Entry(rec["size"], rec["fp"])
    return out


def _dump(rel: str, e: Entry) -> str:
    return json.dumps({"rel": rel, "size": e.size, "fp": e.fp}) + "\n"


class LocalRemote:
    """Files live under <path>/<dataset>/; an append-only manifest beside them records each one.

    Local means same machine, so push moves the file and leaves a symlink behind. The manifest
    line is appended before the symlink is made, so a crash never loses track of a moved file.
    """

    links_back = True

    def __init__(self, path: str, dataset: str):
        self.base = Path(path).expanduser() / dataset

    def file(self, rel: str) -> Path:
        return self.base / rel

    def list(self) -> dict[str, Entry]:
        try:
            return _replay(self.base.joinpath(MANIFEST).read_text().splitlines())
        except FileNotFoundError:
            return {}

    def record(self, rel: str, entry: Entry) -> None:
        self.base.mkdir(parents=True, exist_ok=True)
        with self.base.joinpath(MANIFEST).open("a") as f:
            f.write(_dump(rel, entry))

    def flush(self) -> None:
        pass

    def put(self, local: Path, rel: str) -> None:
        """Move `local` into the remote. The file only appears at its final name once complete."""
        dest = self.file(rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".nds-part")
        size = local.stat().st_size
        try:
            os.rename(local, tmp)  # same filesystem: instant
        except OSError:
            shutil.copy2(local, tmp)
            if tmp.stat().st_size != size:
                tmp.unlink()
                raise NdsError(f"copy of {rel} came out the wrong size")
        os.replace(tmp, dest)
        if local.exists() and not local.is_symlink():
            local.unlink()


class SshRemote:
    """Files copied to <host>:<path>/<dataset>/ with rsync; local files are left in place.

    Symlinks are followed, so a file already parked in a local remote can be copied on. The
    manifest is kept in memory and written once, atomically, at flush(). Local files stay put,
    so a crash before flush only means the next push re-checks those files.
    """

    links_back = False

    def __init__(self, host: str, path: str, dataset: str):
        self.host = host
        self.base = f"{path.rstrip('/')}/{dataset}"
        self._ssh = ["ssh", "-o", "BatchMode=yes"]
        self._entries: dict[str, Entry] | None = None

    def _run(self, cmd: str, data: str | None = None) -> str:
        p = subprocess.run(
            [*self._ssh, self.host, cmd], input=data, check=False, capture_output=True, text=True
        )
        if p.returncode != 0:
            raise NdsError(f"ssh {self.host}: {p.stderr.strip() or 'failed'}")
        return p.stdout

    def list(self) -> dict[str, Entry]:
        if self._entries is None:
            path = shlex.quote(f"{self.base}/{MANIFEST}")
            out = self._run(f"cat {path} 2>/dev/null || true")
            self._entries = _replay(out.splitlines())
        return self._entries

    def record(self, rel: str, entry: Entry) -> None:
        self.list()[rel] = entry

    def flush(self) -> None:
        if self._entries is None:
            return
        base, path = shlex.quote(self.base), shlex.quote(f"{self.base}/{MANIFEST}")
        body = "".join(_dump(r, e) for r, e in sorted(self._entries.items()))
        self._run(f"mkdir -p {base} && cat > {path}.tmp && mv {path}.tmp {path}", body)

    def _rsync(self, src: str, dst: str, rels: list[str]) -> None:
        if not rels:
            return
        cmd = ["rsync", "-aL", "--from0", "--files-from=-", "-e", " ".join(self._ssh), src, dst]
        p = subprocess.run(
            cmd, input="\0".join(rels) + "\0", check=False, capture_output=True, text=True
        )
        if p.returncode != 0:
            raise NdsError(f"rsync failed: {p.stderr.strip()[-500:]}")

    def put_many(self, root: Path, rels: list[str]) -> None:
        self._run(f"mkdir -p {shlex.quote(self.base)}")
        self._rsync(f"{root}/", f"{self.host}:{self.base}/", rels)

    def get_many(self, root: Path, rels: list[str]) -> None:
        self._rsync(f"{self.host}:{self.base}/", f"{root}/", rels)


def open_remote(spec: dict, dataset: str) -> LocalRemote | SshRemote:
    kind = spec.get("type")
    if kind == "local":
        return LocalRemote(spec["path"], dataset)
    if kind == "ssh":
        return SshRemote(spec["host"], spec["path"], dataset)
    raise NdsError(f"remote type {kind!r} is not implemented yet (only 'local' and 'ssh')")
