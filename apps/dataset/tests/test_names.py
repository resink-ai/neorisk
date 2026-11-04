import pytest

from dataset.names import REPO, BadName, data_root, resolve


def test_default_root(monkeypatch):
    monkeypatch.delenv("NEORISK_DATA_ROOT", raising=False)
    assert data_root() == REPO / "data" / "datasets"
    assert (REPO / "datasets").is_dir()


def test_root_relative_and_trailing_slash(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NEORISK_DATA_ROOT", "rel/dir/")
    assert resolve("olist/v1/log/part-00000.parquet") == (
        tmp_path / "rel/dir/olist/v1/log/part-00000.parquet")
    assert resolve("olist/v1") == tmp_path / "rel/dir/olist/v1"


@pytest.mark.parametrize("name", ["../x/v1", "/abs/v1", "olist/1", "olist/v0", "Olist/v1",
                                  "olist//v1", "olist/v1/../../etc", "olist\\v1", "olist",
                                  "olist/v1/", ""])
def test_bad_names_refused(name):
    with pytest.raises(BadName):
        resolve(name)
