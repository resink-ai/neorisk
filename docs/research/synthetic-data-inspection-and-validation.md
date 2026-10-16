# Inspecting and Validating Synthetic Event Datasets

Compiled 2026-10-15. Each claim carries a URL. Tags: **[P]** = traced to a primary source fetched during research; **[U]** = unverified (general knowledge, search-snippet only, a source that could not be fetched, or design synthesis; treat as unconfirmed). Companion to `event-simulation-techniques.md` and `event-simulation-programmability-and-agents.md`.

Question: when an AI agent configures a simulation of a platform (e-commerce, trading, payments, SNS, L1 chain), how do we check that the **generated data** is realistic and not nonsense? Scope is strictly data-side: inspect and validate the output dataset, treat the simulator as a black box. The output of this work is usually a summary report, statistics or a dashboard.

---

## 0. Summary

| Layer | Question it answers | Needs a reference? | Main tools / methods |
|---|---|---|---|
| A. Overview + profile | What is in the data, at what volume, over what time? | No | ydata-profiling, whylogs, Evidently summary, custom event counts |
| B. Schema / catalog conformance | Does every event match the declared event catalog? | No (needs the spec) | JSON Schema (Snowplow-style), Pandera, Great Expectations, Amplitude/Avo-style status |
| C. Behavioral structure | Are journeys legal and plausible? | No for legality, yes for plausibility | Directly-follows graph, transition matrix, variants, PM4Py conformance, LTLf rules |
| D. Linkage structure | Do shared devices/IPs/referrals form a plausible graph? | Target stats or reference | NetworkX/graph-tool: degree, components, clustering, assortativity |
| E. Invariants | Is anything internally impossible? | No | Integrity constraints, denial constraints, ledger conservation, point-in-time checks |
| F. Realism vs targets | Do distributions match the spec's targets or a real reference? | Yes (targets or real) | KS/TVD/Wasserstein/JSD, correlation and contingency similarity, MMD, C2ST/pMSE, alpha-precision/beta-recall, TSTR |
| G. Domain stylized facts | Does it look like the domain (fat tails, burstiness, diurnal cycles)? | Literature facts | Clauset power-law fit, burstiness B, ACF, STL, Cont's stylized facts |

Main conclusions:
1. Split the checks into **hard invariants** (must be 0 violations, no reference needed) and **soft realism scores** (distance to targets, with tolerance bands). An agent-configured simulator should be gated by the first and scored by the second. [U, synthesis]
2. Column-level tools (SDMetrics, ydata-profiling, Evidently) cover marginals and pairs only; event data needs **sequence, timing and graph** checks on top. SDMetrics itself calls its quality score a proxy and recommends task-based metrics. [P] <https://docs.sdv.dev/sdmetrics/data-metrics/quality.md>
3. When no real data exists, the "reference" is (a) the simulation spec's declared targets, (b) published stylized facts, and (c) internal consistency. Every declared target in the spec should compile into an automatic check. [U, synthesis]
4. A self-contained HTML "synthetic data inspector" fits next to `apps/bench`, reading `events.parquet` + `meta.json` (+ optional reference stats), and never opening `golden.parquet` except in a separate, clearly marked oracle section. [U, design]

---

## 1. Inspection report / dashboard for synthetic event datasets

### 1.1 Dataset overview (what to show first)

| Panel | Metric | Why it catches nonsense | Tag |
|---|---|---|---|
| Volume | rows, events by `event_type`, distinct entities per type (users, devices, IPs, accounts, products) | Missing or exploding event types; entity counts off by orders of magnitude | [U] |
| Time span | min/max event time, events per day line, empty days | Truncated spans, gaps, events outside configured span | [U] |
| Rates | events per entity (histogram, log-log), events per entity per day | Uniform activity where heavy tails are expected | [U] |
| Diurnal / weekly | hour-of-day x day-of-week heatmap per event type | Flat 24h activity, wrong time zone, weekend identical to weekday | [U] |
| Label | label rate over time, label rate by event type | Label drift or leakage-like concentrations | [U] |
| Run metadata | seed, config, versions, achieved vs target stats | Reproducibility; spec vs output comparison | [U] (`meta.json` in this repo already records seed/config, see sec. 6.6) |

### 1.2 What generic profiling tools compute

| Tool | What it computes | Fit for event logs | Tag / source |
|---|---|---|---|
| ydata-profiling | Type inference; overview (records, variables, missingness, duplicates, memory); univariate stats and histograms; correlations; missing-data analysis; duplicate rows; interactions; alerts (high correlation, skewness, uniformity, zeros, missing, constant); dataset comparison; JSON/HTML/notebook output | Good per-column view of the flat events table; blind to sequences | [P] <https://github.com/ydataai/ydata-profiling>, <https://docs.profiling.ydata.ai/latest/> |
| ydata-profiling time-series mode | `tsmode=True`, `sortby=`: ACF/PACF, NON_STATIONARY and SEASONAL warnings (ADF-based), time-gap analysis | Only for one series at a time; per-entity requires filtering first (docs example filters one site) | [P] <https://docs.profiling.ydata.ai/latest/features/time_series_datasets/> |
| Great Expectations | Expectations ("a verifiable assertion about data") grouped into suites; Data Docs render suites and validation results as HTML | Good for declarative per-column rules and catalog conformance | [P] <https://docs.greatexpectations.io/docs/reference/learn/terms/data_docs/> |
| GE core expectations | Includes `expect_column_values_to_be_unique`, `..._to_be_increasing`, `expect_column_pair_values_a_to_be_greater_than_b`, `expect_compound_columns_to_be_unique`, `expect_column_kl_divergence_to_be_less_than`, `expect_column_bootstrapped_ks_test_p_value_to_be_greater_than`, `expect_column_proportion_of_non_null_values_to_be_between`, `unexpected_rows_expectation` | `..._to_be_increasing` is column-global, so per-entity monotonic time needs a custom/`unexpected_rows` query | [P] file list <https://github.com/great-expectations/great_expectations/tree/develop/great_expectations/expectations/core>; per-entity caveat [U] |
| Evidently | Data summary (DatasetStats, ValueStats, row/column counts); drift with defaults: numerical <=1000 rows KS (p<0.05), >1000 normed Wasserstein (>=0.1); categorical <=1000 chi-square / Z-test, >1000 Jensen-Shannon (>=0.1); ~20 methods incl. PSI, Hellinger, TVD, empirical MMD; dataset drift if >50% columns drift | Use "drift" as "synthetic vs reference" comparison | [P] <https://docs.evidentlyai.com/metrics/all_metrics>, <https://docs.evidentlyai.com/metrics/customize_data_drift> |
| SDMetrics | Quality report: Column Shapes, Column Pair Trends (+ Cardinality, Intertable Trends for multi-table), averaged; Diagnostic report: Data Validity (KeyUniqueness, BoundaryAdherence, CategoryAdherence), Data Structure, Relationship Validity, Constraint Validity | Built for synthetic-vs-real; has sequential metrics (SequenceLengthSimilarity, LSTM detection) | [P] <https://docs.sdv.dev/sdmetrics/data-metrics/quality.md>, <https://docs.sdv.dev/sdmetrics/data-metrics/diagnostic/diagnostic-report-api.md> |
| Deequ | "Unit tests for data" on Spark: constraint verification (`isComplete`, `isUnique`, `isContainedIn`, `isNonNegative`, `hasApproxQuantile`), metrics computation, constraint suggestion, anomaly detection on metrics over time, metrics repository | Useful pattern: persist metrics per run and alert on run-to-run anomalies | [P] <https://github.com/awslabs/deequ> |
| whylogs | Mergeable statistical profiles (counts, types, distributions via streaming sketches, missing, cardinality), constraints, drift visualizer comparing target vs reference profile | Profile per event type, per day; merge across shards | [P] <https://github.com/whylabs/whylogs> |
| Pandera | `DataFrameSchema` / `DataFrameModel`, column and dataframe-wide checks, hypothesis tests (pandas only), Polars backend (no groupby checks, no hypothesis tests) | Good fit for this repo (Polars) for type/range checks; per-entity rules need custom code | [P] <https://pandera.readthedocs.io/en/stable/> |
| dbt tests / docs | Generic tests `unique`, `not_null`, `accepted_values`, `relationships`; each compiles to a query returning failing rows; `dbt docs generate` emits a static site | Pattern to copy: every check returns failing rows, zero rows = pass | [P] <https://docs.getdbt.com/docs/build/data-tests>, <https://docs.getdbt.com/reference/commands/cmd-docs> |

### 1.3 Adapting profilers to event logs
- Profile **per event type**, not over the whole table: a wide events table has columns that are legitimately null for most types, which a global profile reports as "missing". [U]
- Profile **per entity aggregate** (events per user, distinct devices per user, amount sum per user) in addition to per row; most realism problems are visible only at entity level. [U]
- Add **sequence and time panels** that generic profilers lack: transitions (sec. 2), inter-event times (sec. 4.5). [U]
- Store each run's profile (whylogs/Deequ style) so two simulator configs can be diffed. [U, pattern from Deequ metrics repository, see above]

---

## 2. Event transition graph and entity linkage graph

### 2.1 Directly-follows graph (DFG) / transition matrix
- Build: sort events by (case_id, time); for each case (user, session, account, order) count pairs (a -> b) of consecutive event types; add synthetic START/END nodes. Normalize rows to get a first-order Markov transition matrix. [U, standard process-mining construction]
- PM4Py exposes `discover_dfg`, `view_dfg`, `save_vis_dfg`, `get_variants`, `get_all_case_durations`, `filter_directly_follows_relation`, `filter_eventually_follows_relation`, `discover_log_skeleton` / `conformance_log_skeleton`, `discover_declare` / `conformance_declare`, `discover_temporal_profile` / `conformance_temporal_profile`. [P] <https://raw.githubusercontent.com/process-intelligence-solutions/pm4py/release/pm4py/__init__.py>
- PM4Py's site shows `discover_dfg(log)`, token-based replay fitness/precision and alignment diagnostics. [P] <https://processintelligence.solutions/pm4py/>

| View | Shows | Use | Tag |
|---|---|---|---|
| DFG with edge counts | Frequent paths, rare edges | Spot impossible edges (e.g. `add_card` before `signup`) and missing expected edges | [U] |
| Markov heatmap (from x to) | Transition probabilities | Compare to spec's declared transition matrix cell by cell; mask forbidden cells red | [U] |
| Sankey / funnel | Flow volume from step to step | Funnel conversion (signup -> kyc -> first_txn) vs target rates. Plotly Sankey takes `node.label` plus `link.source/target/value`. | [P] <https://plotly.com/python/sankey-diagram/> |
| Mermaid / Graphviz | Static diagram of the top-k edges | Embeddable in Markdown/HTML report; Mermaid edge label syntax `A -->|text| B` | [P] <https://mermaid.js.org/syntax/flowchart.html> |
| Variant table | Distinct full traces with counts and share | Long-tail of variants; 100% one variant = too regular; all-unique = random noise | [U] |
| Path length histogram | Events per case | SDMetrics `SequenceLengthSimilarity` applies KSComplement to sequence lengths | [P] <https://docs.sdv.dev/sdmetrics/data-metrics/quality/sequencelengthsimilarity.md> |

Automatic checks on the transition graph [U, synthesis]:
- **Forbidden edges**: any edge not in the spec's allowed set -> invariant violation with example case ids.
- **Precedence**: "b only after a" = for each case, first(b) > first(a) (eventually-follows, not just directly-follows).
- **Start/end activities**: allowed first events (e.g. only `signup`), allowed terminal states.
- **Unreachable / dead states**: event types declared in catalog but never observed; states with in-edges and no out-edges where the spec says they continue.
- **Funnel conversion**: step-to-step ratio vs target with tolerance.
- **Self-loop rate**: repeated same-event runs (e.g. 50 consecutive `login`) as a smell.

### 2.2 Entity linkage graph
Build bipartite graphs from co-occurrence in events: user-device, user-IP, user-payment instrument, inviter-invitee, sender-receiver (payments/L1). Project to user-user via shared nodes. [U]

| Check | Metric | Library | Tag |
|---|---|---|---|
| Degree distribution | users per device, devices per user, CCDF on log-log | NetworkX / graph-tool | [U] |
| Components | number and size distribution of connected components; giant component share | NetworkX (components section listed) | [P] <https://networkx.org/documentation/stable/reference/algorithms/index.html> |
| Clustering | `average_clustering` (on projections) | NetworkX | [P] same URL |
| Assortativity | `degree_assortativity_coefficient`, `attribute_assortativity_coefficient`, mixing matrices | NetworkX | [P] <https://networkx.org/documentation/stable/reference/algorithms/assortativity.html> |
| Reciprocity | `reciprocity`, `overall_reciprocity` (payments, follows) | NetworkX | [P] <https://networkx.org/documentation/stable/reference/algorithms/index.html> |
| Motifs | `triadic_census` (directed), k-core | NetworkX | [P] same URL |
| Communities / rings | Louvain communities; dense small components with many shared devices = ring candidates | NetworkX Louvain; graph-tool SBM inference (C++/Boost, OpenMP) for larger graphs | [P] same URL; <https://graph-tool.skewed.de/> |

Sanity rules for linkage [U, synthesis]:
- A planted fraud ring should appear as a component or community with the configured size and sharing rate; the benign background should not be a single giant clique or all-singletons.
- Max users per device / IP should respect caps (households, NAT, carrier-grade NAT are legitimate high-degree IPs; a phone with 500 users is not).
- Edge creation time must follow both endpoints' creation times (no device seen before it is first registered, unless intended).

---

## 3. Per-event attribute report

### 3.1 Per event type x attribute matrix
For each `event_type`, expand to its attributes and compute: [U, synthesis; metrics match ydata-profiling / whylogs outputs above]

| Column | Meaning |
|---|---|
| fill rate | non-null share within this event type (not global) |
| expected? | required / optional / forbidden according to catalog |
| type conformance | share matching declared type, format, regex, enum |
| cardinality | distinct count, distinct/rows ratio; flags near-unique and constant |
| distribution | histogram/top-k vs target; KS/TVD vs reference when present |
| range | min/max vs declared bounds (SDMetrics `BoundaryAdherence` is the reference-based variant) |
| drift over time | per-day mean/top-k share; flags step changes not in spec |

SDMetrics diagnostic Data Validity uses KeyUniqueness, BoundaryAdherence, CategoryAdherence. [P] <https://docs.sdv.dev/sdmetrics/data-metrics/diagnostic/diagnostic-report-api.md>

### 3.2 Within-entity / within-session consistency
| Check | Rule | Tag |
|---|---|---|
| Device attribute stability | within a device: `os`, `model` constant; within a session: `user_agent`, `ip` mostly constant | [U] |
| Drift rates | per entity: changes per 30 days for slow attributes (address, IP); compare to declared volatility class | [U] |
| Coupled changes | state/zip/street/IP-geo change together; independent changes are a realism smell | [U]; matches risk noted in `event-simulation-techniques.md` sec. 3 |
| Point-in-time enrichment | attribute value carried on an event equals the dimension timeline value valid at event time (`valid_from <= t < next valid_from`) | [U] |
| Functional dependencies | e.g. `zip -> state`, `device_id -> os` hold with ~100% confidence; FD violations are the cross-row version of these checks | [P] FD definition example `zipcode -> city`: <https://www.vldb.org/pvldb/vol8/p1082-papenbrock.pdf> |

### 3.3 Tracking-plan / event-catalog conformance
Treat the simulation spec's event catalog as a tracking plan and report the same statuses product-analytics tools do:

| Source pattern | Mechanism | Tag |
|---|---|---|
| Snowplow | self-describing JSON Schemas in Iglu; "each event is validated against its schema and only valid events are allowed to pass through"; failures go to a separate location | [P] <https://docs.snowplow.io/docs/fundamentals/schemas/> |
| Segment Protocols | tracking plan, violations reviewed in aggregate or in detail, block non-conforming events into a quarantine source, transformations | [P] <https://www.twilio.com/docs/segment/protocols.md> (segment.com URL returned 403) |
| Amplitude Data (Observe) | statuses Unexpected / Valid / Invalid / Out of Date; "% Seen" indicator for missing required properties; type mismatch indicator; per-source sparklines of invalid volume | [P] <https://amplitude.com/docs/data/validate-events> |
| Avo Inspector | extracts event names, property names and types (not values); reports discrepancies vs plan; value constraints (allowed values, regex, min/max) in Debugger | [P] <https://www.avo.app/docs/inspector/start-using-inspector> |

Report as a coverage table: events in catalog never generated; generated events not in catalog; per property: % seen, % type-valid, % value-valid. [U, synthesis of the above]

---

## 4. Statistical methods for realism

### 4.1 Marginals (per column, per event type)
| Method | Data | Notes | Tag |
|---|---|---|---|
| KS statistic / KSComplement = 1 - max CDF gap | numeric, datetime | SDMetrics score in [0,1]; nulls ignored | [P] <https://docs.sdv.dev/sdmetrics/data-metrics/quality/kscomplement.md> |
| Chi-square, Z-test | categorical | Evidently default for <=1000 rows (p<0.05) | [P] <https://docs.evidentlyai.com/metrics/customize_data_drift> |
| Wasserstein (normed) | numeric | Evidently default >1000 rows, threshold 0.1 | [P] same |
| Jensen-Shannon distance | categorical | Evidently default >1000 rows, threshold 0.1 | [P] same |
| TVD | categorical | TVComplement in SDMetrics; ContingencySimilarity is 1 - TVD on 2-D tables | [P] <https://docs.sdv.dev/sdmetrics/data-metrics/quality/contingencysimilarity.md> |
| Category coverage | categorical | share of reference categories present in synthetic | [U] (page URL found in sitemap, not opened: <https://docs.sdv.dev/sdmetrics/data-metrics/quality/categorycoverage.md>) |

Caveat: with 10^5-10^7 synthetic rows, p-value tests reject almost any tiny difference; use effect sizes (distance with tolerance) for large samples, as Evidently's defaults do. [U, reasoning; consistent with Evidently's size-dependent defaults]

### 4.2 Joint / pairwise
- **CorrelationSimilarity** = 1 - |S - R| / 2 for Pearson or Spearman per pair. [P] <https://docs.sdv.dev/sdmetrics/data-metrics/quality/correlationsimilarity.md>
- **ContingencySimilarity** = 1 - 0.5 * sum |S_ab - R_ab| over normalized contingency tables; numeric columns binned; missing as its own category. [P] <https://docs.sdv.dev/sdmetrics/data-metrics/quality/contingencysimilarity.md>
- Since SDMetrics 0.27.0, Column Pair Trends skips pairs without a strong real pattern (|Pearson| > 0.5 or Cramer's > 0.3). [P] <https://docs.sdv.dev/sdmetrics/data-metrics/quality.md>
- Without a reference, compare the achieved correlation matrix to correlations the spec declares (e.g. amount vs account age), and assert declared independences. [U]

### 4.3 Multivariate distribution tests
| Method | Idea | Source |
|---|---|---|
| MMD | Largest difference in expectations over the unit ball of an RKHS; quadratic-time statistic, linear-time approximations; also applied to graph distributions | [P] Gretton et al., JMLR 2012 <https://jmlr.org/papers/v13/gretton12a.html> |
| C2ST | Label real vs synthetic, train a classifier on a split; accuracy near chance if P = Q; interpretable units, simple null; classifier uncertainty localizes differences | [P] Lopez-Paz & Oquab <https://arxiv.org/abs/1610.06545> |
| pMSE | Stack real and synthetic, fit propensity model, pMSE = mean (p_hat - c)^2 with c = synthetic share; null expectation (k-1)(1-c)^2 c / N, i.e. (k-1)/(8N) for equal sizes | [P] Snoke et al., JRSS-A 2018 <https://academic.oup.com/jrsssa/article/181/3/663/7070840> |
| SDMetrics detection | Single-table detection; sequential version trains an LSTM on real vs synthetic rows, score = 1 - accuracy (Beta) | [P] <https://docs.sdv.dev/sdmetrics/data-metrics/metrics-in-beta/detection-sequential.md> |
| alpha-Precision / beta-Recall / Authenticity | P_alpha = P(synthetic in alpha-support of real); R_beta = P(real in beta-support of synthetic); curves over alpha, beta; integrated IP_alpha = 1 - 2 dP_alpha, equals 1 only if P_g = P_r; per-sample scores allow "auditing" (discard low-fidelity samples) | [P] Alaa et al., ICML 2022 <https://arxiv.org/abs/2102.08921> (PDF text extracted) |
| Density / Coverage | Fixes precision/recall variants that fail on identical distributions, are not outlier-robust, use arbitrary hyperparameters | [P] Naeem et al., ICML 2020 <https://arxiv.org/abs/2002.09797> |
| Improved precision/recall | Non-parametric manifold estimates of real and generated data | [P] Kynkaanniemi et al. 2019 <https://arxiv.org/abs/1904.06991> |
| Implementations | synthcity lists `ks_test`, `chi_squared_test`, `max_mean_discrepancy`, `jensenshannon_dist`, `wasserstein_dist`, `prdc`, `alpha_precision`, detection (`detection_xgb`, ...), performance (`performance.xgb`, ...) | [P] <https://github.com/vanderschaarlab/synthcity> |

For event data, apply multivariate tests on **entity-level feature vectors** (per user: counts by type, amount stats, distinct devices, active days, mean inter-event gap) rather than on raw rows, so behavioral differences become visible. [U, synthesis]

### 4.4 Utility: TSTR / TRTS
- Esteban et al. train on synthetic and test on real, "and vice-versa" (TSTR / TRTS). [P] <https://arxiv.org/abs/1706.02633>
- SDMetrics ML Efficacy (binary) trains on synthetic, tests on real, returns F1 (Beta). [P] <https://docs.sdv.dev/sdmetrics/data-metrics/metrics-in-beta/ml-efficacy-single-table/binary-classification.md>
- Without real data, a TSTR analogue is "oracle vs observable-feature model" on the generator's own labels, as `apps/bench` already does; it tests learnability of the planted signal, not realism. [U, relation to repo]
- Report convention for this repo: whenever TSTR/TRTS models are reported, show **ROC and PR curves side by side**. [user convention, MEMORY.md]

### 4.5 Temporal
| Check | Metric | Tag / source |
|---|---|---|
| Inter-event time | per entity gap distribution; compare to exponential (Poisson) baseline; log-binned histogram | [U] |
| Burstiness | Goh-Barabasi: arXiv v1 defines Delta = sgn(sigma - m) * 1/2 * integral |P(tau) - P_Poisson(tau)| d tau (+1 bursty, 0 Poisson, -1 regular); widely cited closed form B = (sigma - m)/(sigma + m) is from the published version (not verified here) | [P] for Delta and memory coefficient <https://arxiv.org/abs/physics/0610233>; [U] for B formula |
| Memory coefficient | correlation of consecutive inter-event times; authors report human dynamics burstiness comes mainly from the inter-event distribution, memory is weak | [P] same |
| Autocorrelation / seasonality | ACF/PACF of hourly counts; STL decomposition into seasonal, trend, residual (`period`, `seasonal` odd >= 7) | [P] <https://www.statsmodels.org/stable/generated/statsmodels.tsa.seasonal.STL.html>; ydata ts-mode ACF/PACF [P] above |
| Self-excitation | Fit Hawkes (tick: `HawkesExpKern`, `HawkesSumExpKern`, `HawkesEM`, ...) to per-entity streams; compare fitted kernels/baselines to spec | [P] <https://x-datainitiative.github.io/tick/modules/hawkes.html>; branching-ratio interpretation [U] |
| Session structure | session length, events per session, gap threshold sensitivity | [U] |

### 4.6 Heavy tails and concentration
- **Power-law fitting** (Clauset, Shalizi, Newman, SIAM Review 2009): MLE for alpha; xmin chosen as the value that minimizes the KS distance D; goodness-of-fit by semiparametric bootstrap, power law ruled out if p <= 0.1; compare to alternatives (lognormal, exponential, etc.) by normalized log-likelihood ratio (Vuong). [P] <https://arxiv.org/abs/0706.1062> (PDF text extracted)
- `powerlaw` package implements Clauset et al.: `Fit(data)`, `.power_law.alpha`, `.xmin`, `distribution_compare('power_law','lognormal')` -> (R, p). [P] <https://github.com/jeffalstott/powerlaw>
- **Gini / Lorenz / top-k share** for events per user, amount per merchant, volume per token: compare to declared concentration target. [U]
- Practical note: "looks straight on log-log" is not evidence; report the fitted alpha, xmin, bootstrap p, and LR vs lognormal. [P, the paper's thesis per abstract]

### 4.7 Graph metrics
- Degree distribution, clustering, assortativity, reciprocity, triadic census and components (sec. 2.2 table). [P NetworkX URLs above]
- **Graph two-sample**: MMD over graph distributions (Gretton) [P above]; GraphRNN evaluates generated graphs with MMD-based metrics against a target set [P] <https://arxiv.org/abs/1802.08773>; the specific statistics (degree, clustering, orbit counts) are from the paper body, not verified here [U].
- For a single big graph (one synthetic platform), compare **distributions of node-level statistics** (degree, local clustering, component size) with KS/Wasserstein instead of graph-level MMD. [U]

### 4.8 Process-mining conformance
- **Token-based replay fitness** (Rozinat & van der Aalst, Information Systems 2008): f = 1/2 (1 - sum n_i m_i / sum n_i c_i) + 1/2 (1 - sum n_i r_i / sum n_i p_i), with missing m, remaining r, consumed c, produced p tokens per trace variant i weighted by count n_i; 0 <= f <= 1. Paper also defines structural/behavioral appropriateness. [P] <https://vdaalst.com/publications/p436.pdf> (PDF text extracted)
- **Alignments** (Adriansyah, van Dongen, van der Aalst, EDOC 2011): cost-based fitness, diagnostics as skipped/inserted activities, A*-based. [U, search snippets only] <https://www.vdaalst.com/publications/p630.pdf>
- PM4Py: `fitness_token_based_replay`, `precision_token_based_replay`, `fitness_alignments`, `precision_alignments`, `conformance_declare`, `conformance_log_skeleton`, `conformance_temporal_profile`. [P] <https://raw.githubusercontent.com/process-intelligence-solutions/pm4py/release/pm4py/__init__.py>
- Use: write the spec's allowed journeys as a model (Petri net / Declare / log skeleton); replay the synthetic log; fitness < 1 lists exactly which traces violate. Precision < 1 means the model allows much more than the data shows (spec branches never exercised). [U, application]
- Reverse use: discover a DFG from a real reference log (if any) and replay the synthetic log on it, and vice versa. [U]

### 4.9 Domain stylized facts (reference-free realism)
| Domain | Stylized facts to test | Tag |
|---|---|---|
| Trading | Cont's 11 facts: absence of linear autocorrelation, heavy tails, gain/loss asymmetry, aggregational Gaussianity, intermittency, volatility clustering, conditional heavy tails, slow decay of ACF of absolute returns, leverage effect, volume-volatility correlation, timescale asymmetry. A 2024 re-test on Dow 30 intraday data supported 8, not gain/loss asymmetry, leverage, timescale asymmetry; volume-volatility only in clock time | [P] list via Ratliff-Crain et al. <https://arxiv.org/html/2311.07738v2>; Cont 2001 original (Quant. Finance 1(2):223-236) not fetched (403) [U] |
| Payments | heavy-tailed amounts, round-number spikes, diurnal/weekly and payday cycles, merchant concentration, small refund/chargeback rates lagged after purchase | [U] |
| E-commerce | funnel attrition (view >> cart >> checkout), session burstiness, repeat purchase heavy tail, category seasonality | [U] |
| SNS | heavy-tailed follower degree, reciprocity, clustering, bursty posting, cascade size heavy tail | [U] |
| L1 chain | block-time regularity, gas price/fee spikes, address activity heavy tail, nonce strictly increasing per sender, conservation of value per tx | [U] |

---

## 5. Inconsistency detection without a reference

### 5.1 Invariant catalog (each returns failing rows; 0 = pass)
| Invariant | Rule (example) | Tag |
|---|---|---|
| Primary key | `event_id` unique; entity ids unique per entity table | [P] dbt `unique` <https://docs.getdbt.com/docs/build/data-tests>; datagen export already refuses duplicate `event_id` (repo) |
| Referential integrity | every `user_id`/`device_id` in events exists in entities; created before the event | [P] dbt `relationships` same URL; simkit `resolve_reference` requires targets to predate rows (repo) |
| Monotonic time per entity | sequence number / nonce strictly increasing with time per account | [U] |
| Precedence | `first(add_card) > first(signup)`; `refund` only after a `purchase` of the same order | [U] |
| Lifecycle validity | status transitions in allowed set (order: created -> paid -> shipped -> delivered/returned) | [U] |
| Conservation | per account: opening + credits - debits = closing; per tx: sum of legs = 0; chain: inputs = outputs + fee | [U] |
| Sign / range rules | amounts > 0 for purchases, < 0 for refunds; fee <= amount; quantity integer | [P] Deequ `isNonNegative`, GE `expect_column_values_to_be_between` (URLs in 1.2) |
| Cross-field | country vs IP geo vs currency vs phone prefix consistency (allow a declared mismatch rate for VPN/travel) | [U] |
| Duplicate detection | exact duplicates on all columns except id; near-duplicates (same user, type, amount within 1s) | [P] ydata duplicate rows; [U] near-dup rule |
| Time travel / leakage | features or labels computed using events at or after t; label known before it could be known; golden columns absent from events | [P] repo `export` and `bench.runner` leak guards; general rule [U] |
| Span bounds | all event times within configured span; no event before its entity's creation | [U] |

### 5.2 Constraint discovery and violation detection
- **Functional dependencies** (X -> A): Papenbrock et al. evaluated seven FD discovery algorithms (TANE, FUN, FD_Mine, DFD, Dep-Miner, FastFDs, FDEP; implemented in the Metanome framework) and found "all current approaches scale surprisingly poorly"; FD discovery remains open. [P] <https://www.vldb.org/pvldb/vol8/p1082-papenbrock.pdf> (PDF text extracted)
- **Denial constraints** (Chu, Ilyas, Papotti, VLDB 2013): more expressive than FDs/CFDs (e.g. "an American citizen cannot have lower salary and higher tax rate than another citizen in the same state"); instance-driven discovery with a scoring function to rank DCs for user validation. [P] <https://www.vldb.org/pvldb/vol6/p1498-papotti.pdf>
- **HoloClean**: holistic repair combining integrity constraints / external data with statistical signals via probabilistic inference, scaling to millions of tuples. [P] <https://arxiv.org/abs/1702.00820>
- Use on synthetic data [U, synthesis]: (1) discover approximate FDs/DCs on the synthetic output; (2) diff against the spec's intended dependencies; a discovered dependency that the spec did not intend is often a generator artifact (e.g. `amount -> label`), and an intended one that is missing is a coherence bug.

### 5.3 Temporal logic over sequences
- LTL on finite traces (LTLf) is used to specify business processes and plan constraints; LDLf adds expressiveness at the same PSPACE-complete cost. [P] De Giacomo & Vardi, IJCAI 2013 <https://www.ijcai.org/Proceedings/13/Papers/132.pdf>
- Practical encodings [U]: Declare templates (`response(a,b)`, `precedence(a,b)`, `not_coexistence`) via PM4Py `discover_declare`/`conformance_declare` [P names, URL in 4.8]; or regex over a per-case string of event-type codes (e.g. forbid `^[^S]*C` = card before signup), cheap in Polars/DuckDB.
- Timed rules (e.g. `otp_verify` within 5 min of `otp_send`) need metric-time checks; PM4Py temporal profile (mean/std of time between activity pairs) flags deviations. [P name; semantics U]

### 5.4 Anomaly detection as a self-check
- Run an unsupervised detector (Isolation Forest: anomalies need fewer random splits; Liu, Ting, Zhou ICDM 2008) over entity-level feature vectors; inspect the top anomalies by hand. Many will be generator bugs (impossible combos), some will be planted fraud. [P] <https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.IsolationForest.html>; usage [U]
- Track the share of planted-positive entities among top anomalies: if planted fraud is trivially the most anomalous thing, the scenario may be too easy. [U]
- Alaa et al.'s per-sample alpha-precision supports the same "audit and discard" workflow when a reference exists. [P] <https://arxiv.org/abs/2102.08921>

---

## 6. Recommended inspector for this repo

### 6.1 Inputs and outputs
- Inputs: `events.parquet` (wide events with entity attributes joined and `label`), `meta.json` (seed, scenario, config, `golden_columns`, achieved bad rate), optional entity tables / attribute timelines, optional `reference_stats.json` (real-data summaries or spec targets), optional spec file. [repo: `libs/simkit/src/neorisk_simkit/export.py`, `apps/datagen/README.md`]
- Note: current datagen output is `events.parquet` + `golden.parquet` + `meta.json`; separate entity Parquet files are not written today, so entity-level checks must reconstruct entities from event columns until they are exported. [repo, read-only]
- Output: single self-contained HTML (+ JSON of all metrics and violations), same style as `apps/bench` reports. [U, design]
- Guard: do not open `golden.parquet` in the realism sections (mirrors bench's guard); an optional, clearly labeled "planted-signal oracle" section may read it. [repo `apps/bench/README.md`; design U]

### 6.2 Report layout
```
Synthetic Data Inspection: <scenario> seed=<s>          [scorecard badge: PASS / WARN / FAIL]
1. Overview         counts by event type & entity, span, events/day, hour x weekday heatmap, label rate over time
2. Event catalog    catalog coverage table (unexpected / missing / invalid events)
   2.x per event    attribute table: fill %, expected?, type-valid %, cardinality, top-k / histogram, drift sparkline
3. Transitions      DFG (top-k edges), transition heatmap with forbidden cells, funnel/Sankey, variants, path lengths
4. Linkage          degree CCDFs (users/device, users/IP, invites/inviter), components, clustering, assortativity, ring candidates
5. Temporal         inter-event gap CCDF vs exponential, burstiness, ACF of hourly counts, STL panel, session stats
6. Distributions    per target: achieved vs target with tolerance band; marginal distances; correlation/contingency diffs; C2ST/MMD if reference
7. Invariants       one row per rule: violations, rate, 5 example ids, severity
8. Scorecard        weighted roll-up; hard-fail list; soft-score table; diff vs previous run
(9. Utility/oracle) only if TSTR or oracle models are reported: ROC and PR side by side
```

### 6.3 Metric per section
| Section | Headline metric | Pass rule (default) |
|---|---|---|
| Overview | event-type share vs target; empty-day count | share within +-20% rel.; 0 empty days unless declared [U] |
| Catalog | % events valid against catalog; % required props seen | 100% / 100% (hard) [U] |
| Per-event attrs | fill-rate deviation, type-valid %, FD confidence | type-valid 100% (hard); fill within tolerance [U] |
| Transitions | forbidden-edge count; token-replay fitness; funnel ratios | 0 forbidden; fitness = 1.0 on legality model; funnel within tolerance [U] |
| Linkage | degree-dist KS vs target; max degree vs cap; ring sizes | caps hard; KS soft [U] |
| Temporal | burstiness vs target; diurnal amplitude; ACF at 24h/168h | soft [U] |
| Distributions | KSComplement / TVComplement / CorrelationSimilarity / C2ST AUC | e.g. >=0.9 / >=0.9 / >=0.9 / AUC <= 0.6 soft [U] |
| Invariants | violations per rule | 0 (hard) except rules with declared tolerated rate [U] |

### 6.4 Config-declared targets become checks
A spec (YAML or Python, whatever the simulator uses) should carry an `expect:` block next to the knobs; the inspector compiles each entry into a check. [U, design]

```yaml
expect:
  events.share: {purchase: 0.40 +-0.05, login: 0.35 +-0.05}
  users.events_per_user: {dist: powerlaw, alpha: 2.3 +-0.3, xmin_max: 10}
  users.top1pct_share.events: 0.25 +-0.05
  transitions.forbidden: [[START, add_card], [refund, signup]]
  transitions.precedence: [[signup, add_card], [purchase, refund]]
  funnel: {view->cart: 0.10 +-0.03, cart->checkout: 0.40 +-0.1}
  device.users_per_device.max: 8
  temporal.burstiness.user: 0.3 +-0.15
  temporal.diurnal.peak_hour: 20 +-2
  attr.fd: [[user_zip, user_state]]
  invariants: [ledger_conservation, nonce_monotonic, ip_geo_matches_country: {tolerated: 0.03}]
  label.rate: 0.02 +-0.002
```

Compilation rules [U]: point targets with `+-` -> tolerance check; `dist:` -> Clauset fit and LR test; lists of pairs -> transition/precedence queries; named invariants -> registered rule functions returning failing rows. Every target is echoed in the report as achieved vs target, so the agent and the human see the same scoreboard. `meta.json` should also record achieved values (today it records only achieved bad rate). [repo: export writes `bad_rate`; rest U]

### 6.5 Pipeline
1. Load and type-check (Pandera/Polars schema from catalog). [P Pandera above; wiring U]
2. Hard invariants (sec. 5.1) as Polars/DuckDB queries; stop early on FAIL but still render the report. [U]
3. Profiles per event type and per entity aggregate. [U]
4. Sequence build per case -> DFG, variants, conformance. [U]
5. Graph build -> linkage metrics. [U]
6. Temporal and heavy-tail fits. [U]
7. Targets and reference comparisons -> scorecard. [U]
8. Render HTML + JSON; store JSON for run-to-run diffs (Deequ-style metrics repository). [U]

### 6.6 Relation to apps/datagen and apps/bench (read-only)
| Existing piece | What it already checks | Gap the inspector fills |
|---|---|---|
| `simkit.export` | required columns, non-empty, label not all null, unique `event_id` in events and golden, golden columns absent from events, identical event_id sets; writes `meta.json` with `golden_columns`, `n_events`, `bad_rate` | No distribution, sequence, graph or temporal checks; no achieved-vs-target stats beyond bad rate |
| `simkit.references.resolve_reference` | referenced entity must predate the row (raises otherwise) | Not reported as a metric; no fan-out caps |
| `bench.runner` / `compare` | fails fast if golden columns leak into events; reports ROC/PR side by side, calibration, SHAP | Bench is model-centric; no data-realism report |
| `bench.datagen_section` | static description of attributes/behaviors (mirrors scenario code) | Describes intent, not achieved data; the inspector shows achieved values next to it |
| `bench temporal` / `curves` | label maturity, leakage experiments | Inspector's leakage invariant is the data-side counterpart |

Sources: `libs/simkit/src/neorisk_simkit/export.py`, `libs/simkit/src/neorisk_simkit/references.py`, `apps/bench/src/bench/runner.py`, `apps/bench/README.md`, `apps/bench/src/bench/datagen_section.py`, `apps/datagen/README.md` (read, not modified).

Natural home: a `bench inspect DATA_DIR --out inspect.html [--targets spec.yaml] [--reference ref.json]` subcommand, or a small `apps/inspect`, reusing bench's HTML helpers. [U, suggestion]

---

## 7. Open questions and risks

| Risk | Detail | Mitigation (all [U]) |
|---|---|---|
| Overfitting to metrics | Metrics check 1-2 dimensional patterns; SDMetrics says scores are aspirational and not ROI [P] <https://docs.sdv.dev/sdmetrics/data-metrics/quality.md> | Keep held-out checks the agent never sees; include C2ST on entity features, which is hard to game column by column |
| Metric gaming by the generating agent | An agent that sees the scorecard can tune knobs to hit targets with implausible mechanisms (e.g. hit the funnel by deleting users) | Separate author and judge; hide part of the suite; require invariants to pass before scores count; review top anomalies manually |
| No real data | Targets come from the spec author; realism = consistency with the author's beliefs + literature stylized facts | Cite sources for targets in the spec; prefer published stylized facts; mark each target "sourced" or "assumed" in the report |
| Large-n significance | p-values meaningless at 10^6 rows | Use effect sizes and tolerance bands (Evidently's size-dependent defaults are a precedent [P] above) |
| Level of aggregation | Row-level tests miss behavioral nonsense; entity-level tests miss row-level coherence | Run both; the report has per-row, per-entity, per-sequence and per-graph sections |
| Planted signal too easy / too hard | Planted fraud may be trivially separable (artifacts) or invisible | Anomaly self-check and oracle vs observable models (bench) |
| Privacy | Not the focus; matters only if a real reference was used to fit the generator (authenticity, nearest-neighbor distance) | Alaa authenticity, synthcity privacy metrics [P] URLs above |
| Tool fit | Pandera on Polars lacks groupby checks and hypothesis tests [P]; GE `increasing` is global | Write per-entity rules as Polars/DuckDB queries returning failing rows |
| Cost | Alignments and FD/DC discovery scale poorly (FD paper) [P] | Sample cases; use DFG/regex rules first, alignments only on samples |

---

## Claims lacking primary sources (summary)

- All design items in sec. 1.1, 1.3, 2.1 checks, 2.2 sanity rules, 3.1-3.3 synthesized tables, 4.9 non-trading domain facts, 5.1 most invariants, 6.2-6.5 report/pipeline/`expect:` design, and default pass thresholds are synthesis [U].
- Burstiness closed form B = (sigma - m)/(sigma + m): only the arXiv v1 Delta definition and memory coefficient were read; B is from the published EPL version (not fetched).
- Cont 2001 original paper: 403; the list of 11 facts is from Ratliff-Crain et al. 2024 (fetched).
- Alignments (Adriansyah et al. 2011): only search snippets.
- GraphRNN's specific MMD statistics (degree, clustering, orbits): abstract only.
- Hawkes branching-ratio interpretation: tick docs do not mention it.
- SDMetrics CategoryCoverage and TVComplement pages: URLs found in sitemap, not opened.
- Segment Protocols: segment.com returned 403; used twilio.com docs mirror.
- PM4Py temporal-profile semantics and LTL checker: function names confirmed in `__init__.py`, behavior not documented on fetched pages; no LTL-named function found.
- NetworkX `connected_components` function name not shown on the index page (Components section is).
- Effect-size-over-p-value advice for large n: reasoning, not a cited source.
