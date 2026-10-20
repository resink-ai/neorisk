# Authoring guide for agents

You turn a short business brief into a **pack** (or an **overlay** on an existing pack) plus its **expectations**. The engine turns the pack into checked event data. You edit only `specs/`. You never edit the engine (`libs/simkit`). If you think you need an engine change, stop and say why.

## Workflow

1. **Brief.** Write `specs/brief.md`: the business, who acts, the abuse to model, and a numbered "Rates we know" table.
2. **Draft.** Write `specs/expectations.yaml`, citing brief rows. Then write `specs/pack.py`, or `specs/overlays/<name>.py`.
3. **Validate.** Run `uv run datagen validate examples/<project> [--overlay <name>]` until it reports `"problems": 0`.
4. **Run a sample.** Run `uv run datagen run examples/<project> --profile sample [--overlay <name>] --force`.
5. **Check.** Run `uv run datagen check examples/<project>/out/<run>`, then read `reports/<run>/report.html`.
   - The command exits 1 if a required check fails, errors, is inconclusive, or is unanchored (the specs changed after the run).
   - Add `--seeds 2` for 95% intervals across held-out seeds.
   - Add `--skip-stats` to check laws only (expectations are calibrated for one profile).
6. **Open a PR.** A second reviewer approves changes to `expectations.yaml` and to laws.

## A project folder

```text
examples/<project>/
  datagen.toml          # [run] seed/days, [config] Config fields, [profiles.<p>.run|config], [overlays.<name>]
  specs/brief.md  specs/expectations.yaml  specs/pack.py  specs/overlays/<name>.py
  out/  reports/        # written by datagen; git-ignored
```

`--set users=500`, `--set run.days=10` and `--set <overlay>.<param>=v` override the profile. A run folder is `out/<profile>-s<seed>[+overlay]`. Runs are deterministic, so `run` refuses to overwrite an existing folder without `--force`.

## The pack module

```python
from dataclasses import dataclass, field
from neorisk_simkit.engine import DAY, HOUR, MINUTE        # seconds
from neorisk_simkit.spec import Pack, Latency, i32, i64, f64, text, boolean, ts, cat, ref, amount, opt
from neorisk_simkit.checks import laws
from neorisk_simkit.std import holds, reservations         # recipes; std.pool.CappedPool too

NAME = "my_pack"          # optional; defaults to the folder name
SCHEMA_VERSION = 1        # bump on any column change (`datagen schema --diff` enforces it)

@dataclass
class Config:             # every tunable, with defaults; datagen.toml and --set override them
    users: int = 1000

@dataclass
class User:               # one partition's mutable state; only its own actions touch it
    uid: int = 0

def define(p: Pack) -> None:
    p.entity("users", key="user_id", cols={"tier": cat("a", "b")})     # ids are assigned for you
    p.event("thing_happened", cols={"user_id": ref("users"), "amount": amount()})
    user = p.owner("user", state=User, latency=Latency(0.05, 0.3))     # δ = 0.05 s > 0
    life = user.process("life", start="arrive")                        # start runs at creation

    @life.action
    def arrive(ctx, s, cmd):
        ctx.emit("thing_happened", user_id=s.uid, amount=100)
        ctx.after(ctx.rng.exponential(DAY), "arrive")

    @p.source
    def population(src):                                               # runs once, before the loop
        for _ in range(src.cfg.users):
            t = src.rng.uniform(0, src.days) * DAY
            uid = src.insert("users", at=t, tier="a")
            src.create("user", at=t, uid=uid)
```

### Primitives

- **Table.** Entity tables (`p.entity`) and event tables (`p.event`). Every event table automatically starts with the common columns `event_id, event_type, event_time, seq, partition_id, cause_id, action_id`. Never declare those yourself.
- **Process.** Behavior inside one partition kind. An **owner** (`p.owner`) is a user, a payment or a campaign. A **shard** (`p.shard`) is a pool, an order book, a chain or an inventory group. `kind.process(name, start=...)` groups actions, and `kind.action` uses a default process named after the kind.
- **Action.** A function `(ctx, s, cmd)` where `s` is this partition's state and `cmd` is the command (`cmd.<field>` reads its payload).
- **Source.** `@p.source def f(src)` seeds populations, shards, exogenous timelines and graphs.
- **Check.** `p.check(name, law, group="law" | "cross", required=True)`.

### Column types

| Type | Meaning |
|------|---------|
| `i32` / `i64` | Integers |
| `f64` | Floats |
| `text` | Strings |
| `boolean` | Booleans |
| `ts` | Seconds since the run start; exported as UTC µs |
| `cat("a", "b")` | Categories; emit the string |
| `ref("table")` | An entity id |
| `amount("USD")` | Integer minor units |
| `opt(x)` | Nullable |

`i32`/`i64` take `min=`, and every type takes `doc=`.

### The action context `ctx`

| Call | What it does |
|------|--------------|
| `ctx.now`, `ctx.self_id`, `ctx.cfg`, `ctx.rng`, `ctx.shared.<name>.<array>` | Time, this partition, config, this partition+process's own random stream, read-only shared inputs |
| `ctx.emit(event, **cols) -> event_id` | A row; every declared column must be given (`None` only for `opt`) |
| `ctx.after(delay, action, **payload)`, `ctx.at(t, ...)` | A timer to this partition |
| `ctx.send(pid, action, **payload)` | A message to another partition, delivered after the target kind's latency |
| `ctx.request(pid, action, reply=..., timeout=..., **payload)` | Ask a shard; the reply runs `reply` here with `cmd.status` ok / rejected / timeout, `cmd.ok`, `cmd.reason`, `cmd.req`, `cmd.sender`, and the shard's reply payload |
| `ctx.reply(**payload)` | In a shard action: answer ok |
| `ctx.decline(reason, **payload)` | In a shard action: keep the rows you emitted, answer "rejected" |
| `ctx.reject(reason)` | Refuse with no effect. **Only before the first write** (emit, schedule, create, insert, label); after one, the run fails |
| `ctx.create(kind, key=None, cohort=None, **state_fields) -> pid` | A new partition (a payment, a cascade); depth ≤ `max_spawn_depth` |
| `ctx.insert(table, **cols) -> id`, `ctx.new_id(space)` | An entity row; a sequential id without a table |
| `ctx.find(kind, key) -> pid` | A partition a source created with `key=` |
| `ctx.call(action, **payload)` | Run another action of this partition inline, in the same atomic step |
| `ctx.label(target_id, role, table=, outcome=None, campaign_id=None, available_at=t)` | A hidden label on a row of entity `table`; the last label for a (table, id) is final; `available_at` models label delay |
| `ctx.retire()` | End this partition; later timers and messages to it are dropped and counted |
| `ctx.local` | A dict of private state for the running process (handy in overlays) |

`src` (sources) has `cfg`, `rng`, `days`, `horizon`, `create(kind, at=, key=, cohort=, **state)`, `insert(table, at=, **cols)` and `share(name, **numpy_arrays)`.

### Rules that keep data correct and reproducible

- **Validate, then commit.** Check everything first. Return `ctx.reject(...)` before writing anything; never mutate state and then reject. `--debug` snapshots state around rejections and checks every emit.
- **One owner per piece of state.** Partitions interact only through messages, requests and replies, never through shared mutable objects. Payloads are copied.
  - Joint constraints use `std.holds`: hold your side, ask, then commit or release.
  - Multi-shard decisions use `std.reservations`: reserve in each shard, join the replies, then commit all or release all. A TTL frees units if nobody commits.
- **Every boundary has δ > 0.** Pick a realistic platform latency for each kind.
- **Randomness comes only from `ctx.rng` / `src.rng`.** These are keyed per partition and process, so adding an overlay doesn't shift anyone else's draws. Never use `random`, `np.random.*` module state, or wall-clock time.
- **No mutable module globals.** `validate` flags lists, dicts and sets at module level. Use tuples or `types.MappingProxyType`.
- **Payload keys** must not shadow command fields: `action t payload status reason sender req ok`.
- **Fan-out is a loop.** One action may emit many rows: an order sweeping a book, a post reaching followers.
- **Same-time order:** creations, messages and replies run before timers. Give an action `priority=0` (`CONTINUATION`) to run first at a shared instant, for example "expiry wins a tie".

### State machines (no code) — `neorisk_simkit.machine`

```python
from neorisk_simkit.machine import Request, Spawn, Then, cond, notify_parent
from neorisk_simkit.spec import dist          # dist.exp(mean_days=2), lognormal(median_s=), gamma(mean_days=), uniform("1h", "5h"), "7d"
m = kind.machine("dunning", initial="due")
m.state("due", request={"paid": Request(("processor", "main"), "charge", timeout="30s",
                                        on_reject="retrying", payload=lambda ctx, s: {"amount": s.amount})})
m.state("retrying", repeat=(dist.const("3d"), 1.0, "retry_charge"), max_repeats=3,
        until=cond.flag("paid"), then="cancelled")
m.state("paid", on_enter="record_payment")
m.state("cancelled", retire=True)
```

Operations, all evaluated on entering a state:

| Operation | Behavior |
|-----------|----------|
| `branch={target: (p, delay, action)}` | Probabilities must sum to 1; use `"otherwise"` for the unpicked mass (its p may be `None`: the remainder) |
| `timer={target: delay \| (delay, action)}` | Leaving the state cancels it |
| `repeat=(delay, p, action)` | With `max_repeats`, `until=cond...` and `then` |
| `spawn=Spawn(kind, n)` | Create children |
| `join={target: (msg, "all_spawned" \| n)}` | Wait for children; needs `join_timeout=(delay, target)` and `late=` |
| `request={target: Request(...)}` | Ask a shard; `timeout` and `on_reject` are mandatory |
| `on_enter`, `on_reject`, `retire` | Run an action on entry; where to go on a rejection; end the partition |
| `Then(a, b, fallback=c)` | Run `a`, then `b`; if `b` rejects, `a` stays committed and `c` runs |

Children call `notify_parent(ctx, msg)`. Probabilities and delays may be `"cfg.<field>"` to read the run config (a number of days for delays), so rates stay tunable from `datagen.toml`.

## Overlays — `specs/overlays/<name>.py`

An overlay adds a configurable group of actors with distinct behavior, and never edits the pack. Overlays emit the same event schema and cannot add tables or columns.

```python
from neorisk_simkit.spec.overlay import Overlay

def apply(o: Overlay, share: float = 0.01, label_delay_days: float = 30.0) -> None:
    o.cohort("ring", kind="user", share=share, arrive_share=0.8,      # size= | share= | rate=
             suppress=["shopper"],                                     # base processes they skip
             redirect={"bonus_credited": "cash_out"})                  # base command -> overlay action
    p = o.process("user", "ring_life", cohort="ring", start="begin")  # or o.machine(...)

    @p.action
    def begin(ctx, s, cmd):
        ctx.call("signup")                                             # a base extension point
        ctx.label(s.uid, "ring", table="users", available_at=ctx.now + label_delay_days * DAY)
```

Cohort members get ids from the overlay's own namespace (≥ 10⁹), so base ids never shift.

The **regression rule** (`datagen check`) compares base rows with and without the overlay:
- If the overlay never reaches a base partition, every base row must be identical.
- If it does reach one (a shared pool, shared inventory):
  - base rows before the first contact must be identical, and so must events marked with `p.mark_exogenous(...)`;
  - the laws must still hold;
  - the report shows the interference.

## Laws — `neorisk_simkit.checks.laws`

| Law | What it checks |
|-----|----------------|
| `lifecycle(key, {None: {first events}, "a": {"b", "c"}})` | Event order per key |
| `sum_le((event, col), (cap_event, col), by)` | A running sum stays under a running cap (refunds ≤ captured) |
| `running_nonneg(by, plus=[(event, col[, filter])], minus=[...])` | A running balance never goes negative |
| `holds_resolved()` | Every hold is committed or released |
| `reservations_resolved()` | Every reservation is resolved by its TTL |
| `pool_within_cap(event, col, "cfg.field", period_days=30)` | Grants stay within a cap per period |
| `unique(event, cols)` | No duplicate rows on these columns |
| `consecutive(event, by, col)` | Values per key count up by one (nonces) |
| `pairing((req, key), (res, key))` | Requests and responses pair up |
| `not_while_open(forbidden, opened, [closed], key)` | No `forbidden` event while a window is open |

A custom law is a function `d -> (n_checked, offending_rows)`. Here `d.ev(name)` is an event frame, and `d.entities`, `d.labels` and `d.cases` are also available. Return rows with `partition_id`, `seq` and `action_id`, so failures cite them.

## Expectations — `specs/expectations.yaml`

```yaml
pack: my_pack
defaults: {min_sample: 200}
expectations:
  - {id: exp.x, metric: 'stat.share("a", of=["a", "b"])', target: {between: [0.1, 0.2]},
     source: "brief: Rates we know, row 1", required: true}
overlays:
  my_overlay: [ ... ]
```

The metrics are:
- `stat.funnel(start, step, unit=, within=)`
- `share(event, of=[...], where={})`
- `quantiles(event, per=)` (targets per `p50`/`p90`)
- `top_share(event, by=, top=)`
- `rate(event)`
- `mean(event, column)`
- `count(event)`
- `cohort_size(role)`

Targets are `between`, `lt`, `gt`, `around` with `tolerance`, or `reported: true`.

## Other commands

```bash
uv run datagen schema examples/<p> --format sql --dialect duckdb|postgres|bigquery|snowflake|clickhouse|spark [--with-fks] [--load RUN]
uv run datagen schema examples/<p> --format avro|json-schema|arrow|markdown --out schemas/
uv run datagen schema --diff OLD NEW            # exits 1 on a column change without a SCHEMA_VERSION bump
uv run datagen replay RUN --first 100 [--with-labels] [--sink file:x.jsonl] [--pace x60] [--where "amount>10000"]
uv run datagen export RUN --single-file all.parquet
```

## Worked projects

| Project | Shows |
|---------|-------|
| `ecommerce` | Owners and shards, reservations with a TTL, a capped pool; overlays `bounty_hunters` (shares state) and `window_shoppers` (shares nothing) |
| `payments` | Holds, refunds, disputes as a child process, idempotency keys, settlement shards, label delay |
| `crypto_exchange` | An order-book shard with price-time matching and IOC/FOK |
| `layer1` | A chain shard with a nonce and fee envelope, and reverts |
| `social` | A shared follow graph; cascades owned by their root post |
| `payments_subscriptions` | A payments variant built as state machines, with a `card_testing` overlay on `payments` |
