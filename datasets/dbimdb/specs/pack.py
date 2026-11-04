"""dbimdb: Db-IMDB, a scrape of IMDb title and name pages weighted to Hindi cinema.
Movies are released with a cast, producers and one director; ratings are read at the scrape.
Stage 1, schema only: the events are ingested from the Spider2 tables
(docs/research/spider2/dbimdb.md); stage 2 adds the behavior.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, cat, f64, i32, i64, opt, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    for name, key in (("genres", "genre_id"), ("languages", "language_id"),
                      ("countries", "country_id"), ("locations", "location_id")):
        p.entity(name, key=key, doc="Created at its first movie's release (a rule)",
                 cols={"ext_id": text(doc="The source id (GID, LAID, CID, LID)"),
                       "name": text(doc="Verbatim; genre names keep their 12 trailing spaces")})
    p.entity("persons", key="person_id", doc="Created at their first credit's release (a rule)",
             cols={"ext_id": text(doc="The PID, without the scraper's leading space"),
                   "name": text(doc="Without the scraper's leading space"),
                   "gender": opt(cat("Male", "Female"))})
    p.entity("movies", key="movie_id", doc="Created at Jan 1 of its year (a rule)",
             cols={"ext_id": text(doc="The MID"),
                   "src_index": i64(doc="Movie.index: scrape order, not a function of anything"),
                   "title": text(),
                   "disambig": opt(text(doc="IMDb's roman-numeral year prefix, I…XVII")),
                   "genre_id": ref("genres"), "language_id": ref("languages"),
                   "country_id": opt(ref("countries")), "location_id": opt(ref("locations")),
                   "director_id": ref("persons")})
    p.event("cast_credited", doc="At its movie's release (a rule), in billing order",
            cols={"movie_id": ref("movies"), "person_id": opt(ref("persons")),
                  "billing": i32(min=1)})
    p.event("producer_credited", doc="At its movie's release (a rule), in credit order",
            cols={"movie_id": ref("movies"), "person_id": opt(ref("persons")),
                  "position": i32(min=1)})
    p.event("movies_snapshot", doc="IMDb's rating and vote count on the scrape day, at N",
            cols={"movie_id": ref("movies"), "rating": f64(), "num_votes": i64(min=0)})
