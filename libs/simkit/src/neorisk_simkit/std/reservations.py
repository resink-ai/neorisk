"""Reservation hold table for an inventory shard (D49).

A shard keeps a fixed table of holds in its process `Local`; a free slot is
`res_hold[j] == std.NULL`. Hold IDs come from `p.ids("hold")`; a full table rejects the line
with reason `busy`.
"""


def fields(slots: int) -> dict[str, str]:
    """`Local` fields of a hold table with `slots` slots."""
    if slots < 2:
        raise ValueError("reservations need at least 2 slots")
    return {"res_hold": f"ref[{slots}]", "res_item": f"i32[{slots}]",
            "res_qty": f"i32[{slots}]", "res_ckt": f"ref[{slots}]"}
