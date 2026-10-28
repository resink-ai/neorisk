"""Device profiles in one shape, whatever the source: a table with `device` (the identity),
`seen_at`, `group` (consistent / spoofer / synthetic ...) and one column per profile field.

A field is either a scalar string (`cat`) or a list of strings (`set`: fonts, plugins,
languages, user-agent words). Numbers are kept as strings: equal values matter more than
their size, and the encoder buckets them by value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import polars as pl


@dataclass(frozen=True)
class Field:
    name: str
    kind: str          # "cat" or "set"


@dataclass(frozen=True)
class Profiles:
    table: pl.DataFrame          # device, seen_at, group, <fields...>
    fields: tuple[Field, ...]

    def __len__(self) -> int:
        return self.table.height

    def filter(self, mask: pl.Expr | pl.Series) -> Profiles:
        return Profiles(self.table.filter(mask), self.fields)

    def write(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self.table.write_parquet(folder / "profiles.parquet")
        pl.DataFrame({"name": [f.name for f in self.fields],
                      "kind": [f.kind for f in self.fields]}).write_parquet(
            folder / "fields.parquet")

    @classmethod
    def read(cls, folder: Path) -> Profiles:
        f = pl.read_parquet(folder / "fields.parquet")
        return cls(pl.read_parquet(folder / "profiles.parquet"),
                   tuple(Field(n, k) for n, k in zip(f["name"], f["kind"], strict=True)))


# FP-Stalker -----------------------------------------------------------------------------------

_PLUGIN = re.compile(r"Plugin \d+: ([^;]*);")
_UA_WORD = re.compile(r"[A-Za-z][A-Za-z0-9._-]*(?:/[0-9][0-9.]*)?")
FLASH_STATES = ("Flash not detected", "Flash detected but not activated (click-to-play)")

# raw column -> profile field. Dropped: dates and counters, constant columns (hostHttp,
# connectionHttp, IEDataJS, octaneScore, sunspiderTime, browserVersion) and the hashes of lists
# kept in full (plugins, fonts).
FPSTALKER_CAT = {
    "addressHttp": "ip_hash", "acceptHttp": "accept", "encodingHttp": "encoding",
    "languageHttp": "accept_language", "orderHttp": "header_order", "platformJS": "platform",
    "cookiesJS": "cookies", "dntJS": "dnt", "timezoneJS": "timezone", "resolutionJS": "screen",
    "localJS": "local_storage", "sessionJS": "session_storage", "resolutionFlash": "screen_flash",
    "languageFlash": "language_flash", "platformFlash": "platform_flash", "adBlock": "adblock",
    "vendorWebGLJS": "webgl_vendor", "rendererWebGLJS": "webgl_renderer",
    "canvasJSHashed": "canvas_hash", "webGLJsHashed": "webgl_hash", "osDetailed": "os",
    "browserDetailed": "browser", "userAgentHttp": "user_agent",
}
FPSTALKER_SET = ("plugins", "fonts", "ua_words", "languages")


def ua_words(ua: str | None) -> list[str]:
    """Product tokens and words of a user-agent: 'Firefox/41.0', 'Windows', 'NT', ..."""
    return _UA_WORD.findall(ua or "")


def plugins(s: str | None) -> list[str]:
    return [p.strip() for p in _PLUGIN.findall(s or "") if p.strip()]


def fonts(s: str | None) -> list[str]:
    if not s or s in FLASH_STATES:
        return []
    return [f for f in s.split("_") if f]


def languages(s: str | None) -> list[str]:
    return [p.split(";")[0].strip().lower() for p in (s or "").split(",") if p.strip()]


def from_fpstalker(raw: pl.DataFrame, consistent: set[str]) -> Profiles:
    """FP-Stalker rows -> Profiles. `group` is "consistent" for the browser instances the
    authors found free of countermeasures, "spoofer" for the rest (user-agent switchers and
    similar), the paper's own split."""
    fonts_col = pl.col("fontsFlash")
    t = raw.select(
        pl.col("counter"),
        pl.col("id").alias("device"),
        pl.col("creationDate").alias("seen_at"),
        pl.when(pl.col("id").is_in(list(consistent))).then(pl.lit("consistent"))
        .otherwise(pl.lit("spoofer")).alias("group"),
        *(pl.col(src).fill_null("").alias(dst) for src, dst in FPSTALKER_CAT.items()),
        pl.col("pluginsJS").map_elements(plugins, return_dtype=pl.List(pl.String))
        .alias("plugins"),
        fonts_col.map_elements(fonts, return_dtype=pl.List(pl.String)).alias("fonts"),
        pl.col("userAgentHttp").map_elements(ua_words, return_dtype=pl.List(pl.String))
        .alias("ua_words"),
        pl.col("languageHttp").map_elements(languages, return_dtype=pl.List(pl.String))
        .alias("languages"),
        # fonts state is a field of its own: "not detected" vs "click-to-play" vs a list
        pl.when(fonts_col.is_in(list(FLASH_STATES))).then(fonts_col)
        .otherwise(pl.lit("listed")).fill_null("").alias("flash_state"),
    ).sort("seen_at", "counter").drop("counter")
    fields = tuple(Field(n, "cat") for n in [*FPSTALKER_CAT.values(), "flash_state"]) + tuple(
        Field(n, "set") for n in FPSTALKER_SET)
    return Profiles(t, fields)
