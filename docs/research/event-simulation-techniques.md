# Simulating Event-Based Systems: Techniques, Difficulties, Prior Platforms

Compiled 2026-10-14. Each claim carries a URL. Tags: **[P]** = traced to a primary source fetched during research; **[U]** = unverified (general knowledge, search-snippet only, or a source that could not be fetched; treat as unconfirmed). Companion to `event-based-systems.md`.

Purpose: how to generate realistic events to (a) validate data pipelines and (b) build sample data for modeling, dashboards and reports.

---

## 0. Landscape: three families of approach

| Family | Idea | Examples | Strength | Weakness |
|---|---|---|---|---|
| Learned synthesis | Fit a generative model to real tables/sequences, sample new rows | SDV (HMA, PAR), Gretel | Mimics real marginals and pair correlations | Needs real data; privacy risk; weak on rare/planted structure |
| Mechanistic simulation | Agents or processes with explicit rules; emit events | PaySim, BankSim, AMLSim, IBM AML generator, Mesa | Ground truth is known; scenarios can be planted | Realism depends on hand-set/calibrated parameters |
| Process-mining playout | Discover a process model from a log, replay it to make new traces | PM4Py, Simod/Prosimos | Control flow and timing learned from logs | Needs an event log; weak on attribute coherence |
| Rule/faker-style fill | Independent per-field generators | Faker | Cheap, fast, seedable | No behavioral or cross-field coherence |

- Faker: generators are grouped into providers, seedable via `Faker.seed()` / `seed_instance()`; no model of journeys. [P] <https://faker.readthedocs.io/en/master/>
- Mesa: modular agent-based modeling library with model/agent classes, an AgentSet, scheduled steps and a DataCollector that exports pandas DataFrames. [P] <https://mesa.readthedocs.io/stable/overview.html>
- SDV HMASynthesizer: one model per table linked by parent-child relations, Gaussian copulas at the base. [P] <https://docs.sdv.dev/sdv/multi-table-data/modeling/synthesizers/hmasynthesizer>
- SDV PARSynthesizer: "Probabilistic Auto-Regressive" model for sequences; one sequence per entity identified by `sequence_key`. [P] <https://docs.sdv.dev/sdv/modeling/sequential-synthesizers/parsynthesizer.md>

---

## 1. Behavioral validity (plausible journeys)

### 1.1 Techniques
- **Transition graph / state machine**: states = event types, edges = allowed next events with probabilities; sign-up has no incoming edge from sign-in. Precedence is encoded structurally (unreachable states) rather than checked after the fact. [U, standard practice; no single source]
- **Markov chain / HMM**: first-order chain over event types gives transition probabilities; an HMM adds a latent intent state (browsing vs. buying vs. fraud). Hard constraints still need a guard because a chain cannot enforce "once per user" or "after X". [U]
- **Autoregressive sequence models**: SDV PAR learns to "create brand new sequences of multi-dimensional data" per entity, with context columns fixed within a sequence. It does not promise constraint satisfaction. [P] <https://docs.sdv.dev/sdv/modeling/sequential-synthesizers/parsynthesizer.md>
- **Agent-based models**: each agent has goals/rules and acts over time. PaySim started as a multi-agent simulation (MABS) based on the schema of a real mobile money service, then moved to aggregated real transactional data to drive activity. [P] <https://github.com/EdgarLopezPhD/PaySim>
- AMLSim: "multi-agent simulator of anti-money laundering"; Python stage builds the transaction graph, Java stage (MASON) runs the simulation; `random_seed` and `total_steps` in `conf.json`. [P] <https://github.com/IBM/AMLSim>
- IBM AML generator (Altman et al.): agent-based, calibrated to match real transactions, ground-truth labels "complete". [P] <https://arxiv.org/abs/2306.16424>
- BankSim: agent-based simulator of bank payments from aggregated transaction data of a Spanish bank; calibrated with statistics and social-network analysis of merchant/customer relations. [P-snippet via search; PDF not opened] <https://ddd.uab.cat/record/128517?ln=en> -> treat as [U] for details.
- **Process-mining playout**: Simod discovers a business process simulation model from a CSV event log (optionally a BPMN model), including resource calendars and data-aware branching rules, and simulates it with the Prosimos engine. [P] <https://github.com/AutomatedProcessImprovement/Simod>
- PM4Py is a Python process mining library; Petri-net/process-tree playout functions exist in its API but the page fetched did not confirm them. [U] <https://github.com/process-intelligence-solutions/pm4py>
- **Session/clickstream generators**: typically a Markov chain per persona with dwell-time distributions. [U]

### 1.2 Precedence / constraint handling (design options)
1. Structural: only legal transitions exist in the graph (cheapest, always valid). [U]
2. Dependency-aware sampling: events require predicates on entity state (e.g. `has_card`) before they are eligible. [U]
3. Post-hoc validators: reject or repair; useful as tests, brittle as the only mechanism. [U]
4. Time-ordering: a child event's time is drawn as parent time plus a positive delay, never independently. [U]

### 1.3 Known difficulty
- Fitted/learned sequence models can generate plausible-looking but invalid orderings; PaySim's native fraud was reported as closer to single-account takeover than coordinated multi-account activity, i.e. journeys were narrower than the real phenomenon. [P-snippet; secondary arXiv paper not opened] <https://arxiv.org/pdf/2607.19266> -> [U]

---

## 2. Attribute consistency (entity -> device -> session -> event)

### 2.1 Technique: hierarchical, entity-centric generation
- Generate parents first, then children conditioned on them: user -> device(s) -> session(s) -> events. Attributes live at the level where they are constant (device OS and model at device level; user agent at device/session level; event amount at event level). [U, design synthesis]
- SDV expresses this as parent-child tables (HMA) and "context columns" that "do not vary inside of a sequence" (PAR). [P] <https://docs.sdv.dev/sdv/multi-table-data/modeling/synthesizers/hmasynthesizer>, <https://docs.sdv.dev/sdv/modeling/sequential-synthesizers/parsynthesizer.md>
- HMA is optimized for "around 5 tables and 1 level of depth", has no conditional sampling, and handles only parametric distributions. [P] <https://docs.sdv.dev/sdv/multi-table-data/modeling/synthesizers/hmasynthesizer>
- PAR is not suited to single-sequence datasets. [P] <https://docs.sdv.dev/sdv/modeling/sequential-synthesizers/parsynthesizer.md>

### 2.2 Cross-device logical sessions (KYC: QR on desktop, face scan on mobile, callback to desktop)
No source found treating this directly. Suggested model [U, synthesis]:
- Separate the **logical flow** (a `flow_id`/journey with its state machine) from the **physical session** (device-bound, with its own device attributes).
- Each flow step is assigned to a device from the user's device set; a handoff step (QR scan) is an explicit event that links two physical sessions via a shared token/`flow_id`.
- Device attributes are looked up from the device, never resampled per event; IP/geo attributes follow the physical session, so the desktop and mobile legs legitimately differ.
- Event time must be monotonic along the flow even though device-local clocks may skew (see client-clock correction in `event-based-systems.md` sec. 1.4). [P] <https://www.twilio.com/docs/segment/connections/spec/common>

---

## 3. Attribute dynamics (slow, fast, mid-session drift)

- **Classification by volatility**: static (device model), slow (state of residence, user agent version), fast (battery level, IP on mobile). [U, convention]
- **Piecewise-constant timelines**: sample change points (Poisson process) and hold values between them. Homogeneous Poisson has exponential inter-arrival times; inhomogeneous rates can be simulated by acceptance-rejection. [P] <https://en.wikipedia.org/wiki/Poisson_point_process>
- **SCD Type 2 as storage form**: one row per value with start/end validity, so events can be joined as-of time. [P] <https://en.wikipedia.org/wiki/Slowly_changing_dimension>
- **Ornstein-Uhlenbeck**: mean-reverting continuous process with Gaussian stationary distribution N(mu, sigma^2/(2 theta)) and an exact Gaussian transition for any step size; suitable for bounded-ish fast numeric attributes (battery level, signal strength) once discretized/clipped. [P] <https://en.wikipedia.org/wiki/Ornstein%E2%80%93Uhlenbeck_process>
- **Random walk with reflection** at the range bounds is a simpler discrete alternative (used in this repo, sec. 8). [U for the general claim]
- **Mid-session drift**: model as a change-point event within a session (IP changes when user moves between Wi-Fi and cellular). Correlated attributes (IP, geo, ISP) should change together; independent change points produce impossible combos. [U]
- **Realistic ranges**: derive time scales from real data where possible; battery drains ~monotonically between charge events, so OU alone is unrealistic and a sawtooth/charge-cycle model is better. [U]

---

## 4. Linkage (shared devices, IPs, referrals, rings)

- **Preferential attachment / Barabasi-Albert**: new nodes attach proportional to existing degree; can yield power-law degree distributions (gamma = 3 for BA). [P] <https://en.wikipedia.org/wiki/Preferential_attachment>
- **Stochastic block model**: graph from a partition into communities and a link-probability matrix; planted-partition form has p within and q between communities. [P] <https://en.wikipedia.org/wiki/Stochastic_block_model>
- **Planted fraud rings**: AMLSim takes alert-pattern parameter files and a degree sequence, and ships `validate_alerts.py` to check generated alert subgraphs against the parameters. [P] <https://github.com/IBM/AMLSim>
- **Making events chainable**: linkage is carried by reference columns (inviter_id, device_id, ip) on events/entities so features such as users-per-device, degree, or ring size are computable by grouping. Referenced entities must exist before the referencing row's time. [U, design synthesis]
- Difficulty: shared-device density, ring size and overlap with benign sharing (families, internet cafes) are rarely known from real data, so the benign background of sharing is as important as the planted fraud. [U]

---

## 4A. Configurable linkage-graph generation (nodes, edges, concentration)

Scope note: "wells concentration" in the request is read as "whale concentration" (a few entities dominating volume/value); hub/degree concentration is covered alongside. [interpretation, not a sourced claim]

### 4A.1 Identifying / creating nodes
- Nodes are the entity IDs of the schema (user, device, IP, referral code, account). Two styles: (a) **pre-created population**: fix node counts per type, then draw edges between them; AMLSim's `accounts.csv` lists account `count`, balance range, open/close days, country, business type and behavior `model`. [P] <https://github.com/IBM/AMLSim/wiki/Data-Schema-for-Input-Parameters-and-Generated-Data-Set> (b) **nodes born with events**: new IDs minted when a sign-up/first-seen event fires, the usual way for devices and IPs. [U]
- Node types with different roles need separate count/lifetime knobs (users sign up over a window; devices are created per user; IPs come from a finite pool). [U]
- Reference columns (an event/entity attribute whose value is another node's ID) are the on-the-wire form of an edge. [U for the generalization; repo precedent in sec. 8]

### 4A.2 Edge-generation techniques and their knobs

| Technique | How edges are made | Tunable knobs | Source |
|---|---|---|---|
| Preferential attachment (Barabasi-Albert) | New node attaches to existing nodes with prob. proportional to degree | `m` edges per new node, offset `a`; tail exponent gamma = 2 + (k0 + a)/m (gamma = 3 for BA) | [P] <https://en.wikipedia.org/wiki/Preferential_attachment> |
| Configuration model | Assign stubs per node from a degree sequence, pair stubs at random | Exact degree sequence (so any distribution can be drawn first); self-loops/multi-edges possible | [P] <https://en.wikipedia.org/wiki/Configuration_model> |
| Chung-Lu | Edge probability scales with product of endpoint weights/degrees; degrees match only in expectation | Expected-degree vector | [P] same page (variant); dedicated page not fetched |
| Stochastic block model | Link-probability matrix over communities; planted partition p (within) vs q (between) | Number/sizes of blocks, matrix entries, p/q ratio | [P] <https://en.wikipedia.org/wiki/Stochastic_block_model> |
| Degree-list generation (AMLSim) | `degree.csv` rows give how many vertices have given in-/out-degree | Count per (in-degree, out-degree) pair | [P] <https://github.com/IBM/AMLSim/wiki/Data-Schema-for-Input-Parameters-and-Generated-Data-Set> |
| Typology/ring injection (AMLSim) | `alertPatterns.csv`: pattern `type` (fan_in, fan_out, cycle...), `count`, min/max accounts, min/max amount, min/max period, `schedule_id` (same interval / random interval / random), `is_sar` true/false-alert | Number of rings, ring size, amounts, duration, timing mode, labeled-or-decoy | [P] same page |
| Shared-device / IP fan-out | A device (IP) node has a bounded number of users; edge = user uses device | Cap on users per device, distribution of fan-out (e.g. heavy-tailed with a hard cap), fraction of users with shared devices | [U, no source found; design synthesis] |

- Edge **generation rate** is usually an indirect knob: mean degree (stubs/`m`), probability matrix scale, or events-per-entity rate times the chance that an event creates a new link (new device, new referral). There is no standard "edge rate" parameter across the sources read. [U]
- Rejection of self-loops and multi-edges (or allowing them) is an explicit decision; the configuration model does not exclude them. [P] <https://en.wikipedia.org/wiki/Configuration_model>

### 4A.3 Edge arrival over time
- Temporal networks: links are active only at certain times; each link carries when it is active; inter-event times are often heterogeneous (bursty). [P] <https://en.wikipedia.org/wiki/Temporal_network>
- Burstiness measure B: 1 = maximally bursty, 0 = Poisson, -1 = periodic. A usable calibration target for edge arrival. [P] same URL.
- Hawkes processes give self-exciting arrivals (a link event raises the near-term rate of further link events, e.g. invite cascades); branching ratio <= 1 keeps descendants finite. Knobs: baseline rate, kernel, branching ratio. [P] <https://en.wikipedia.org/wiki/Hawkes_process>
- Inhomogeneous Poisson for diurnal/weekly modulation of the edge rate. [P] <https://en.wikipedia.org/wiki/Poisson_point_process>
- AMLSim lays edges on a time axis via `total_steps`/`base_date` and per-pattern period and schedule mode. [P] <https://github.com/IBM/AMLSim>, <https://github.com/IBM/AMLSim/wiki/Data-Schema-for-Input-Parameters-and-Generated-Data-Set>
- Referenced node must exist before the edge time (causal ordering of node birth vs edge birth). [U; repo rule in sec. 8]

### 4A.4 Concentration ("whale") behavior
Two separate things to configure:
1. **Degree concentration** (hubs): heavy-tailed degree from preferential attachment [P] <https://en.wikipedia.org/wiki/Preferential_attachment>, a drawn degree sequence fed to configuration model/Chung-Lu [P] <https://en.wikipedia.org/wiki/Configuration_model>, or Zipf-style rank-size weights [P] <https://en.wikipedia.org/wiki/Zipf%27s_law>.
2. **Volume/value concentration** (whales): per-entity activity or amount drawn from a heavy-tailed law.
   - Pareto: tail index alpha; Pareto principle 80/20 corresponds to alpha = log_4(5) ~ 1.16; Gini = 1/(2 alpha - 1) for alpha >= 1; mean infinite for alpha <= 1, variance infinite for alpha <= 2. [P] <https://en.wikipedia.org/wiki/Pareto_distribution>
   - Zipf: value at rank n roughly proportional to 1/n^s; infinite set needs s > 1; log-log plot slope -s. [P] <https://en.wikipedia.org/wiki/Zipf%27s_law>
   - Gini coefficient: Lorenz-curve-based, 0 = equality, 1 = absolute inequality; usable as a single "concentration" target. [P] <https://en.wikipedia.org/wiki/Gini_coefficient>
   - Top-k share (e.g. "top 1% of users = 40% of volume") is a more interpretable knob than alpha; invert it numerically to a Pareto/lognormal parameter. [U, design synthesis]
- **Parameterization in simulators**:
  - AMLSim: concentration is expressed via the degree list (counts per in/out degree), per-account behavior `model` (single/fan-out/fan-in/mutual/forward/periodical) and balance ranges, not a single Gini knob. [P] <https://github.com/IBM/AMLSim/wiki/Data-Schema-for-Input-Parameters-and-Generated-Data-Set>
  - PaySim: activity is driven by aggregated real transaction data (statistics per transaction type); README documents no concentration parameter. [P] <https://github.com/EdgarLopezPhD/PaySim>
  - IBM AML generator: described as agent-based and calibrated to real transactions; concentration parameters could not be extracted (PDF text unreadable via fetch; repo page 404). [U] <https://arxiv.org/abs/2306.16424>
- Pitfall: heavy tails with alpha <= 2 make sample means and variances unstable, so a seeded sample's Gini or top-k share fluctuates strongly between runs. [P for moment conditions; U for the run-to-run consequence] <https://en.wikipedia.org/wiki/Pareto_distribution>

### 4A.5 Other knobs worth exposing (all [U] unless cited)
- Node counts per type and arrival curve (sign-up rate over time).
- Reciprocity / mutual edges, clustering (triadic closure), assortativity (do hubs link to hubs).
- Community structure: number, size skew, p/q ratio [P: SBM page above]; fraction of cross-community links.
- Benign shared-infrastructure background (families, offices, carrier NAT IPs) so rings are not the only sharing.
- Ring injection: count, size range, member selection rule (e.g. rank band of sign-up order), overlap with benign communities, share of members on a common device, timing mode, labeled vs decoy (AMLSim `is_sar`). [P for the AMLSim fields]
- Lifetime/churn of nodes and edges (devices retire, referral codes expire).
- Noise: fraction of edges rewired at random, to prevent trivially recoverable structure.
- Label coupling: how strongly ring/hub membership shifts the label (signal strength).

### 4A.6 Difficulties and past attempts in calibrating to target statistics
- Parameters of generators and observed statistics are not one-to-one: SBM p/q or BA `m` set degree/community structure only indirectly, so hitting a target mean degree + clustering + tail exponent simultaneously needs search. [U]
- Calibration precedent: IBM generator "calibrated to match real transactions as closely as possible" [P] <https://arxiv.org/abs/2306.16424>; BankSim used statistics and social-network analysis to calibrate [U, snippet] <https://ddd.uab.cat/record/128517?ln=en>; Simod automates tuning of simulation parameters from logs [P] <https://github.com/AutomatedProcessImprovement/Simod>.
- Public sample-size discrepancy: AMLSim's own `degree.csv` example has row counts that do not sum to the stated vertex count, illustrating how easy it is for hand-written degree specs to be inconsistent; validate configs up front. [P, observed from page] <https://github.com/IBM/AMLSim/wiki/Data-Schema-for-Input-Parameters-and-Generated-Data-Set>
- Validation of the produced graph against its config is a precedent (`validate_alerts.py`). [P] <https://github.com/IBM/AMLSim>
- Realism of structure can still mislead: PaySim's fraud described as closer to single-account takeover than coordinated activity. [U, snippet] <https://arxiv.org/pdf/2607.19266>

### 4A.7 Declarative and reproducible configuration
- AMLSim pattern: one `conf.json` (`input`/`general`/`output`) pointing at CSV parameter files for accounts, degree and typologies; `random_seed` fixes randomness. [P] <https://github.com/IBM/AMLSim>
- Recommended shape (design synthesis, [U]): a config with `nodes` (type, count, arrival), `edges` (relation, source/target type, generator, params, cap), `concentration` (metric: top-k share or Gini, target value), `rings` (count, size, member rule, timing), `time` (span, seasonality, burstiness), plus `seed`. Config is validated up front (sums, ranges, feasibility), hashed, and written beside outputs together with achieved statistics (achieved Gini, degree histogram, ring count).
- Derive an independent RNG stream per component (nodes, edges, rings, attributes) from the root seed so changing one block leaves others unchanged. [U]
- Seeds reproduce only for identical library versions (Faker caveat). [P] <https://faker.readthedocs.io/en/master/>

---

## 5. Other challenges

### 5.1 Fidelity vs privacy
- Real data is often unavailable for AML research and earlier synthetic generators had "major shortcomings" per the IBM paper; a calibrated generator gives shareable data. [P] <https://arxiv.org/abs/2306.16424>
- BankSim data "contain no personal information" and can be shared. [P-snippet] <https://ddd.uab.cat/record/128517?ln=en> -> [U]
- Differential privacy formalizes a utility-privacy trade-off: stronger privacy means more noise and less accuracy. [P] <https://en.wikipedia.org/wiki/Differential_privacy>
- Learned synthesizers fit to real data can leak records; a purely mechanistic simulator with no real inputs avoids this by construction. [U]

### 5.2 Temporal patterns
- Diurnal/weekly seasonality: inhomogeneous Poisson process with a periodic intensity. [P for the process] <https://en.wikipedia.org/wiki/Poisson_point_process>; [U for the periodic-intensity recipe].
- Burstiness / self-excitation: Hawkes process, intensity = baseline + decaying kernel per past event; finite descendants almost surely if branching ratio <= 1. [P] <https://en.wikipedia.org/wiki/Hawkes_process>
- Hawkes is used for statistical modeling in mathematical finance. [P] same URL.
- Heavy tails: preferential attachment can produce power laws [P] <https://en.wikipedia.org/wiki/Preferential_attachment>; amounts and inter-event gaps are commonly log-normal/Pareto [U].

### 5.3 Class imbalance and label delay
- Target bad rates are low (fraud often low single-digit percent or less); label delay (chargebacks, SAR) means recent labels are immature. [U, standard practice]
- The IBM paper argues complete labels are a benefit of synthetic data vs real data where much laundering goes undetected. [P] <https://arxiv.org/abs/2306.16424>
- Evaluating with a random split instead of a temporal split does not mimic deployment under shifting patterns. [P-snippet] <https://arxiv.org/pdf/2607.19266> -> [U]

### 5.4 Leakage
- Point-in-time features must use only data strictly before the event; shuffled splits and future-aware aggregates leak. [U, practice]
- PaySim: balance columns are not usable for fraud detection since flagged transactions are cancelled (an artifact of the generator). [P-snippet via Kaggle description] -> [U]
- Concept drift: models lose accuracy as the data evolves; synthetic data should be able to include drift to test this. [P] <https://en.wikipedia.org/wiki/Concept_drift>

### 5.5 Evaluating realism of synthetic data
- **TSTR** (train on synthetic, test on real) was proposed to test usefulness beyond likelihood/MMD, demonstrated for RCGAN time series. [P] <https://arxiv.org/abs/1706.02633>
- **Distributional checks**: SDV Quality Report scores Column Shapes (marginals) and Column Pair Trends (pairs); 100% means identical patterns; it checks only 1-2 dimensional patterns and is "a proxy" of utility, "not a guarantee". [P] <https://docs.sdv.dev/sdv/single-table-data/evaluation/data-quality>
- Sequence-level properties (journey order, inter-event gaps, per-user event counts) are not covered by column-level metrics and need dedicated tests. [U]
- **Simulator-validity claim**: simulated PaySim data "can be as prudent as the original dataset for setting optimal controls", a claim limited to threshold setting. [P-snippet] <https://www.inderscience.com/offer.php?id=93756> -> [U]

### 5.6 Validating ground truth
- Where labels come from a known generative rule, they are exact by construction (IBM: "ground truth labels are complete"). [P] <https://arxiv.org/abs/2306.16424>
- Still verify that the planted structure was actually produced: AMLSim's alert validator is the precedent. [P] <https://github.com/IBM/AMLSim>

---

## 6. Configurability and reproducibility

- Declarative configuration: AMLSim drives everything from `conf.json` (`input`, `general`, `output`) plus parameter CSVs (accounts, degree sequence, alert patterns). [P] <https://github.com/IBM/AMLSim>
- Seeding: `random_seed` in AMLSim [P] same URL; Faker `Faker.seed()` and `seed_instance()`, with results guaranteed only for the same Faker version [P] <https://faker.readthedocs.io/en/master/>; Mesa batch runs pass distinct seeds per run from a seeded NumPy generator [P] <https://mesa.readthedocs.io/stable/overview.html>.
- Lesson: pin library versions as well as seeds; record seed, config and versions beside outputs. [P for Faker version caveat; U for the generalization]
- Calibration/tuning: IBM generator "calibrated to match real transactions as closely as possible" [P] <https://arxiv.org/abs/2306.16424>; Simod tunes simulation parameters from logs [P] <https://github.com/AutomatedProcessImprovement/Simod>; BankSim used statistics and SNA to calibrate [U].
- Per-component RNG streams (so adding an attribute does not shift unrelated draws) are good practice for stable diffs between runs. [U]

---

## 7. Usability for research (labels, planted signals, benchmarks)

- Public benchmark datasets from simulators: PaySim1 on Kaggle (April 2018) [P] <https://github.com/EdgarLopezPhD/PaySim>; IBM AML datasets released as a standardized benchmark [P] <https://arxiv.org/abs/2306.16424>.
- IBM paper argues synthetic data can sometimes be better than real for model comparison because labels are complete. [P] same URL.
- Planted signals: AMLSim injects known alert patterns and outputs alerted accounts/transactions and SAR accounts. [P] <https://github.com/IBM/AMLSim>
- Known weakness of public simulators as benchmarks: narrow fraud typologies (PaySim) mean models may overfit to generator artifacts. [U, from secondary snippet]
- Practice: ship the oracle/ceiling (what a model could achieve with the hidden signal) so benchmark scores are interpretable. [U]

---

## 8. Relation to this repo (libs/simkit, apps/datagen)

Based on `docs/superpowers/specs/2026-10-13-ml-sim-datagen-design.md` and `libs/simkit` (read, not modified).

| Topic | This repo's design | Relation to findings |
|---|---|---|
| Realism strategy | "Planted-signal": sampled entities/events, golden features point-in-time, preset scorer -> labels; no agent-based simulation in v1 | Closest to a mechanistic generator with exact ground truth (sec. 5.6, 7); trades behavioral realism (sec. 1) for control |
| Behavioral validity | Skewed per-user activity, warm-up then cash-out, zombie bursts; no transition graph or precedence engine | Gap vs sec. 1: no sign-up-before-sign-in structure beyond "users sign up over first 90% of span" and "referenced IDs must predate row" |
| Attribute model | `AttrSpec` with cardinality (low/high) x volatility (static/slow/fast); `sample_timeline` emits long-form `(entity_id, attr, valid_from, value)`; fast attrs reflecting random walk, slow attrs redraw at Poisson change points | Matches SCD-style piecewise-constant timelines (sec. 3); reflecting walk is the discrete cousin of OU; attributes change independently (state/street/zip), which sec. 3 flags as a realism risk |
| Hierarchy / cross-device | Entities user/device/product with independent attribute timelines; no session entity, no cross-device flow | Gap vs sec. 2: no `session`/`flow_id` layer, so KYC handoffs cannot be expressed yet |
| Linkage | `RefSpec(column, target_entity, nullable, chooser)` reference columns; no edge table; bounty-hunter inviters, device rings (70% sharing) | Same idea as sec. 4 (chainable events via references); chooser is a hand-planted preferential-attachment-like skew; no benign background community structure |
| Point-in-time & leakage | Golden features strictly before event (window [t-w, t)); property test vs brute force; `export` refuses golden columns in `events.parquet`; bench fails fast on golden names | Directly addresses sec. 5.4; stronger than most public simulators |
| Labels | golden -> XGBScorer teacher -> calibrate to target rate (~2%) -> Bernoulli; no label delay | Imbalance handled (5.3); label delay and drift not modeled |
| Reproducibility | `--seed`, `meta.json` with seed/config/versions, determinism test; Python-module scenarios (no YAML) | Matches sec. 6; declarative config is explicitly out of scope in v1 |
| Evaluation | Oracle vs raw-column AUC, time-based split | Analogue of TSTR-style utility check (sec. 5.5) but against its own hidden truth, not real data; no distributional-fidelity tests |

Linkage-graph configurability (sec. 4A) vs this repo:
- Node identification: entity types with UUID namespaces, counts and sign-up times set per scenario in Python; edges are `RefSpec` reference columns, so there is no separate edge/degree spec.
- Concentration is planted by a scenario-specific `chooser` (bounty hunters drawn from the 5-25% sign-up rank band receive a large share of invites) and skewed per-user activity ("earlier users transact more"), not by a declared target such as top-k share or Gini; achieved concentration is not reported in `meta.json` (only achieved bad rate).
- Edge arrival: invite events follow the event timeline; no Hawkes/burstiness knob. Fan-out cap on devices is implicit in the 70% device-ring rule rather than a configurable limit.
- Reproducibility fits sec. 4A.7 (seed, config, versions recorded), but config is Python, not declarative; the closest generic building block is the `RefSpec` chooser.
- Candidate additions: a `ConcentrationSpec` (target top-k share/Gini, solved to a Pareto/lognormal parameter), reporting achieved concentration and degree stats in `meta.json`, a per-device user-count cap, and a ring-injection spec modeled on AMLSim's typology rows.

Suggested next steps (derived, not from sources): add a session/flow entity for cross-device journeys; generate benign sharing background alongside rings; couple IP/geo attribute change points; add diurnal/weekly intensity and optional Hawkes bursts; consider label-delay masking.

---

## Claims lacking primary sources (summary)

- All "[U]" items: transition-graph/Markov/HMM precedence handling, clickstream generators, cross-device flow modeling, battery sawtooth, benign sharing background, per-component RNG streams, label-delay practice, heavy-tail amount distributions.
- BankSim details (Spanish bank, calibration, shareable data): only seen in search-result snippets of <https://ddd.uab.cat/record/128517?ln=en>; PDF not opened.
- PaySim limitations (single-account takeover, Kaggle balance caveat, 2018 threshold-setting claim): only via search snippets of <https://arxiv.org/pdf/2607.19266> and <https://www.inderscience.com/offer.php?id=93756>; the original EMSS 2016 PaySim paper was not fetched.
- PM4Py playout/simulation functions: docs host (pm4py.fit.fraunhofer.de) unreachable; GitHub README did not mention them.
- Gretel docs: host unreachable; no Gretel claims made.
- Simod page did not detail hyperparameter optimization or output formats; AMLSim README did not detail pattern types.
- Sec. 4A: shared-device fan-out caps, a generic "edge rate" knob, top-k-share-to-Pareto inversion, benign sharing background, and the declarative config shape are design synthesis [U]. IBM AML generator concentration/pattern parameters not extracted (PDF unreadable via fetch; AMLworld repo and AMLSim `docs/parameters.md` returned 404). Chung-Lu has only the configuration-model page variant note (dedicated page 404).
- Hawkes thinning simulation (Ogata) and crime applications not confirmed; only the branching-ratio and finance-use claims were.
