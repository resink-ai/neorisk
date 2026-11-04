"""Staff hours: staff members clock in and out. Stage 1, schema only: the events are ingested
from the Spider2 table (docs/research/spider2/edu_misc.md).

The source is generated: its rows cycle through the letters and alternate Enter and Exit in
rowid order, at random dates, so Enters and Exits do not pair in time. Each row keeps its
source rowid. One date, 2013-02-29, does not exist: it is placed at 2013-03-01 by rule and
its text travels verbatim.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, cat, i64, opt, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("staff", key="staff_id", doc="Created at its first clock event (a rule)",
             cols={"ext_id": text(doc="StaffMember, a letter A..Z")})
    p.event("staff_clocked", doc="One clock event at its own date and minute",
            cols={"staff_id": ref("staff"), "direction": cat("Enter", "Exit", doc="EventType"),
                  "date_text": opt(text(doc="The source date when it is not a real date "
                                            "(2013-02-29); else NULL")),
                  "src_rowid": i64(doc="Source rowid: the generator's row order")})
