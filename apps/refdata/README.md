# refdata

Reference datasets: real tables from the [Spider 2.0](https://github.com/xlang-ai/Spider2) text-to-SQL benchmark, turned into simkit event logs and rebuilt exactly. Each one is a project in `examples/` whose `pack.py` declares the events. Stage 1, this app, proves that the event log *is* the tables. Stage 2 will make the same pack generate the log, and grade it with the same views. See `docs/superpowers/specs/2026-10-30-spider2-reference-datasets-design.md`.

```bash
uv run refdata fetch                                   # 30 SQLite files → data/spider2/ (436 MB zip, sha256-pinned)
uv run refdata roundtrip examples/olist [--force]      # ingest → rebuild → compare; exit 1 on any difference
uv run refdata ingest examples/olist [--db SRC] [--out DIR] [--force]          # → data/ref/olist/
uv run refdata rebuild data/ref/olist --project examples/olist [--out FILE]    # → data/ref/olist.rebuilt.sqlite
uv run refdata compare data/spider2/E_commerce.sqlite data/ref/olist.rebuilt.sqlite --project examples/olist
uv run datagen check data/ref/olist --project examples/olist --skip-stats        # structural checks on real data
```

Exit codes are 0 for success, 1 when a round trip or comparison differs, and 2 for a usage error, a missing source or a refusal.

Everything under `data/` is git-ignored. The sources' licences vary (Olist is CC BY-NC-SA 4.0), so only specs, SQL and research are committed.

## A project's files

| File | Holds |
|---|---|
| `specs/pack.py` | The entities and events (stage 1 declares only these) |
| `specs/source.toml` | The source file, and each source table's key (used only to sort diff samples) |
| `specs/ingest.sql` | SQLite SQL, with one `-- event: <name> owner=<col> [ord=<col>]` or `-- entity: <name>` block per pack table |
| `specs/views.sql` | DuckDB SQL, with one `-- table: <name>` block per source table, read over the dataset's Parquet files |
| `specs/queries/<id>.sql` | Spider2 questions, run on the source and on the rebuilt file |

## Dataset conventions

An ingested dataset has simkit's layout, so `neorisk_simkit.io.read`, `datagen check`, `datagen schema --load` and `datagen replay` all work on it.

- **Time:** source wall clock is stored as if it were UTC. Ingest SQL emits ISO text and may call `iso_time(text, strptime_format)`. Views format times back into the source's exact text.
- **Entities:** an entity's key is the 1-based rank of its `ext_id`, the source id held verbatim. `created_at` comes from the block if given, otherwise it is the first event time.
- **Refs:** a `ref(T)` column, in an event or an entity, is given as the source id and mapped through `T.ext_id`. An unmatched id is an error.
- **Order:** events sort by (event_time, `ord`, block position, owner, block row).
  - `seq = event_id` is that position.
  - `partition_id` ranks (owner column, owner value).
  - Every block ends in an ORDER BY.
- **Values:** money that is exact cents becomes `amount()` in minor units. Other floats are `f64`, and text is byte-exact.

## Exactness

A round trip passes when every source table equals the rebuilt one as a **multiset of rows**. INTEGER and REAL compare by value; NULL, `''` and `'\N'` are three different values. No tolerance applies to tables. Saved queries run on in-memory copies of both files, indexed on the `source.toml` keys. They compare as lists when the query has a top-level ORDER BY, otherwise as multisets, and float cells use a relative tolerance of 1e-9.

## The five datasets

Measured on an Apple-silicon laptop on 2026-10-30.

| Project | Source | Tables | Rows | Events | Queries | `roundtrip` |
|---|---|---:|---:|---:|---:|---:|
| `databank` | bank_sales_trading (Data Bank) | 3 | 9,373 | 9,368 | 6 | 1 s |
| `cliquebait` | bank_sales_trading (Clique Bait) | 5 | 34,537 | 32,734 | 1 | 2 s |
| `olist` | E_commerce | 11 | 1,559,764 | 918,549 | 12 | 41 s |
| `delivery_center` | delivery_center | 7 | 1,154,523 | 3,944,085 | 3 | 36 s |
| `airlines` | Airlines | 8 | 2,289,506 | 2,339,321 | 2 | 22 s |

Every table of every project round-trips exactly, and every saved query agrees.

## Laws on real data

Run `datagen check --skip-stats` on each ingested dataset. All seven structural checks pass on all five: types, required, unique ids, references, ordering, leakage, anchored. The packs have no laws yet. Stage 2's laws must also pass on these datasets. The research already knows facts that rule out some tempting laws:
- Olist has 1,359 carrier handoffs before approval.
- delivery_center has negative metrics and moments out of order.
- Data Bank customers overdraw: 56.8% end below zero.

A law that real data breaks is wrong, not the data.

## Times the sources do not have

Stage 1 is exact on table contents. For rows with no source time, the time comes from a rule, and stage 2 must not treat it as data:

| Dataset | Rows | Time given by rule |
|---|---|---|
| Olist | final statuses | the last known stage |
| delivery_center | payments | the order's creation |
| delivery_center | deliveries | the `delivering` moment, else the latest earlier moment |
| delivery_center | closes | the `finished` moment, else the last moment |
| Airlines | flight scheduling and cancellation | 30 days before departure |
| Airlines | tickets | the booking time |
| Airlines | check-ins | 130–90 minutes before departure, in boarding order |

Every invented time is capped at the snapshot time N.
