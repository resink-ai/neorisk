# Authoring a datagen project (for agents)

You are turning a business brief into a simulation spec. Edit only `specs/` (and
`datagen.toml` profiles). Never write to `out/`, `reports/` or `logs/`; `datagen` fills them.

## Loop

1. Write or update `specs/brief.md` with the human. Every number you will calibrate against
   goes in its "Rates we know" table with a source.
2. Write `specs/expectations.yaml`: one entry per brief rate, each with `source:`. Laws are
   listed by id and declared in `pack.py`.
3. Write `specs/pack.py` (tables, events, partitions, boundaries, processes, checks) and,
   only where a state machine can't express the behavior, `specs/kernels.py`.
4. `datagen validate <project>`, then fix every structural error it reports.
5. `datagen run <project> --profile sample` and `datagen check <project> --profile sample`.
   Read `reports/sample-s<seed>/report.html`; fix the spec, not the expectations, unless the
   brief was wrong (then change both and say so in the PR).
6. Open a PR. Changes to `expectations.yaml` need a second reviewer.

## Rules that `validate` enforces

- Each piece of mutable state has exactly one partition: an owner or a shard.
- Partitions talk only through `p.request(...)` with a latency whose minimum is > 0.
- A decision needing two partitions' state uses a hold (owner) plus a request (shard).
  Several shards: `std.reservations` with a TTL.
- Owner-to-owner messages (`std.send_owner`, `on_message`) arrive next step or later.
  If two actors must coordinate tighter, put them under one owner (`execution_owner`).
- Kernels: validate → `out.reserve(...)` for every resource → commit. `reject` and `RETRY`
  only before the first write. Checked arithmetic on amounts. One `site` per random draw.
- Unbounded fan-out declares a fixed `substep` and continues with `out.continue_at`.
- Spawns declare counts; depth ≤ `max_spawn_depth`.

## Overlays

- `apply(o, <params with defaults>)`; every parameter can be set with `--set name.param=...`.
- Add actors with `o.cohort(size=… | share=… | rate=…)`; use `existing=True` to pick from the
  base population instead of creating new IDs.
- Members act only through actions the base pack exposes with `p.expose(...)`. Overlays
  never add event columns, so the schema doesn't change.
- Ground truth goes to hidden `labels/` with `o.label(...)`: role, outcome, `available_at`.
- If the overlay touches shared state (a capped pool, inventory, a book), expect interference
  and keep the `stat.interference` expectation.

## Style

Match the existing projects: typed `Config` dataclasses, comments that say *why*, events with
a `doc=` where the name isn't obvious, cents/base units for amounts, UTC microseconds for time.
