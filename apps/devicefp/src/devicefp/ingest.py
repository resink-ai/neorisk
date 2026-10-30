"""FP-Stalker's MySQL dump (`tableFingerprints.sql`) -> `fingerprints.parquet`.

The dump is read as text and never executed. Large blobs are dropped: `canvasJS` and `webGLJs`
are data-URL images and only their hashes are kept.
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl

_INSERT = re.compile(r"INSERT INTO `extensionDataScheme` \(([^)]*)\) VALUES\s*")
_TOKEN = re.compile(r"'((?:[^'\\]|\\.)*)'|(NULL)|(-?\d+(?:\.\d+)?)|(\))")
_ESCAPES = {"0": "\0", "n": "\n", "r": "\r", "t": "\t", "Z": "\x1a", "b": "\b"}
_ESCAPE = re.compile(r"\\(.)", re.DOTALL)
DROPPED = ("canvasJS", "webGLJs")


def _unescape(s: str) -> str:
    return _ESCAPE.sub(lambda m: _ESCAPES.get(m.group(1), m.group(1)), s)


def parse_dump(text: str) -> pl.DataFrame:
    """Every row of every INSERT statement, all columns as strings (NULL -> None)."""
    rows: list[list[str | None]] = []
    columns: list[str] | None = None
    for m in _INSERT.finditer(text):
        cols = [c.strip(" `") for c in m.group(1).split(",")]
        if columns is None:
            columns = cols
        elif cols != columns:
            raise ValueError("INSERT statements disagree on columns")
        row: list[str | None] = []
        pos = m.end()
        while True:
            # each tuple: "(" values ")" then "," or ";"
            while text[pos] in " \n\r\t,(":
                if text[pos] == "(":
                    row = []
                pos += 1
            t = _TOKEN.match(text, pos)
            if t is None:
                raise ValueError(f"unparsed value at offset {pos}: {text[pos:pos + 40]!r}")
            pos = t.end()
            if t.group(4):                      # end of a tuple
                rows.append(row)
                row = []
                while text[pos] in " \n\r\t":
                    pos += 1
                if text[pos] == ";":
                    break
                continue
            if t.group(1) is not None:
                row.append(_unescape(t.group(1)))
            elif t.group(2):
                row.append(None)
            else:
                row.append(t.group(3))
    if columns is None:
        raise ValueError("no INSERT statements found")
    df = pl.DataFrame(rows, schema=columns, orient="row")
    return df.drop(DROPPED, strict=False)


def ingest(dump: Path, out: Path) -> pl.DataFrame:
    df = parse_dump(dump.read_text(encoding="utf-8", errors="replace"))
    df = df.with_columns(
        pl.col("counter").cast(pl.Int64),
        *(pl.col(c).str.to_datetime("%Y-%m-%d %H:%M:%S", strict=False)
          for c in ("creationDate", "updateDate", "endDate")),
    ).sort("counter")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out)
    return df
