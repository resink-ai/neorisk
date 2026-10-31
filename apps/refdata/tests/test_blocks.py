import pytest

from refdata.blocks import Block, parse_blocks
from refdata.source import Source, load_source

ALL = {"event", "entity", "table"}


def test_parse_two_blocks_with_opts():
    text = ("-- event: order_placed owner=order_id ord=o\nSELECT 1;\n"
            "-- entity: orders\nSELECT 2;")
    assert parse_blocks(text, ALL) == [
        Block("event", "order_placed", {"owner": "order_id", "ord": "o"}, "SELECT 1;"),
        Block("entity", "orders", {}, "SELECT 2;"),
    ]


def test_comments_before_first_block_ignored():
    text = "-- a file comment\n\n-- table: t\nSELECT 1"
    assert parse_blocks(text, ALL) == [Block("table", "t", {}, "SELECT 1")]


def test_duplicate_name_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        parse_blocks("-- table: t\nSELECT 1\n-- table: t\nSELECT 2", ALL)


def test_kind_not_allowed():
    with pytest.raises(ValueError, match="line 1"):
        parse_blocks("-- table: t\nSELECT 1", {"event", "entity"})


def test_empty_sql_rejected():
    with pytest.raises(ValueError, match="line 1"):
        parse_blocks("-- table: t\n\n-- table: u\nSELECT 1", ALL)


def test_load_source(tmp_path):
    (tmp_path / "specs").mkdir()
    (tmp_path / "specs" / "source.toml").write_text(
        'file = "E_commerce.sqlite"\nnote = "wall clock as UTC"\n'
        '[tables]\norders = ["order_id"]\ngeolocation = []\n')
    assert load_source(tmp_path) == Source("E_commerce.sqlite",
                                           {"orders": ["order_id"], "geolocation": []},
                                           "wall clock as UTC")
