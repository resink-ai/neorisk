"""imdb_movies: the "RSVP Movies" IMDb case study, movies published 2017–2019.
Movies are published, tagged with genres and credited with directors and top-billed actors;
IMDb's ratings, gross and known-for lists are read at the scrape.
Stage 1, schema only: the events are ingested from the Spider2 tables
(docs/research/spider2/imdbmovies.md); stage 2 adds the behavior.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, cat, f64, i32, i64, opt, ref, text

SCHEMA_VERSION = 1

GENRES = ("Action", "Adventure", "Comedy", "Crime", "Drama", "Family", "Fantasy", "Horror",
          "Mystery", "Others", "Romance", "Sci-Fi", "Thriller")


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("erd", key="erd_id", doc="The case study's ERD spreadsheet; at the catalog start",
             cols={"ext_id": text(doc="'<table>.<column>'"), "table": text(), "column": text(),
                   "u6": opt(text(doc="Cell 'Unnamed: 6', verbatim")),
                   "u9": opt(text(doc="Cell 'Unnamed: 9', verbatim")),
                   "u12": opt(text(doc="Cell 'Unnamed: 12', verbatim"))})
    p.entity("names", key="name_id",
             doc="Created at their first credited publication; uncredited at 2017-01-01 (rules)",
             cols={"ext_id": text(doc="The nm… id"), "name": text(),
                   "height": opt(i32(doc="Centimetres; REAL in the source, always whole")),
                   "date_of_birth": opt(text(doc="Verbatim: YYYY-MM-DD, YYYY or 'October 29'"))})
    p.entity("movies", key="movie_id", doc="Created at date_published (natural)",
             cols={"ext_id": text(doc="The tt… id"), "title": text(), "duration": i32(min=1),
                   "country": opt(text(doc="', '-joined list, verbatim")),
                   "languages": opt(text(doc="', '-joined list, verbatim")),
                   "production_company": opt(text())})
    p.event("movie_genre_tagged", doc="At its movie's publication (a rule)",
            cols={"movie_id": ref("movies"), "genre": cat(*GENRES)})
    p.event("director_credited", doc="At its movie's publication (a rule)",
            cols={"movie_id": ref("movies"), "person_id": ref("names")})
    p.event("cast_credited", doc="At its movie's publication (a rule)",
            cols={"movie_id": ref("movies"), "person_id": ref("names"),
                  "category": cat("actor", "actress")})
    p.event("movie_rated", doc="IMDb's rating on the scrape day, at N",
            cols={"movie_id": ref("movies"), "avg_rating": f64(), "total_votes": i64(min=0),
                  "median_rating": f64()})
    p.event("movies_snapshot", doc="Lifetime worldwide gross at N, where known",
            cols={"movie_id": ref("movies"), "worldwide_gross_usd": i64(min=0)})
    p.event("names_snapshot", doc="IMDb's known-for list at N, where present",
            cols={"name_id": ref("names"),
                  "known_for_movies": text(doc="Comma-joined tt… ids, verbatim; not refs")})
