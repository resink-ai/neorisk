import json

from dataset import cli, config


def _last(capsys) -> dict:
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_cli_build_verify_shop(shop_cli, capsys):
    assert cli.main(["build", "shop", "--db", str(shop_cli)]) == 0
    assert _last(capsys)["counts"]["log"] == 7
    assert cli.main(["verify", "shop"]) == 0
    out = _last(capsys)
    assert out == {"name": "shop", "tables": 2, "queries": 1, "failed": []}


def test_cli_resolve_bad_name_exit_2(capsys):
    assert cli.main(["resolve", "../etc/v1"]) == 2
    assert cli.main(["resolve", "olist/v1/log"]) == 0
    assert capsys.readouterr().out.strip().endswith("olist/v1/log")


def test_cli_build_missing_source_exit_2(shop_cli, tmp_path, capsys):
    assert cli.main(["build", "shop", "--db", str(tmp_path / "nope.sqlite")]) == 2
    assert "refdata fetch" in capsys.readouterr().err
    assert cli.main(["build", "nosuch"]) == 2


def test_cli_list_states(shop_cli, capsys):
    def state():
        assert cli.main(["list", "--json"]) == 0
        return {r["name"]: r["built"] for r in json.loads(capsys.readouterr().out)}
    assert state() == {"shop": "no"}
    cli.main(["build", "shop", "--db", str(shop_cli)])
    capsys.readouterr()
    assert state() == {"shop": "unrecorded"}
    cli.main(["build", "shop", "--db", str(shop_cli), "--record"])
    capsys.readouterr()
    assert state() == {"shop": "yes"}


def test_cli_verify_failure_exit_1(shop_cli, capsys):
    cli.main(["build", "shop", "--db", str(shop_cli)])
    b = config.DATASETS / "shop" / "specs" / "build.sql"
    b.write_text(b.read_text().replace("p.total / 100.0", "p.total / 10.0"))
    assert cli.main(["verify", "shop"]) == 1
    assert _last(capsys)["failed"] == ["recipe", "orders", "q1"]


def test_context_prints_catalogue_from_build(shop_cli, capsys):
    assert cli.main(["context", "shop"]) == 2                 # not built yet
    cli.main(["build", "shop", "--db", str(shop_cli)])
    capsys.readouterr()
    assert cli.main(["context", "shop"]) == 0
    out = capsys.readouterr().out
    assert "The input is one ordered event log of 7 events" in out
    assert "| `customers_created` | entity | 2 | `customer_id`, `ext_id`, `city` |" in out
    assert "| `orders` | 3 | 6 | none |" in out
    assert "(`q1`)" in out
    assert "uv run dataset build shop" in out


def test_context_intro_counts_read_naturally():
    from dataset.context import _intro
    assert _intro("v1", "spider2", 7, 1, 0) == (
        "Version `v1`, kind `spider2`. The input is one ordered event log of 7 events; the output "
        "is the source table, rebuilt exactly.")
    assert _intro("v1", "spider2", 1, 2, 1).endswith(
        "of 1 event; the output is the 2 source tables, rebuilt exactly, and the answer to 1 "
        "saved Spider 2.0 question.")
