import zipfile

import pytest

from refdata import cli, fetch


def test_verify_rejects_wrong_hash(tmp_path):
    p = tmp_path / "x.zip"
    p.write_bytes(b"hello")
    with pytest.raises(ValueError) as e:
        fetch.verify(p, "0" * 64)
    assert "0" * 64 in str(e.value)
    assert "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824" in str(e.value)


def test_unpack_keeps_only_sqlite(tmp_path):
    z = tmp_path / "db.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("a.sqlite", b"db")
        f.writestr("__MACOSX/._a.sqlite", b"junk")
        f.writestr("local-map.jsonl", b"{}")
    dest = tmp_path / "out"
    assert fetch.unpack(z, dest) == [dest / "a.sqlite"]
    assert sorted(p.name for p in dest.iterdir()) == ["a.sqlite"]


def test_cli_fetch_skips_when_present(tmp_path, monkeypatch):
    (tmp_path / "a.sqlite").write_bytes(b"db")
    monkeypatch.setattr(fetch, "EXPECTED", ["a.sqlite"])

    def boom(*a, **k):
        raise AssertionError("must not download")

    monkeypatch.setattr(fetch.urllib.request, "urlopen", boom)
    assert cli.main(["fetch", "--dest", str(tmp_path)]) == 0
