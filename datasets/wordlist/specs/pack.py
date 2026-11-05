"""English word list: one entity per row of the base list, a static reference input with no
time. Stage 1, schema only: the events are ingested from the Spider2 table
(docs/research/spider2/modern_misc.md).

The key is the 1-based position in the base list, not the word: 2 rows are NULL (the words
`nan` and `null`, eaten by a pandas import), and they stay NULL. Spider2 prepended 3,701
copies of existing rows; they come back from `source_row_duplicated`, never by dropping them:
local201's accepted `_b` answer depends on them. Stage 2 must not learn from that event type.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, cat, opt, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("words", key="word_key", doc="One row of the base list; created at rule time T0",
             cols={"ext_id": text(doc="Position in the base list, zero-padded to 6 digits"),
                   "word": opt(text(doc="Verbatim; NULL twice, upper case for TRUE and FALSE"))})
    p.event("source_row_duplicated",
            doc="Spider2 artefact: one extra identical row of the source table (time T0)",
            cols={"word_id": ref("words"), "src_table": cat("word_list")})
