# Label-discovery bench: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:executing-plans or
> superpowers:subagent-driven-development to run this plan task by task. Steps use `- [ ]`
> checkboxes.

**Goal:** `bench discover`: hide the ring labels, run 11 discovery methods from the same seeds at
the same review budget, and score each against the hidden truth.

**Architecture:** a new `bench.discover` package with four parts:
- `world.py` (a leak-free view, plus hidden truth);
- `protocol.py` (seeds, oracle, the round loop);
- `methods/` (one module per family);
- `metrics.py` / `report.py`.

The simulator gets one change: the `variant` label column.

**Tech stack:** Python 3.12, polars, numpy, scikit-learn, xgboost, scipy.sparse (for PageRank).
No new dependency.

**Spec:** `docs/superpowers/specs/2026-10-21-label-discovery-bench-design.md`

**Estimate:** about 9 h of agent time across 5 milestones. If a milestone runs past twice its
estimate, I stop and report.

## Global constraints

- Methods see only the world view. Truth reaches them only through `Oracle.review`, and a test
  enforces that.
- No method hyperparameter is tuned on truth. Defaults are frozen in M3 before the first scored run.
- Everything is seeded: the same command gives the same `discover.json`.
- `stealth_p = 0` profiles stay byte-identical except for the new null `variant` column. The legacy
  export stays byte-identical.
- ROC and PR are always shown together.
- No commit or push without asking.

## Review focus

1. **Leaks from the world view:** ids, time ordering of overlay sign-ups, and device ids minted
   inside the overlay. These are covered by the M1 leak test on every column.
2. **A method proposing an already-reviewed or unknown id:** the oracle must reject it without
   spending budget, and the loop must still finish.
3. **Too few seed candidates when the report date is early:** the run must fail with a clear
   message, not sample fewer seeds silently.
4. **Ties in score** (common for graph methods with no path): rank deterministically by world id.
5. **The `perfect` baseline reading truth:** it is the one sanctioned exception, and it is marked
   in the code and the report.

---

### Task 1: M1 truth and world (1.5 h)

**Files:**
- Modify:
  - `libs/simkit/src/neorisk_simkit/engine/loop.py` (`label(..., variant=None)`);
  - `engine/output.py` (the `variant` column);
  - `examples/ecommerce/specs/overlays/bounty_hunters.py` (pass `variant="stealth"`).
- Create: `apps/bench/src/bench/discover/{__init__,world}.py` and
  `apps/bench/tests/test_discover_world.py`.

**Interfaces:**

```python
@dataclass(frozen=True)
class World:
    users: pl.DataFrame; devices: pl.DataFrame; sessions: pl.DataFrame; views: pl.DataFrame
    orders: pl.DataFrame; returns: pl.DataFrame; bonuses: pl.DataFrame; skus: pl.DataFrame
    addresses: pl.DataFrame
    user_ids: np.ndarray          # world ids, sorted; the index every score array uses

@dataclass(frozen=True)
class Truth:
    bad: np.ndarray               # bool, aligned to World.user_ids
    stealth: np.ndarray           # bool
    cohort: np.ndarray            # str: "base" | "promoter" | "promoted_friend" | "ring"
    available_at: np.ndarray      # datetime64 or NaT

def load(run_dir: Path, seed: int) -> tuple[World, Truth]
```

**Tasks:**
- [ ] Simulator: add `variant` to labels and the stealth overlay. Tests:
  - stealth labels carry `"stealth"`;
  - the `stealth_p = 0` run's legacy export is byte-identical to `main`;
  - `datagen check` passes.
- [ ] `world.load`:
  - permute ids with `public_ids.feistel`;
  - drop `partition_id`, `action_id`, `cause_id` and `seq`;
  - join cohort through `user_signed_up.partition_id → cases.cohort` (truth only).
- [ ] Tests on the bench run:
  - 931 bad and 414 stealth;
  - `test_world_has_no_provenance_columns`;
  - `test_no_single_world_column_scores_ring_auc_above_0_8`, which includes the user id.

### Task 2: M2 protocol and baselines (1.5 h)

**Files:** create `discover/protocol.py`, `discover/methods/{__init__,baseline}.py` and
`tests/test_discover_protocol.py`.

**Interfaces:**

```python
class Method(Protocol):
    key: str
    def propose(self, world: World, known: dict[int, int], k: int) -> list[int]
    def score(self, world: World, known: dict[int, int]) -> np.ndarray   # aligned to user_ids

class Oracle:
    def __init__(self, truth: Truth, world: World, budget: int)
    def review(self, ids: list[int]) -> dict[int, int]   # rejects reviewed or unknown ids for free
    spent: int

def draw_seeds(truth, world, n: int, t_report_days: float, rng) -> list[int]
def run_method(method, world, truth, *, seeds, k: int, rounds: int) -> Trace
# Trace: reviewed ids per round, hits per round, final scores
```

`METHODS: dict[str, Callable[[int], Method]]` is the registry, keyed by seed.

**Tasks:**
- [ ] Oracle and seeds. Tests:
  - seeds are bad, not stealth, and available by `t_report`;
  - too few candidates raises `ValueError`;
  - re-reviewing an id does not spend budget.
- [ ] `random` and `perfect`. Tests:
  - on the bench world at K = 50 and R = 10, `perfect` finds 500 of 500 and `random` finds about 2%.
- [ ] `test_methods_never_import_truth`: an AST scan of `methods/`, with `baseline.perfect`
  allowed.

### Task 3: M3 methods (3.5 h)

**Files:**
- Create:
  - `discover/features.py` (the behaviour vector);
  - `methods/graph.py` (`connection`, `money_flow`);
  - `methods/behaviour.py` (`similarity`, `pu_learn`, `sync`);
  - `methods/weak.py` (the labeling functions, `rules`, `label_model`);
  - `methods/active.py`;
  - `methods/vote.py`;
  - `tests/test_discover_methods.py`.
- Each method keeps its defaults as module constants, with a comment saying they are frozen.

**Tasks:**
- [ ] `features.user_matrix(world) -> (np.ndarray, list[str])`, with the 11 features from the spec.
  - Test: one row per user, with no NaN.
- [ ] Graph:
  - user–device edges from sessions and signups, device weight 1/log(1 + users);
  - invite edges, and bonus edges weighted by count;
  - PageRank with restart on known bad, alpha 0.15, 30 iterations.
- [ ] Behaviour:
  - kNN (k = 20) on standardized features;
  - PU logistic regression with 20× unlabeled negatives;
  - `sync`: a 2-hour window over signup, first-order and bonus times, on the same SKU.
- [ ] Weak supervision:
  - the 6 labeling functions;
  - majority vote;
  - Dawid-Skene EM (20 iterations), with known labels clamped.
- [ ] `active`: XGBoost on known labels, retrained each round, 100 rounds, depth 4.
  - In round 1 only seeds are known, so it uses unlabeled users as soft negatives, as in `pu_learn`.
- [ ] `vote` over the top 2% of each of the 5 member methods.
- [ ] One sanity test per method on a 30-user toy world:
  - a ring of 5 sharing a device and an invite tree, one seed;
  - each graph method ranks the other 4 above any base user.
- [ ] Freeze the defaults: commit before M4's first scored run.

### Task 4: M4 metrics, report, CLI (1.5 h)

**Files:**
- Create: `discover/metrics.py`, `discover/report.py`, `tests/test_discover_metrics.py`,
  `tests/test_discover_cli.py`.
- Modify: `apps/bench/src/bench/cli.py` (the `discover` subcommand).

**Tasks:**
- [ ] `metrics.summarize(trace, truth) -> dict`:
  - discovery curve; hit rate per round;
  - recall at the budget;
  - AUC and PR-AUC over unreviewed users; precision and recall at the top 931;
  - recall on stealth and non-stealth members;
  - false-alarm rate by cohort;
  - approval rate against bad share among approved users.
  - Tests use hand-computed values on a 10-user case.
- [ ] `bench discover`:
  - `--run DIR`, or `--generate PROJECT` with `--profile`, `--overlay` and `--seed`;
  - `--methods`, `--k 50`, `--rounds 10`, `--sweep 0,2,5,10`, `--seed-draws 5`, `--out`, `--lang`.
  - `--generate` calls datagen in-process. datagen is already a dev dependency; it becomes a
    runtime import, guarded with a clear error if it is missing.
- [ ] The report: one HTML file, inline SVG, in the style of the existing bench report.
  - Sections:
    - discovery curves, mean ± spread;
    - a method × metric table;
    - ROC and PR side by side;
    - stealth and non-stealth recall bars;
    - the cohort false-alarm table;
    - the risk view.
  - Test: the file is written, has no unfilled placeholders and no external `src`.
- [ ] CLI smoke test on the toy world, with 2 methods, K = 3 and R = 2.

### Task 5: M5 run and write up (1 h)

- [ ] `bench discover --generate examples/ecommerce --profile bench --overlay bounty_hunters --seed 42`
  with all methods, the sweep and 5 seed draws. Expected wall time is under 10 min; cap it at 20.
- [ ] Add a results section to the spec, covering:
  - the method ranking;
  - what each method misses (stealth members) and what it wrongly flags (promoters);
  - whether R = 0 differs from R = 10.
- [ ] Update `apps/bench/README.md` with the command and outputs.
- [ ] Run the full test suite and ruff.
- [ ] Report back:
  - elapsed time against this plan;
  - the result table;
  - the HTML report path; offer to publish it as an artifact.
