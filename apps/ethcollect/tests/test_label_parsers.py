import json
from datetime import date

import pytest

from ethcollect import tables
from ethcollect.connectors.cryptoscamdb import connector as cryptoscamdb
from ethcollect.connectors.eth_labels import connector as eth_labels
from ethcollect.connectors.forta import connector as forta
from ethcollect.connectors.huione import connector as huione
from ethcollect.connectors.mew_darklist import connector as mew
from ethcollect.connectors.ofac import connector as ofac
from ethcollect.connectors.scamsniffer import connector as scamsniffer
from ethcollect.connectors.stablecoin_freezes import connector as freezes

A = "0x" + "ab" * 20
B = "0x" + "cd" * 20


def test_norm_lowercases_and_rejects_non_addresses():
    assert tables.norm(" 0xABAB" + "ab" * 18 + " ") == A
    assert tables.norm("0x123") is None
    assert tables.norm("0x" + "zz" * 20) is None
    assert tables.norm(None) is None


def test_ofac_one_address_per_line_is_sanctioned_high_trust():
    rows = ofac.parse(f"{A.upper().replace('X', 'x')}\n\n{B}\n".encode())
    assert [r["address"] for r in rows] == [A, B]
    assert {r["label_kind"] for r in rows} == {"sanctioned"}
    assert rows[0]["trust"] == tables.TRUST["high"] and rows[0]["is_risk"]
    assert rows[0]["date_known"] is False


def test_scamsniffer_json_list_is_phishing():
    rows = scamsniffer.parse(json.dumps([A, "not-an-address"]).encode())
    assert [(r["address"], r["label_kind"]) for r in rows] == [(A, "phishing")]


def test_mew_darklist_keeps_its_date_and_comment():
    body = json.dumps([{"address": A, "comment": "fake airdrop", "date": "2020-11-17"},
                       {"address": B, "comment": "x", "date": "garbage"}]).encode()
    a, b = mew.parse(body)
    assert a["observed_at"] == date(2020, 11, 17) and a["date_known"] and a["source_ref"]
    assert b["date_known"] is False


def test_cryptoscamdb_yaml_category_sets_kind():
    body = (f"- name: x\n  url: http://x\n  category: Phishing\n  addresses:\n    ETH:\n"
            f"    - \"{A}\"\n- name: y\n  category: Scamming\n  addresses:\n    ETH:\n"
            f"    - \"{B}\"\n- name: z\n  category: Phishing\n").encode()
    rows = cryptoscamdb.parse(body)
    assert {(r["address"], r["label_kind"]) for r in rows} == {(A, "phishing"), (B, "scam")}


@pytest.mark.parametrize(("header", "line", "expected"), [
    ("address,etherscan_tag,etherscan_labels,is_contract",
     f"{A},Fake_Phishing1,phish-hack,False", {(A, "phishing")}),
    ("banned_address,wallet_tag,data_source",
     f"{A},Exploiter 3,etherscan-heist", {(A, "hack")}),
    (("contract_address,contract_tag,contract_creator,contract_creation_tx,contract_creator_tag,"
      "source,notes,contract_creator_etherscan_label"),
     f"{A},Multichain Exploiter,{B},0xtx,,Luabase,,exploit", {(A, "hack"), (B, "hack")}),
])
def test_forta_recognises_each_file_by_header(header, line, expected):
    rows = forta.parse(f"{header}\n{line}\n".encode())
    assert {(r["address"], r["label_kind"]) for r in rows} == expected


@pytest.mark.parametrize(("label", "tag", "expected"), [
    ("ofac-sanctions-lists", "", ("sanctioned", "high")),
    ("bybit-exploit", "Bybit Exploiter 4", ("hack", "medium")),
    ("tornado-cash", "Tornado.Cash: Router", ("mixer", "medium")),
    ("coinbase", "Coinbase 10", ("exchange", "medium")),
    ("bridged-token", "", None),
    ("bridge", "", ("bridge", "medium")),
    ("uniswap", "", ("dex", "medium")),
    ("genesis-address", "", None),
])
def test_eth_labels_classify(label, tag, expected):
    assert eth_labels.classify(label, tag) == expected


def test_eth_labels_skips_other_chains_and_marks_services_not_risky():
    body = (f"address,chainId,label,nameTag\n{A},1,kraken,Kraken 4\n{B},8453,kraken,x\n").encode()
    (row,) = eth_labels.parse(body)
    assert row["label_kind"] == "exchange" and row["is_risk"] is False


def test_huione_requires_a_source_url_and_keeps_only_ethereum():
    body = ("address,chain,claim,source_url,observed_at\n"
            f"{A},ethereum,Huione Pay hot wallet,https://example.org/r,2025-10-16\n"
            f"{B},ethereum,no source,,\n"
            f"{B},tron,tron row,https://example.org/t,\n").encode()
    rows, rejected = huione.parse(body)
    assert [r["address"] for r in rows] == [A] and rejected == [B]
    assert rows[0]["observed_at"] == date(2025, 10, 16) and "https://example.org/r" in (
        rows[0]["source_ref"])


def test_shipped_huione_seeds_file_parses():
    _rows, rejected = huione.parse(huione.SEEDS.read_bytes())
    assert rejected == []


def test_freeze_address_comes_from_data_for_usdt_and_topic1_for_usdc():
    usdt = {"data": "0x" + "0" * 24 + A[2:], "topics": ["0xt", None], "timeStamp": "0x68f4b747",
            "transactionHash": "0xh"}
    usdc = {"data": "0x", "topics": ["0xt", "0x" + "0" * 24 + B[2:]], "timeStamp": "1760000000",
            "transactionHash": "0xh2"}
    rows = freezes.parse([usdt], "USDT", "data") + freezes.parse([usdc], "USDC", "topic1")
    assert [(r["address"], r["label_kind"], r["date_known"]) for r in rows] == [
        (A, "frozen", True), (B, "frozen", True)]
    assert rows[0]["observed_at"] == date(2025, 10, 19)


def test_unknown_label_kind_is_refused():
    with pytest.raises(ValueError):
        tables.label_rows([A], kind="suspicious", source="x", trust="low")
