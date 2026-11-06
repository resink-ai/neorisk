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


def test_exact_columns_load(tmp_path):
    d = tmp_path / "x"
    d.mkdir()
    (d / "dataset.toml").write_text('name = "x"\nversion = "v1"\nkind = "spider2"\n'
                                    '[results.exact]\nt = ["a", "b"]\n')
    assert load(d).exact == {"t": ["a", "b"]}


SYNTH = '''name = "ecommerce"
version = "v1"
kind = "synthetic"

[recipe]
project = "examples/ecommerce"
profile = "sample"
seed = 7
overlay = []
designs = ["star", "dv", "an"]

[recipe.owners]
order_placed = "user_id"

[[check]]
table = "star_dim_sku"
simkit = "skus"
columns = { sku_id = "sku_id", category = "category", price = "price" }
'''


def test_synthetic_config_loads(tmp_path):
    cfg = load(_write(tmp_path / "ecommerce", SYNTH))
    assert cfg.designs == ["star", "dv", "an"]
    assert cfg.owners == {"order_placed": "user_id"}
    assert cfg.checks[0]["columns"]["price"] == "price"
    assert cfg.checks[0]["where"] == "" and cfg.checks[0]["simkit_where"] == ""
    assert cfg.recipe["seed"] == 7


@pytest.mark.parametrize(("old", "new", "field"), [
    ('designs = ["star", "dv", "an"]', 'designs = ["star", "dv", "snow"]', "snow"),
    ('designs = ["star", "dv", "an"]', 'designs = ["star", "dv"]', "designs"),
    ('project = "examples/ecommerce"\n', "", "project"),
    ('profile = "sample"\n', "", "profile"),
    ("seed = 7\n", "", "seed"),
    ('table = "star_dim_sku"\n', "", "table"),
])
def test_synthetic_config_refuses(tmp_path, old, new, field):
    d = _write(tmp_path / "ecommerce", SYNTH.replace(old, new))
    with pytest.raises(ValueError, match=field):
        load(d)


def test_spider2_config_has_no_designs(tmp_path):
    cfg = load(_write(tmp_path / "shop", 'name = "shop"\nversion = "v1"\nkind = "spider2"\n'))
    assert cfg.designs == [] and cfg.checks == [] and cfg.owners == {}
