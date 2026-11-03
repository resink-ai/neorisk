"""Chinook: a digital music store. Customers buy tracks on invoices from a fixed catalog.
Stage 1, schema only: the events are ingested from the Spider2 tables
(docs/research/spider2/chinook.md); stage 2 adds the behavior.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, amount, i64, opt, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("genres", key="genre_id", cols={"ext_id": text(), "name": opt(text())})
    p.entity("media_types", key="media_type_id", cols={"ext_id": text(), "name": opt(text())})
    p.entity("artists", key="artist_id", cols={"ext_id": text(), "name": opt(text())})
    p.entity("albums", key="album_id",
             cols={"ext_id": text(), "title": text(), "artist_id": ref("artists")})
    p.entity("tracks", key="track_id",
             cols={"ext_id": text(), "name": text(), "album_id": opt(ref("albums")),
                   "media_type_id": ref("media_types"), "genre_id": opt(ref("genres")),
                   "composer": opt(text()), "milliseconds": i64(), "bytes": opt(i64()),
                   "unit_price": amount("USD")})
    p.entity("playlists", key="playlist_id", cols={"ext_id": text(), "name": opt(text())})
    p.entity("playlist_track", key="pt_id", doc="Playlist membership; no time, no order",
             cols={"ext_id": text(doc="'<PlaylistId>/<TrackId>'"),
                   "playlist_id": ref("playlists"), "track_id": ref("tracks")})
    p.entity("employees", key="employee_id", doc="Created at their hire date",
             cols={"ext_id": text(), "last_name": text(), "first_name": text(),
                   "title": opt(text()), "reports_to": opt(ref("employees")),
                   "birth_date": opt(text(doc="Verbatim 'YYYY-MM-DD 00:00:00'")),
                   "address": opt(text()), "city": opt(text()), "state": opt(text()),
                   "country": opt(text()), "postal_code": opt(text()), "phone": opt(text()),
                   "fax": opt(text()), "email": opt(text())})
    p.entity("customers", key="customer_id", doc="Created at their first invoice (a rule)",
             cols={"ext_id": text(), "first_name": text(), "last_name": text(),
                   "company": opt(text()), "address": opt(text()), "city": opt(text()),
                   "state": opt(text()), "country": opt(text()), "postal_code": opt(text()),
                   "phone": opt(text()), "fax": opt(text()), "email": text(),
                   "support_rep_id": opt(ref("employees"))})
    p.event("invoice_issued", doc="Billed to the customer's own address; the total is its lines",
            cols={"customer_id": ref("customers"), "invoice_id": i64()})
    p.event("invoice_line_added", doc="At its invoice's time",
            cols={"customer_id": ref("customers"), "invoice_id": i64(),
                  "invoice_line_id": i64(), "track_id": ref("tracks"),
                  "unit_price": amount("USD"), "quantity": i64(min=1)})
