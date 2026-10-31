import json
import sqlite3

from refdata import cli
from refdata.compare import compare


def _db(path, rows, ddl="CREATE TABLE t (k TEXT, x)"):
    con = sqlite3.connect(path)
    con.execute(ddl)
    con.executemany("INSERT INTO t VALUES (?, ?)", rows)
    con.commit()
    con.close()
    return path


def _project(tmp_path, queries=None):
    proj = tmp_path / "p"
    (proj / "specs" / "queries").mkdir(parents=True, exist_ok=True)
    (proj / "specs" / "source.toml").write_text('file = "a.sqlite"\n[tables]\nt = ["k"]\n')
    for name, sql in (queries or {}).items():
        (proj / "specs" / "queries" / f"{name}.sql").write_text(sql)
    return proj


def test_identical_files_ok(tmp_path):
    rows = [("a", 1), ("b", 2.5)]
    r = compare(_db(tmp_path / "a", rows), _db(tmp_path / "b", rows), _project(tmp_path))
    assert r.ok


def test_int_vs_real_equal(tmp_path):
    r = compare(_db(tmp_path / "a", [("a", 62)]), _db(tmp_path / "b", [("a", 62.0)]),
                _project(tmp_path))
    assert r.ok


def test_null_empty_backslash_n_distinct(tmp_path):
    vals = [None, "", "\\N"]
    src = _db(tmp_path / "src", [(str(i), v) for i, v in enumerate(vals)])
    for i, j in ((0, 1), (0, 2), (1, 2)):
        swapped = list(vals)
        swapped[i], swapped[j] = swapped[j], swapped[i]
        reb = _db(tmp_path / f"r{i}{j}", [(str(k), v) for k, v in enumerate(swapped)])
        assert not compare(src, reb, _project(tmp_path)).ok


def test_multiset_counts_duplicates(tmp_path):
    r = compare(_db(tmp_path / "a", [("a", 1), ("a", 1)]), _db(tmp_path / "b", [("a", 1)]),
                _project(tmp_path))
    assert not r.ok
    t = r.tables[0]
    assert (t.rows_source, t.rows_rebuilt, t.missing, t.extra) == (2, 1, [("a", 1.0)], [])


def test_row_order_ignored(tmp_path):
    rows = [("a", 1), ("b", 2), ("c", 3)]
    r = compare(_db(tmp_path / "a", rows), _db(tmp_path / "b", rows[::-1]), _project(tmp_path))
    assert r.ok


def test_query_float_tolerance(tmp_path):
    xs = [0.1, 0.2, 0.3]
    assert (0.1 + 0.2) + 0.3 != (0.3 + 0.2) + 0.1         # the order changes the last bit
    src = _db(tmp_path / "a", [(str(i), x) for i, x in enumerate(xs)])
    reb = _db(tmp_path / "b", [(str(i), x) for i, x in reversed(list(enumerate(xs)))])
    proj = _project(tmp_path, {"q1": "SELECT sum(x) AS s FROM t"})
    assert compare(src, reb, proj).ok
    bumped = _db(tmp_path / "c", [(str(i), x * (1 + 1e-6) if i == 0 else x)
                                  for i, x in enumerate(xs)])
    r = compare(src, bumped, proj)
    assert [q.ok for q in r.queries] == [False]
    assert not r.tables[0].ok                              # tables never get a tolerance


def test_ordered_query_compares_as_list(tmp_path):
    proj = _project(tmp_path, {"ord": "SELECT k FROM t ORDER BY x"})
    src = _db(tmp_path / "a", [("a", 1), ("b", 2)])
    reb = _db(tmp_path / "b", [("a", 2), ("b", 1)])
    r = compare(src, reb, proj)
    assert [q.ok for q in r.queries] == [False]
    proj2 = _project(tmp_path / "y", {"set": "SELECT k FROM t"})
    assert [q.ok for q in compare(src, reb, proj2).queries] == [True]


def test_roundtrip_fixture_exit_0(shop, tmp_path, capsys):
    proj, db = shop
    args = ["roundtrip", str(proj), "--db", str(db), "--out-dir", str(tmp_path / "ref")]
    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["failed"] == []
    views = (proj / "specs" / "views.sql").read_text()
    (proj / "specs" / "views.sql").write_text(views.replace("p.total / 100.0", "p.total / 10.0"))
    assert cli.main([*args, "--force"]) == 1
    assert "orders" in json.loads(capsys.readouterr().out.strip().splitlines()[-1])["failed"]


def test_queries_run_on_indexed_copies(tmp_path):
    from refdata.compare import open_indexed
    src = _db(tmp_path / "a", [("a", 1)])
    con = open_indexed(src, {"t": ["k"]})
    idx = con.execute("SELECT sql FROM sqlite_master WHERE type = 'index'").fetchall()
    assert idx == [('CREATE INDEX "refdata_t" ON "t" ("k")',)]
    con.execute("INSERT INTO t VALUES ('b', 2)")                  # a copy, not the file
    assert sqlite3.connect(src).execute("SELECT count(*) FROM t").fetchone() == (1,)


def test_extra_rebuilt_column_fails(tmp_path):
    src = _db(tmp_path / "a", [("a", 1)])
    con = sqlite3.connect(tmp_path / "b")
    con.execute("CREATE TABLE t (k TEXT, x, extra)")
    con.execute("INSERT INTO t VALUES ('a', 1, 'boo')")
    con.commit()
    con.close()
    assert not compare(src, tmp_path / "b", _project(tmp_path)).ok


def test_big_ints_stay_exact(tmp_path):
    r = compare(_db(tmp_path / "a", [("a", 2**53 + 1)]), _db(tmp_path / "b", [("a", 2**53)]),
                _project(tmp_path))
    assert not r.ok
