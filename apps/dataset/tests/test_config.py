import pytest

from dataset.config import load


def _write(d, text):
    d.mkdir(parents=True, exist_ok=True)
    (d / "dataset.toml").write_text(text)
    return d


def test_load_and_mixed(tmp_path):
    d = _write(tmp_path / "shop", 'name = "shop"\nversion = "v1"\nkind = "spider2"\n'
                                  '[recipe]\n[results.mixed]\nt = ["a"]\n')
    cfg = load(d)
    assert (cfg.name, cfg.version, cfg.kind, cfg.dir) == ("shop", "v1", "spider2", d)
    assert cfg.mixed == {"t": ["a"]}
    assert cfg.recipe == {}


def test_name_must_match_folder(tmp_path):
    d = _write(tmp_path / "shop", 'name = "other"\nversion = "v1"\nkind = "spider2"\n')
    with pytest.raises(ValueError, match="other"):
        load(d)


def test_bad_kind_and_version(tmp_path):
    d = _write(tmp_path / "shop", 'name = "shop"\nversion = "1"\nkind = "spider2"\n')
    with pytest.raises(ValueError, match="version"):
        load(d)
    _write(d, 'name = "shop"\nversion = "v1"\nkind = "csv"\n')
    with pytest.raises(ValueError, match="kind"):
        load(d)
