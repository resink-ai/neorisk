import os
from pathlib import Path

import pytest

from nds import ops
from nds.cli import main
from nds.config import Config, NdsError
from nds.fingerprint import CHUNK, fingerprint
from nds.remote import open_remote


@pytest.fixture
def ds(tmp_path):
    root, store = tmp_path / "spider2", tmp_path / "store"
    (root / "sub").mkdir(parents=True)
    (root / "a.bin").write_bytes(b"aaa")
    (root / "sub" / "b.bin").write_bytes(b"bbbb")
    (root / "sub" / "x.tmp").write_bytes(b"junk")
    cfg = Config(
        root=root,
        dataset="spider2",
        default_remote="home",
        remotes={"home": {"type": "local", "path": str(store)}},
        exclude=["*.tmp"],
    )
    cfg.save()
    return cfg, open_remote(cfg.remotes["home"], "spider2")


def always(action):
    return lambda *_: action


def test_push_moves_and_links(ds):
    cfg, remote = ds
    res = ops.push(cfg, remote, always(ops.ABORT))
    assert res.files == {"a.bin": "pushed", "sub/b.bin": "pushed"}
    assert (cfg.root / "a.bin").is_symlink()
    assert (cfg.root / "a.bin").read_bytes() == b"aaa"
    assert remote.file("sub/b.bin").read_bytes() == b"bbbb"
    assert not (cfg.root / "sub" / "x.tmp").is_symlink()  # excluded
    assert set(remote.list()) == {"a.bin", "sub/b.bin"}


def test_push_is_idempotent(ds):
    cfg, remote = ds
    ops.push(cfg, remote, always(ops.ABORT))
    assert set(ops.push(cfg, remote, always(ops.ABORT)).files.values()) == {"stored"}


def test_conflict_policies(ds):
    cfg, remote = ds
    ops.push(cfg, remote, always(ops.ABORT))
    (cfg.root / "a.bin").unlink()
    (cfg.root / "a.bin").write_bytes(b"changed")  # same path, new content
    with pytest.raises(NdsError, match="conflict on a.bin"):
        ops.push(cfg, remote, always(ops.ABORT))
    assert not (cfg.root / "a.bin").is_symlink()  # untouched after abort
    assert ops.push(cfg, remote, always(ops.SKIP)).files["a.bin"] == "conflict"
    assert remote.file("a.bin").read_bytes() == b"aaa"
    assert ops.push(cfg, remote, always(ops.OVERWRITE)).files["a.bin"] == "pushed"
    assert remote.file("a.bin").read_bytes() == b"changed"


def test_identical_local_copy_is_just_relinked(ds):
    cfg, remote = ds
    ops.push(cfg, remote, always(ops.ABORT))
    (cfg.root / "a.bin").unlink()
    (cfg.root / "a.bin").write_bytes(b"aaa")
    assert ops.push(cfg, remote, always(ops.ABORT)).files["a.bin"] == "stored"
    assert (cfg.root / "a.bin").is_symlink()


def test_edit_through_symlink_is_modified_then_updated(ds):
    cfg, remote = ds
    ops.push(cfg, remote, always(ops.ABORT))
    (cfg.root / "a.bin").write_bytes(b"edited!")  # writes through to the remote
    assert ops.status(cfg, remote).files["a.bin"] == "modified"
    assert ops.push(cfg, remote, always(ops.ABORT)).files["a.bin"] == "updated"
    assert ops.status(cfg, remote).files["a.bin"] == "stored"


def test_status_new_and_conflict(ds):
    cfg, remote = ds
    assert set(ops.status(cfg, remote).files.values()) == {"new"}
    ops.push(cfg, remote, always(ops.ABORT))
    (cfg.root / "a.bin").unlink()
    (cfg.root / "a.bin").write_bytes(b"zzz")
    assert ops.status(cfg, remote).files["a.bin"] == "conflict"


def test_pull_restores_links_on_fresh_checkout(ds):
    cfg, remote = ds
    ops.push(cfg, remote, always(ops.ABORT))
    for rel in ("a.bin", "sub/b.bin"):
        (cfg.root / rel).unlink()
    res = ops.pull(cfg, remote, always(ops.ABORT))
    assert set(res.files.values()) == {"linked"}
    assert (cfg.root / "sub" / "b.bin").read_bytes() == b"bbbb"


def test_pull_conflict_with_local_file(ds):
    cfg, remote = ds
    ops.push(cfg, remote, always(ops.ABORT))
    (cfg.root / "a.bin").unlink()
    (cfg.root / "a.bin").write_bytes(b"mine")
    assert ops.pull(cfg, remote, always(ops.SKIP)).files["a.bin"] == "conflict"
    assert (cfg.root / "a.bin").read_bytes() == b"mine"


def test_include_exclude_flags(ds):
    cfg, remote = ds
    res = ops.push(cfg, remote, always(ops.ABORT), exclude=["sub/**"])
    assert res.files == {"a.bin": "pushed"}


def test_sampled_fingerprint_misses_gap_edit_but_full_catches_it(tmp_path):
    f = tmp_path / "big"
    f.write_bytes(bytes(5 * CHUNK))
    before_s, before_f = fingerprint(f), fingerprint(f, full=True)
    with f.open("r+b") as h:
        h.seek(CHUNK + 10)  # between head and middle samples
        h.write(b"x")
    assert fingerprint(f) == before_s
    assert fingerprint(f, full=True) != before_f


def test_cli_roundtrip(tmp_path, capsys):
    root, store = tmp_path / "d", tmp_path / "new" / "store"
    root.mkdir()
    (root / "f.csv").write_text("1,2")
    assert main(["-C", str(root), "init", "--path", str(store)]) == 0
    assert store.is_dir()  # init created the missing remote folder
    assert main(["-C", str(root), "push"]) == 0
    assert (root / "f.csv").is_symlink()
    capsys.readouterr()
    assert main(["-C", str(root), "ls-remote"]) == 0
    assert "f.csv" in capsys.readouterr().out
    assert main(["-C", str(root), "remote", "add", "lake", "--type", "s3"]) == 0
    assert main(["-C", str(root), "push", "-r", "lake"]) == 1  # not implemented yet, clean error
    assert os.path.exists(Path(root / "nds.yaml"))


def test_nested_dataset_is_left_to_its_own_nds_yaml(tmp_path):
    store = tmp_path / "store"
    parent = tmp_path / "data"
    for name in ("a", "b"):
        (parent / name).mkdir(parents=True)
        (parent / name / "f.csv").write_text(name)
    assert main(["-C", str(parent / "a"), "init", "--path", str(store)]) == 0
    assert main(["-C", str(parent / "a"), "push"]) == 0
    assert main(["-C", str(parent), "init", "--path", str(store)]) == 0
    assert main(["-C", str(parent), "push"]) == 0  # run again from the parent
    assert main(["-C", str(parent), "push"]) == 0  # and again: nothing changes
    assert (parent / "a" / "nds.yaml").is_file() and not (parent / "a" / "nds.yaml").is_symlink()
    assert (parent / "b" / "f.csv").is_symlink()
    assert not (store / "data" / "a").exists()  # a/ stays owned by dataset "a"


def _multi(tmp_path):
    root, store = tmp_path / "data", tmp_path / "store"
    for name in ("spider2", "eth", "ref"):
        (root / name).mkdir(parents=True)
        (root / name / "f.csv").write_text(name)
    (root / "eth" / "raw").mkdir()
    (root / "eth" / "raw" / "big.bin").write_text("raw")
    (root / "ref" / "x.tmp").write_text("junk")
    (root / "nds.yaml").write_text(
        f"""default_remote: home
remotes:
  home: {{type: local, path: {store}}}
exclude: ["*.tmp"]
datasets:
  spider2: {{path: spider2}}
  eth: {{path: eth, exclude: ["raw/**"]}}
  ref: {{path: ref}}
"""
    )
    return root, store


def test_datasets_push_one_then_all(tmp_path):
    root, store = _multi(tmp_path)
    assert main(["-C", str(root), "push", "spider2"]) == 0
    assert (root / "spider2" / "f.csv").is_symlink() and not (root / "eth" / "f.csv").is_symlink()
    assert main(["-C", str(root), "push", "--all"]) == 0  # the later run does not conflict
    assert main(["-C", str(root), "push", "--all"]) == 0  # and is idempotent
    for name in ("spider2", "eth", "ref"):
        assert (store / name / "f.csv").read_text() == name  # one folder per dataset
        assert (store / name / ".nds-manifest.jsonl").exists()  # one manifest per dataset
    assert not (root / "eth" / "raw" / "big.bin").is_symlink()  # dataset-level exclude
    assert not (root / "ref" / "x.tmp").is_symlink()  # shared exclude


def test_datasets_need_a_name_or_all(tmp_path, capsys):
    root, _ = _multi(tmp_path)
    assert main(["-C", str(root), "push"]) == 1
    assert main(["-C", str(root), "push", "nope"]) == 1
    assert "unknown dataset" in capsys.readouterr().err
    assert not (root / "spider2" / "f.csv").is_symlink()


def test_datasets_overlap_and_escape_rejected(tmp_path):
    root, _ = _multi(tmp_path)
    cfg = Config.load(root)
    cfg.datasets["inner"] = {"path": "eth/raw"}
    with pytest.raises(NdsError, match="overlap"):
        cfg.check_datasets()
    cfg.datasets = {"bad": {"path": "../elsewhere"}}
    with pytest.raises(NdsError, match="inside this folder"):
        cfg.check_datasets()


def test_dataset_add_and_pull_all(tmp_path):
    root, _ = _multi(tmp_path)
    (root / "extra").mkdir()
    assert main(["-C", str(root), "dataset", "add", "extra"]) == 0
    assert "extra" in Config.load(root).datasets
    assert main(["-C", str(root), "push", "--all"]) == 0
    (root / "ref" / "f.csv").unlink()
    assert main(["-C", str(root), "pull", "ref"]) == 0
    assert (root / "ref" / "f.csv").read_text() == "ref"


@pytest.fixture
def fake_ssh(tmp_path, monkeypatch):
    """An `ssh` that runs the command locally, so SshRemote is exercised without a network."""
    script = tmp_path / "fakessh"
    script.write_text('#!/bin/sh\nshift\nif [ $# -eq 1 ]; then exec sh -c "$1"; fi\nexec "$@"\n')
    script.chmod(0o755)
    from nds import remote as r

    real_init = r.SshRemote.__init__

    def init(self, host, path, dataset):
        real_init(self, host, path, dataset)
        self._ssh = [str(script)]

    monkeypatch.setattr(r.SshRemote, "__init__", init)


def test_ssh_remote_copies_and_follows_local_symlinks(tmp_path, fake_ssh):
    root, home, far = tmp_path / "data", tmp_path / "home", tmp_path / "far"
    (root / "ds" / "sub").mkdir(parents=True)
    (root / "ds" / "a.bin").write_text("aaa")
    (root / "ds" / "sub" / "b.bin").write_text("bbbb")
    (root / "nds.yaml").write_text(
        f"""default_remote: home
remotes:
  home: {{type: local, path: {home}}}
  desk: {{type: ssh, host: desk, path: {far}}}
datasets:
  ds: {{path: ds}}
"""
    )
    n = ["-C", str(root)]
    assert main([*n, "push", "ds", "-r", "home"]) == 0  # parks the files, leaves symlinks
    assert (root / "ds" / "a.bin").is_symlink()
    assert main([*n, "push", "ds", "-r", "desk"]) == 0  # copies through the symlinks
    assert (far / "ds" / "sub" / "b.bin").read_text() == "bbbb"
    assert not (far / "ds" / "a.bin").is_symlink()
    assert (root / "ds" / "a.bin").is_symlink()  # still the local-remote link
    assert main([*n, "push", "ds", "-r", "desk"]) == 0  # idempotent: nothing re-sent
    assert main([*n, "ls-remote", "ds", "-r", "desk"]) == 0
    (root / "ds" / "sub" / "b.bin").unlink()
    (root / "ds" / "sub" / "b.bin").write_text("changed")  # now differs from the desk copy
    assert main([*n, "push", "ds", "-r", "desk"]) == 1  # non-interactive conflict aborts
    assert main([*n, "push", "ds", "-r", "desk", "--force"]) == 0
    assert (far / "ds" / "sub" / "b.bin").read_text() == "changed"
    (root / "ds" / "a.bin").unlink()  # lose a file locally...
    assert main([*n, "pull", "ds", "-r", "desk"]) == 0  # ...and get it back from the desk
    assert (root / "ds" / "a.bin").read_text() == "aaa"
