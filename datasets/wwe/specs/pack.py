"""WWE: a web scrape of profightdb.com. Each card is one show of one promotion on one date, and
holds its matches in card order. Stage 1, schema only: the events are ingested from the Spider2
tables (docs/research/spider2/wwe.md); stage 2 adds the behavior.

The scraper ran 7 times and appended every known card's matches again on each run, so Matches is
7 copies (1..7 per card) of 77,567 distinct matches. A match is one `match_held` event; the copies
come back from the 7 `scrape_run` events and each card's first run, in `build.sql`. The HTML page
snapshots ride on `card_page_scraped`, at scrape time, never on the show's date.

Ids are the scraper's counters, carried verbatim as `ext_id`. A Wrestlers row is a match side
(members sorted and ' & '-joined), not a person. `''` means unknown or none, never NULL.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, cat, i32, i64, opt, ref, text

SCHEMA_VERSION = 1

WIN_TYPES = ("def. (pin)", "def.", "def. (sub)", "def. (DQ)", "draw (NC)", "def. (CO)",
             "draw (DCO)", "draw (time)", "draw (DDQ)", "draw", "def. (TKO)", "def. (KO)", "vs.",
             "def. (forfeit)", "draw (curfew)", "(pin)", "draw (DPin)", "draw (DTKO)", "",
             "def.draw (time)", "(sub)", "(DQ)", "draw (points)", "def.draw (NC)",
             "def.draw (DCO)")


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("promotions", key="promotion_id", cols={"ext_id": text(), "name": text()})
    p.entity("locations", key="location_id", doc="'City, State'",
             cols={"ext_id": text(), "name": text()})
    p.entity("shows", key="show_id", doc="Spider2 table Events: a show name",
             cols={"ext_id": text(), "name": text()})
    p.entity("sides", key="side_id",
             doc="Spider2 Wrestlers: one match side, members sorted, ' & '-joined",
             cols={"ext_id": text(), "name": text()})
    p.entity("belts", key="belt_id", cols={"ext_id": text(), "name": text(doc="'' = no title")})
    p.entity("match_types", key="match_type_id",
             cols={"ext_id": text(), "name": text(doc="'' = plain")})
    p.entity("listing_pages", key="page_id", doc="Spider2 Tables: a run-1 listing page snapshot",
             cols={"ext_id": text(), "html": text(doc="Verbatim HTML"), "url": text()})
    p.event("card_held", doc="One show on its date",
            cols={"promotion_id": ref("promotions"), "card_id": i64(doc="Cards.id, verbatim"),
                  "location_id": ref("locations"), "show_id": ref("shows")})
    p.event("match_held", doc="One distinct match, at its card's date, in card order",
            cols={"promotion_id": ref("promotions"), "card_id": i64(),
                  "position": i32(doc="1-based place on the card"),
                  "winner_id": ref("sides"), "loser_id": ref("sides"), "win_type": cat(*WIN_TYPES),
                  "match_type_id": ref("match_types"),
                  "duration_s": opt(i64(doc="Seconds; NULL where the source has ''")),
                  "title_id": ref("belts"), "title_change": i64(doc="0 or 1")})
    p.event("scrape_run", doc="One scraper pass; its time is a rule (the latest card date known)",
            cols={"scraper": text(doc="Sentinel owner 'all'"), "run": i32(doc="1..7")})
    p.event("card_page_scraped", doc="The card's page, fetched on its first run",
            cols={"promotion_id": ref("promotions"), "card_id": i64(),
                  "run": i32(doc="The card's first run"), "table_id": ref("listing_pages"),
                  "url": text(), "info_html": text(doc="Verbatim HTML"),
                  "match_html": text(doc="Verbatim HTML")})
