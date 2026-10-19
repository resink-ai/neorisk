# Authoring a datagen project (for agents)

You are turning a business brief into a simulation spec. Edit only `specs/` (and
`datagen.toml` profiles). Never write to `out/`, `reports/` or `logs/`; `datagen` fills them.
[`ecommerce/`](ecommerce/) is the worked example of everything below.

## Loop

1. Write or update `specs/brief.md` with the human. Every number you will calibrate against
   goes in its "Rates we know" table with a source.
2. Write `specs/expectations.yaml`: one entry per brief rate, each with `source:`. Laws are
   listed by id and declared in `pack.py`. Quote a `metric:` that contains `": "` (a `where=`
   dict), or YAML reads it as a mapping.
3. Write `specs/pack.py` (tables, events, partitions, boundaries, processes, machines,
   checks). Use a state machine (`p.machine`) for lifecycles. Write a handwritten kernel in
   `specs/kernels.py` only where a machine can't express the behavior: shards, carts, joins
   across partitions.
4. `datagen validate <project>`, then fix every structural error it reports. Use
   `datagen validate <project> --dump-machines DIR` to read the generated machine code that
   is compiled.
5. `datagen run <project> --profile sample` and `datagen check <project> --profile sample`.
   Read `reports/sample-s<seed>/report.html`; fix the spec, not the expectations, unless the
   brief was wrong (then change both and say so in the PR). `datagen check` lands later in
   M3. Until then, read the laws in the run's `manifest.json`.
6. Open a PR. Changes to `expectations.yaml` need a second reviewer.

A cold compile of a pack-sized module takes tens of minutes. Write a kernels file completely
before its first run. A `--set` of a config field or overlay parameter never recompiles.

## Rules that `validate` enforces

- Each piece of mutable state has exactly one partition: an owner or a shard.
- Partitions talk only through declared boundaries, `p.request(...)` or `p.message(...)`, with
  a latency whose minimum is > 0.
- A decision needing two partitions' state uses a hold (owner) plus a request (shard).
  Several shards: one request per shard plus commit or release messages, with a TTL on the
  shard's hold.
- An owner-to-owner message (`p.message(frm=<owner>, to=<owner>)`, sent with
  `out.send_<name>(t, to=<dense id>, ...)`, received through `on_message`) needs a latency
  minimum ≥ `engine.step_max` and a target with a population (D73). It is delivered next step
  or later. A target that has retired, has not arrived or is a member row counts it as
  `late_messages`, so a receiver must stay alive (`retire_when_idle=False` or its own pending
  timer). If two actors must coordinate tighter, put them under one owner (an overlay cohort's
  campaign owner).
- Kernels: validate → `out.reserve(...)` for every resource → commit. `reject` and `RETRY`
  only before the first write. Checked arithmetic on amounts. One `site` per random draw.
- Unbounded fan-out declares a fixed `substep` and continues with `out.continue_at`.
- Spawns and created owners are bounded by `max_spawn_depth` (default `budget.max_spawn_depth`),
  checked at runtime (D72).

## Machines

- `p.machine(name, owner=, initial=, start=p.on_created(...), config=, max_instances=,
  fields=, max_spawn_depth=)`. Every machine of one owner partition compiles into one
  generated process `mx_<partition>`.
- States: `.state(name, branch=, timer=, repeat=, max_repeats=, until=, then=, join=, late=,
  request=, on_reject=, on_timeout=, timeout=, spawn=)`, and `.final(*names)`.
  - `branch={target: (p, delay, action)}`: at most one `p` is `None`, which takes the rest.
    `std.p_by(col, {value: p}, otherwise=)` picks by an owner state category.
  - `request={ok_target: std.request(...)}` needs `timeout=` and `on_reject=`.
    `std.request(local, ok=, shard=, store=, release=, **payload)` must declare `release=`
    (a `std.send(...)` that gives back a grant that arrives late, D67).
  - `join={target: msg}` with `timer=` waits for `std.send_parent(msg)` from spawned children.
    `late="ignore" | "count"` decides what happens to a child that answers late.
  - `until=std.cond.ge|le|eq(a, b)` or `std.cond.repeats_ge(n)` then `then=target`.
- Actions: `@action(state=, max=Res(...), fields={...})` on `def f(ctx, s, m, cmd, out)`.
  Never call `out.reserve` inside (the machine reserves `max`). `return reject(code)` only
  before the first write. `m.id` is the actor, `m.parent_id` the parent and `m.<field>` an
  instance field. Compose with `.then(...)` and `.otherwise(...)`.
- Helper actions: `std.emit`, `std.spawn`, `std.send_parent`, `std.label`, `std.request`,
  `std.send`, `std.create_owner`, `std.set_field` and `std.add_field`.
- Helper values: `std.actor()`, `std.parent()`, `std.col(c)`, `std.field(f)`,
  `std.new_id(ns)`, `std.now()`, `std.after(dist)`, `std.near(v, above)` and
  `std.pick_ref(refs, parent_share=)`.
- Generated code: the method that writes an action part is `_Gen.make_part`. Module-level names
  are per partition (`MX_STALE_<p>`, `MX_FIRE_<p>`, `mx_tag_<p>`).
- Every literal a machine uses is a config parameter, so `--set` never changes generated
  source. Per-machine counters (`entries`, `rejects`, `late`, `late_grants`, `spawned`) are
  in `run_stats.json["machines"]`.

## Overlays

- `specs/overlays/<name>.py` defines `apply(o, <params with defaults>)`. Overlay modules import
  only `from neorisk_simkit.spec import Overlay, dist, std`. An `int|float|str|bool` parameter
  is set with `[profiles.<p>.overlay.<name>]` or `--set <name>.<param>=...`.
- A profile's `overlays = [...]` list enables overlays. `datagen run --overlay NAME` adds one,
  and `--no-overlays` clears the list. `run_to_dataset(overlays=None)` inherits the profile's
  list, and an explicit list (`[]` included) replaces it. The run is named
  `<profile>-s<seed>+<o1>+...`.
- The base pack opens extension points: `p.expose_owner("user")` (an owner partition overlays
  may act for), `p.expose(name=action | chain | std.request(...))` (read by overlays as
  `o.base.<name>`) and `p.expose_param(path, value)` (read by `o.param(path)`).
- `o.cohort(name, table=, size= | share= | rate=, arrivals=, execution_owner=, attrs=, refs=)`
  creates the cohort's campaigns (`size` of them), each its own owner of partition `name`,
  acting for the exposed owner. Its members are
  new rows of the base table, with ids after the population, so base ids never move. `suppress=`
  is recorded but has no runtime effect (D74). Cohorts of existing base owners are deferred
  (D93).
- `o.machine(name, members=cohort | cohort.spawned(machine), initial=, member=, fields=, init=,
  max_instances=)` declares a cohort machine. Its actions are the exposed base actions and
  `std` helpers.
- `o.label(cohort, roles=, outcomes=, available_after=)` declares hidden `labels/` rows, written
  by `std.label(role, outcome)`.
- Overlays add no event tables or columns and no processes, requests or shards (D74, D95).
  `datagen schema --overlay NAME` adds only the cohort's entity and label tables.
- If the overlay touches shared state (a capped pool, inventory, a book), expect interference
  and keep the `stat.interference` expectation.

## Style

Match the existing projects: typed `Config` dataclasses, comments that say *why*, events with
a `doc=` where the name isn't obvious, cents/base units for amounts, UTC microseconds for time.
