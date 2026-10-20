# Programmable, Multi-Domain Event Simulation and the Role of LLM Agents

Compiled 2026-10-15. Each claim carries a URL. Tags: **[P]** = traced to a primary source fetched during this research (paper abstract/HTML, official docs, repo README); **[U]** = unverified (general knowledge, search-snippet only, a page that failed to load, or design synthesis; treat as unconfirmed). Builds on `event-simulation-techniques.md` (techniques for behavioral validity, attribute dynamics, linkage graphs, calibration, reproducibility) and `event-based-systems.md`; those topics are referenced, not repeated.

Question: how to build an event simulator that is deeply configurable/programmable, and how 2023-2026 LLM-agent work can help define behavior, so one engine can serve e-commerce, a centralized crypto exchange (CEX), a layer-one (L1) blockchain, a social network (SNS), and a payment system.

---

## 0. Short answer

- Use a **layered model** (event catalog, entities, journeys/state machines, attribute dynamics, graph, calendar, scenario injection, run config). Each layer gets a **declarative config validated against a schema**, plus **typed Python escape hatches** (plugins) where a declarative form runs out of expressiveness. This is the pattern shared by AMLSim (JSON + CSV parameter files), PaySim (properties + CSV), k6 (options object + JS functions), and Locust (plain Python). See sec. 1. [U, synthesis of sources in sec. 1]
- Use LLMs mainly at **authoring time**, as a compiler from a business description to a config/event catalog/state machine that is schema-validated, reviewed, pinned, and then run by a cheap, seeded, deterministic engine. LLM-in-the-loop per agent step costs on the order of thousands of input tokens per agent action (OASIS reference: ~3.4k input tokens per active agent-step) and is not reproducible run-to-run, so it is unsuitable as the default path for millions of events. Middle ground: **LLM archetypes** (one LLM query per persona-group, sampled per agent), as in AgentTorch's 8.4M-agent run that used ~400 queries. See secs. 2-3. [P for numbers; U for the recommendation]
- Each domain ships as a **domain pack**: a catalog of event schemas taken from a public standard (GA4 e-commerce events, Binance-style order/trade enums, Ethereum JSON-RPC objects, ActivityPub activities, Stripe/ISO 20022 payment lifecycles), lifecycle state machines, default distributions tied to published stylized facts, and scenario templates (fraud, incidents). See sec. 4.
- The current repo (`libs/simkit` + `apps/datagen`) already has the right core: seeded determinism, point-in-time attribute timelines, reference columns, planted-signal labels, Python scenarios. It lacks an event catalog, a journey layer, a declarative config surface, and a domain-pack interface. See sec. 5.

---

## 1. Configurability and programmability spectrum

### 1.1 The spectrum

| Level | Form | Strength | Weakness | Examples (sec. 1.2) |
|---|---|---|---|---|
| L1 Declarative parameters | Key-value / properties, flat JSON | Easy diff, easy to validate, easy for non-coders and LLMs to emit | Only knobs the author foresaw | PaySim `.properties`, AMLSim `conf.json` |
| L2 Declarative structure | Schemas + tables (CSV/JSON/YAML) describing entities, relations, patterns | Expresses structure (tables, relations, typologies) without code | Logic (conditions, loops) is awkward | SDV metadata, AMLSim parameter CSVs, tracking plans, OTel registries, BPMN XML |
| L3 DSL | Embedded or external mini-language for journeys | Readable control flow: loops, branches, pauses, weighted choices | Learning curve; limited to what the DSL offers | Gatling scenario DSL, k6 scenarios/executors, NetLogo |
| L4 Code-as-config | Ordinary modules/classes in a general language | Unlimited expressiveness, testable, reusable libraries | Harder to validate statically, harder to diff semantically, needs a programmer | Locust locustfiles, Mesa models, Concordia prefabs, this repo's scenarios |
| L5 Plugins | Registered extension points (providers, handlers, components) inside L1-L4 | Add new behavior without forking the engine | Need stable interfaces and versioning | Mimesis/Faker providers, Concordia components, OTel Weaver templates |

Synthesis: real systems mix levels; the useful question per layer is which level is the default and which is the escape hatch. [U]

### 1.2 Concrete systems and their configuration models

| System | What it configures | Config model | Source |
|---|---|---|---|
| SDV metadata | Tables, columns with `sdtype` (id, categorical, numerical, datetime, email...), primary keys, parent/child `relationships`; JSON with `METADATA_SPEC_VERSION`; auto-detect from dataframes, `validate()`, `save_to_json()` | L2 JSON | [P] <https://docs.sdv.dev/sdv/concepts/metadata> |
| Mimesis | `Field("person.name")`, `Fieldset`, `Schema(schema=callable, iterations=N)`; per-record `.map()` transforms with a context carrying seed; custom handlers registered by name; seeds passed to constructors; CSV/JSON/pickle export; `SchemaBuilder` for foreign-key data | L4 + L5 handlers | [P] <https://mimesis.name/master/schema.html> |
| Faker | Generators grouped into providers; seedable; same output only for same Faker version | L5 providers | [P] <https://faker.readthedocs.io/en/master/> |
| PaySim | `PaySim.properties`: `seed`, `nbSteps=720`, `nbClients=20000`, `nbFraudsters=1000`, `nbMerchants`, `fraudProbability=0.001`, `transferLimit`, plus paths to CSVs: `transactionsTypes`, `aggregatedTransactions`, `clientsProfiles`, `initialBalancesDistribution`, `overdraftLimits`, `maxOccurrencesPerClient`, `typologiesFolder` | L1 properties pointing at L2 CSVs | [P] <https://raw.githubusercontent.com/EdgarLopezPhD/PaySim/master/PaySim.properties> (raw file fetched; GitHub HTML view timed out) |
| AMLSim | `conf.json` (`input`/`general`/`output`, `random_seed`, `total_steps`) + CSVs for accounts, degree distribution, alert patterns (typology type, count, size, amount, period, schedule, `is_sar`) | L1 + L2 | [P] <https://github.com/IBM/AMLSim>, <https://github.com/IBM/AMLSim/wiki/Data-Schema-for-Input-Parameters-and-Generated-Data-Set> (see also techniques doc sec. 4A) |
| Snowplow schemas | Self-describing JSON Schema (draft 4) with a `self` block (`vendor`, `name`, `format`, `version` like `1-0-0`); stored in an Iglu registry (`iglu:com.acme/viewed_product/jsonschema/1-0-0`); events vs entities (contexts) attached to events; invalid events routed to a failed-events location | L2 event catalog with versioning | [P] <https://docs.snowplow.io/docs/fundamentals/schemas/> |
| Segment Protocols tracking plan | Expected events and properties per source; property type, required/optional, regex-permitted values; per-event and common JSON Schema; violations on mismatch; event versions via `context.protocols.event_version`; CSV import/export (limits 15 MB / 100k rows / 2,000 rules) | L2 event catalog | [P] <https://www.twilio.com/docs/segment/protocols/tracking-plan/create> (segment.com URL returned 403; Twilio-hosted copy fetched) |
| JSON Schema | "Declarative language for defining structure and constraints for JSON data"; current version 2020-12; needs a separate validator | L2 schema language | [P] <https://json-schema.org/overview/what-is-jsonschema> |
| OpenTelemetry semantic conventions | Names, types, meanings, valid values of attributes; span names/kinds; metric instruments/units; across traces, metrics, logs, events, resources | L2 attribute registry | [P] <https://opentelemetry.io/docs/specs/semconv/> |
| OTel Weaver | Registries defined in YAML; validate, resolve, diff versions; generate code/docs from templates; live-check an OTLP stream against a registry; **emit example telemetry from a registry**; MCP server for LLM integration | L2 registry + L5 templates | [P] <https://github.com/open-telemetry/weaver> |
| Avo Codegen | Tracking plan -> generated type-safe tracking functions (e.g. `Avo.gameStarted()`), routes to destinations (GA4, Segment, Mixpanel) | Tracking-plan-as-code | [P] <https://www.avo.app/docs/implementation/avo-codegen-overview> |
| Amplitude Ampli | Tracking plan in Amplitude Data -> generated typed wrapper (`ampli.songPlayed()`); `ampli pull` downloads it, `ampli status` reports unimplemented events | Tracking-plan-as-code | [P] <https://amplitude.com/docs/sdks/ampli>; relation to Iteratively not stated on page [U] |
| BPMN 2.0 | OMG standard for process diagrams, "precise enough to allow BPMN diagrams to be translated into software process components"; normative XML Schemas (BPMN20.xsd); 2.0.1 successor | L2 process model | [P] <https://www.omg.org/spec/BPMN/2.0/About-BPMN> |
| Petri nets | Places/transitions/tokens; enabled transitions fire atomically; coloured (typed tokens with guards), timed, stochastic (exponential timing, reachability graph as CTMC) variants | L2 formal process model | [P] <https://en.wikipedia.org/wiki/Petri_net> |
| Mesa | `mesa.Model`/`mesa.Agent` subclasses with `step()`; AgentSet `do`/`shuffle_do`; `schedule_event`, `schedule_recurring`; `batch_run(Model, parameters, rng=[seeds], ...)` | L4 code | [P] <https://mesa.readthedocs.io/stable/overview.html> |
| NetLogo BehaviorSpace | Parameter sweeps over sliders/globals (lists or ranges), subexperiments, repetitions; reproducibility via fixed seed or seed from `behaviorspace-run-number`; table/spreadsheet output; headless runs | L3 DSL + L2 experiment spec | [P] <https://docs.netlogo.org/behaviorspace.html> |
| Locust | Users are Python classes; `@task(weight)` methods picked at random; `wait_time` (`between`, `constant_pacing`, `poisson`...); locustfile is an ordinary Python module | L4 code-as-config, weighted journeys | [P] <https://docs.locust.io/en/stable/writing-a-locustfile.html> |
| k6 | `options.scenarios` each with an `executor` (shared-iterations, per-vu-iterations, constant-vus, ramping-vus, constant-arrival-rate, ramping-arrival-rate), `startTime`, `exec` function | L1 options + L4 JS functions | [P] <https://grafana.com/docs/k6/latest/using-k6/scenarios/> |
| Gatling | Scenario DSL (Java/JS/Kotlin/Scala): `exec`, `pause`, `pace`, loops (`repeat`, `during`, `asLongAs`), `doIf`, `randomSwitch` (percentages), `roundRobinSwitch`, `tryMax`, `group`; injection profiles: open (`constantUsersPerSec`, `rampUsersPerSec`) vs closed (`constantConcurrentUsers`) | L3 embedded DSL | [P] <https://docs.gatling.io/concepts/scenario/>, <https://docs.gatling.io/concepts/injection/> |
| ABIDES (markets) | Python config builders (`rmsc04.build_config(seed=0, end_time=...)`), agent mix (rmsc04: 1 exchange, 2 market makers, 102 value, 12 momentum, 1,000 noise agents); CLI overrides; Gym wrapper | L4 config builder | [P] <https://github.com/jpmorganchase/abides-jpmc-public> |
| Y Social | Admin panel sets agent demographics, personality, activity hours, action-frequency distribution (Uniform/Poisson/Geometric/Zipf), recommender (10 options), follow recommender (5 options), LLM backend per population | L1 GUI parameters | [P] <https://github.com/YSocialTwin/YSocial> |

### 1.3 Lessons from the comparison

- **Tracking plans are ready-made event catalogs.** Segment/Snowplow/Avo/Ampli already encode event names, property types, required flags, enums/regex, and versions, and validate live events against them. A simulator that consumes a tracking plan (or emits one) gets a schema contract for free and can be validated with the same tooling as production. [P for the tool features above; U for the reuse argument]
- **OTel Weaver is the closest existing "registry -> emitter" loop**: a YAML registry that is validated, diffed, used to generate code, and used to emit example telemetry and live-check streams. A simulator event catalog can follow the same lifecycle. [P] <https://github.com/open-telemetry/weaver>; [U for the analogy]
- **Load-testing tools are journey programmers**: weighted task choice (Locust `@task(3)`), think-time distributions (Locust `poisson`), percentage branching (Gatling `randomSwitch`), and the open-vs-closed workload distinction (arrival rate vs concurrent users in Gatling/k6) map directly onto user-journey simulation. Open (arrival-rate) models are the correct default for business events, where arrivals do not wait for others to finish. [P for features; U for the mapping]
- **Simulators split scalar knobs from structural tables**: PaySim and AMLSim both keep a small top-level file of scalars plus CSV tables for distributions/typologies. That split keeps the top level reviewable and lets tables be swapped (e.g., calibrated from real aggregates). [P for both formats; U for the generalization]
- **Formal process models (BPMN, Petri nets) give precedence and concurrency for free** (a transition fires only when its input places are marked), and coloured/stochastic variants add typed data and random timing. They are heavier than needed for most journeys but useful as an export target and for verification (reachability). [P for Petri net semantics; U for the recommendation]
- **Code-as-config wins when behavior is conditional on state** (Locust, Mesa, Concordia, this repo). The cost is weaker static validation, which is why a schema-validated declarative layer on top is valuable. [U]

### 1.4 What a good layered design looks like

Design synthesis [U] unless a row cites a source. Each layer has a declarative default and a code escape hatch.

| # | Layer | Declares | Default form | Escape hatch | Borrowed from |
|---|---|---|---|---|---|
| 1 | Event schema / catalog | Event types, properties, types, enums, required, version, which entities each event references | JSON Schema per event (self-describing, versioned) | Custom property generators (provider plugin) | Snowplow, Segment, OTel registry [P links in 1.2] |
| 2 | Entity model | Entity types, ID namespaces, counts/arrival, attributes with cardinality x volatility | YAML/JSON table | Custom attribute samplers | SDV metadata [P]; repo `EntitySpec`/`AttrSpec` |
| 3 | Journey / state machine | States, allowed transitions with weights, guards on entity state, delays between steps, which event each transition emits | YAML state machine (or BPMN/Petri import) | Python policy class per actor | Gatling DSL, Locust tasks, Petri nets [P] |
| 4 | Attribute dynamics | How attributes change over time (static, Poisson redraw, random walk/OU, coupled change groups) | Declarative per attribute | Custom process | techniques doc sec. 3 |
| 5 | Graph / linkage | Relations, generator (BA, SBM, configuration model, degree list), caps, concentration targets | Declarative per relation | Custom chooser | AMLSim degree/typology files [P]; techniques doc sec. 4A |
| 6 | Calendar / time | Span, diurnal/weekly intensity, holidays/events, burstiness (Hawkes), domain clocks (block slots, settlement cycles) | Declarative curves | Custom intensity function | OASIS 24-hour activity vector [P] <https://arxiv.org/html/2411.11581> |
| 7 | Scenario / injection | Fraud typologies, incidents (outage, price shock, airdrop), labels and decoys, signal strength | Declarative typology rows | Python scenario module | AMLSim `alertPatterns` [P]; PaySim `typologiesFolder` [P] |
| 8 | Run config | Seed, sizes, output sinks/formats, versions, validation thresholds | Small YAML/CLI | n/a | PaySim/AMLSim top-level files [P] |
| 9 | Validation / report | Achieved statistics vs targets, schema conformance, planted-signal verification | Generated report | Custom checks | AMLSim `validate_alerts.py` [P]; Weaver live-check [P] |

Rules that keep layers composable [U]:
- Events reference entities by ID only; attributes are joined point-in-time, not copied at generation (repo already does this via `attach_asof`).
- Each layer draws from its own RNG stream derived from the root seed, so editing one layer does not perturb others (techniques doc sec. 4A.7).
- Layers are validated independently (schema) and jointly (cross-references: every event's referenced entity type exists; every journey emits only cataloged events).

---

## 2. LLM agents for defining behavior (2023-2026)

### 2.1 System survey

| System | What it simulates | Scale | Cost / compute (as reported) | Determinism / reproducibility | How behavior is specified | Source |
|---|---|---|---|---|---|---|
| Generative Agents (Park et al. 2023) | Sims-like town; daily routines, conversations, emergent coordination (Valentine's party) | 25 agents, 2 game days | "thousands of dollars in token credits and taking multiple days to complete" | Not addressed; limitations: hallucinated embellishments, memory retrieval failures, overly formal and overly cooperative agents attributed to instruction tuning | Natural-language seed identity per agent; memory stream + reflection + planning | [P] <https://arxiv.org/abs/2304.03442>, <https://ar5iv.labs.arxiv.org/html/2304.03442> |
| 1,000-person simulation (Park et al. 2024) | Attitudes/behavior of specific real individuals | 1,052 people | Not stated on abstract | Accuracy normalized by human test-retest: interview agents 83%, survey 82%, combined 86%, demographics-only 74% on GSS | Two-hour interview transcripts and/or survey answers as agent memory | [P] <https://arxiv.org/abs/2411.10109> |
| OASIS (CAMEL-AI) | X- and Reddit-like platforms with recommender (interest-based, hot-score) | Up to 1M agents | 196 core + 1M regular agents, 60 steps: 24 A100s for ~1 week; Reddit at 10k agents ~15 min/step on 4 A100s; README: 100 agents x 1 step at activation 1 ~335.6k input + 16.75k output tokens (Qwen-turbo) | No seed/determinism discussion in README | 21 actions in paper (23 in README): sign up, post, repost, like, dislike, comment, follow, mute, search, trend, refresh, do nothing; JSON user profiles; 24-dim hourly activity vector; step = 3 min; 1M profiles generated by LLM from 196 real core users | [P] <https://arxiv.org/abs/2411.11581>, <https://arxiv.org/html/2411.11581>, <https://github.com/camel-ai/oasis> |
| AgentSociety | Urban/social life; polarization, inflammatory messages, UBI, hurricane shock, sustainability | >10k agents, ~5M interactions | Not on abstract; v2 runs agents as Ray tasks | Replay via catalog-driven JSONL + DuckDB traces; no seed control described | Python agent specs (`PersonAgent`), environment modules, reasoning routers (ReAct, Plan-Execute...) | [P] <https://arxiv.org/abs/2502.08691>, <https://github.com/tsinghua-fib-lab/AgentSociety> |
| Y Social | "Digital twin" of a social platform | Not stated | Self-hosted LLMs via Ollama/vLLM | Not stated | Admin-panel parameters: demographics, personality, toxicity, interests, activity hours, action-frequency distributions; 10 content and 5 follow recommenders; RSS news injection | [P] <https://arxiv.org/abs/2408.00818>, <https://github.com/YSocialTwin/YSocial> |
| RecAgent (User Behavior Simulation, Wang et al.) | Users browsing a recommender plus chatting/broadcasting in a social network | 5-50 agents in experiments; efficiency test to 500 | ~220 s/round for 10 agents, ~1.9 h/round for 100 agents (one API key); ~$0.25/round for 10 agents with ChatGPT, roughly linear | Limitations: discrete rounds, prompts "may not be robust for different LLMs" | Profile (age, traits, career, interests, behavior type Watcher/Explorer/Critic/Chatter/Poster) handcrafted, GPT-generated, or aligned to real data; 3-tier memory | [P] <https://arxiv.org/abs/2306.02552>, <https://arxiv.org/html/2306.02552v3> |
| Agent4Rec | Recommender users (page-by-page browsing, rating, exiting) | Not on abstract | Not stated | Not stated | Profiles initialized from MovieLens, Steam, Amazon-Book; factual + emotional memory | [P] <https://arxiv.org/abs/2310.10108> |
| RecSim (non-LLM baseline) | Configurable recommender environments: user preferences, latent state dynamics, choice models | n/a | n/a | Code-defined, seedable (TF) | Python/TF environment components; repo archived Apr 2026 | [P] <https://arxiv.org/abs/1909.04847>, <https://github.com/google-research/recsim> |
| WebShop | Shopping web environment for agents (search, customize, purchase) | 1.18M real products, 12,087 instructions, 1,600+ human demos | n/a | Benchmark (task success: humans 59%, best model 29%) | Goal instructions; it benchmarks shopping agents rather than generating realistic traffic | [P] <https://arxiv.org/abs/2207.01206> |
| TradingAgents | Trading firm roles: analysts, bull/bear researchers, traders, risk team | Single-ticker decisions | Not stated | README: LLM output non-deterministic even at fixed temperature; live news changes; lower temperature helps only on non-reasoning models | Role prompts; `default_config.py` (deep/quick model, debate rounds, temperature) | [P] <https://arxiv.org/abs/2412.20138>, <https://github.com/TauricResearch/TradingAgents> |
| StockAgent | Investors trading 2 stocks with loans, BBS posts, external factors (rates, news) | 200 agents; 10-264 trading days (inconsistent across sections) | Not reported | Tested only gpt-3.5-turbo-0125 and Gemini-pro-1.0; results model-specific | Randomly assigned personality (Conservative/Aggressive/Balanced/Growth) + random capital/debt | [P] <https://arxiv.org/html/2407.18957v3>; findings summary [U] via search snippet |
| LLM market sim (Lopez-Lira 2025) | LLM traders on a persistent order book (market/limit orders, partial fills, dividends) | Not on snippet | Not stated | Not stated | Assigned strategies (value, momentum, market maker); decisions via structured outputs/function calls | [U] search snippet of <https://arxiv.org/abs/2504.10789> (abstract not fetched) |
| Concordia (DeepMind) | Generative ABMs in physical/social/digital settings; synthetic data and evaluation of digital services | Library | Needs an LLM + embedder | Not addressed on README | Entities built from components (memory, instructions, action selection); prefabs; a **Game Master** resolves natural-language actions into grounded outcomes and checks plausibility | [P] <https://github.com/google-deepmind/concordia>, <https://arxiv.org/abs/2312.03664> |
| AgentTorch / LLM archetypes | Large population models (GPU), e.g. COVID in NYC | 8.4M agents | ~400 LLM queries for weekly decisions of 8.4M agents (GPT-3.5); ~95% less runtime than LLM-as-agent at fixed prompt budget | Differentiable simulator calibrated by gradient to historical data | Agents grouped into archetypes (e.g. age x sex); LLM queried M times per archetype x action; answers averaged into a probability; agents sample from it | [P] <https://github.com/AgentTorch/AgentTorch>, <https://arxiv.org/abs/2409.10568>, <https://arxiv.org/html/2409.10568v3> |
| ABIDES (non-LLM baseline) | Exchange + trading agents, NASDAQ ITCH/OUCH-like messages, pairwise latency | Tens of thousands of agents | CPU | Seeded config builders | Python agent classes and config builders | [P] <https://arxiv.org/abs/1904.12066>, <https://github.com/jpmorganchase/abides-jpmc-public> |

### 2.2 Cross-cutting findings

- **Scale vs expressiveness is the central trade-off.** The archetype paper frames it explicitly (heuristic agents vs fully adaptive LLM agents) and shows that per-group querying covers 8.4M agents where per-agent LLM covers 300 under the same prompt budget. [P] <https://arxiv.org/html/2409.10568v3>
- **Fidelity of LLM "people" is partial and biased.** GPT-3.5 replicated 37.5% of analyzable Many Labs 2 effects, and gave near-identical "correct answers" on nuanced questions across runs. [P] <https://arxiv.org/abs/2302.07267>. GPT-4 and Llama 3.1 silicon samples on ANES items showed structural inconsistency across demographic aggregation levels and "severe homogenization" (minority opinions underrepresented). [P] <https://arxiv.org/abs/2507.02919>. Interview-grounded agents do better (86% of test-retest on GSS). [P] <https://arxiv.org/abs/2411.10109>
- **Instruction tuning shifts behavior**: agents are overly cooperative and formal. [P] <https://ar5iv.labs.arxiv.org/html/2304.03442>. For fraud/abuse simulation this is a direct risk: an aligned model under-produces adversarial behavior unless it is constrained or the behavior is scripted. [U]
- **Simplified environments damp dynamics**: OASIS notes its simplified recommender struggles with intermediary users and simulated cascades were shallower than real ones. [P] <https://arxiv.org/html/2411.11581>
- **Behavior specification converges on: profile + memory + action space + environment arbiter.** Profiles are free text or attribute tables (RecAgent, OASIS JSON, Y Social panel); action spaces are enumerated (OASIS 21 actions, Binance-like order types in market sims); an arbiter (Concordia Game Master, OASIS platform, an order book) turns intents into state changes. [P for each system above; U for the generalization]
- **None of the LLM-agent systems surveyed documents seed-level reproducibility.** Replay logs (AgentSociety) and caching are the substitute. Temperature-0 inference is itself not deterministic in typical serving because kernels are not batch-invariant (Qwen3-235B: 80 unique completions in 1,000 temperature-0 runs; identical with batch-invariant kernels at some speed cost). [P] <https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/>, <https://github.com/TauricResearch/TradingAgents>

---

## 3. Practical hybrid patterns

### 3.1 Where the LLM sits: five options

| Pattern | LLM calls | Reproducible? | Typical use | Notes |
|---|---|---|---|---|
| A. LLM as **author/compiler** | Once per scenario (plus repair loop) | Yes, once outputs are pinned | Generate event catalog, state machines, distributions, typologies from a business description | Output validated by JSON Schema and engine checks; committed to git [U] |
| B. LLM as **persona generator** | Once per persona (or batch) | Yes, once pinned | Population of profiles, then mapped to numeric parameters | PersonaHub: 1B web-curated personas (200k public preview; 370M "elite" added Feb 2025; CC BY-NC-SA 4.0) [P] <https://arxiv.org/abs/2406.20094>, <https://huggingface.co/datasets/proj-persona/PersonaHub> |
| C. LLM **archetypes** (offline or per-epoch) | K archetypes x A actions x M samples | Yes if answers are cached per (archetype, context) | Behavior probabilities that react to simulated context | AgentTorch: ~400 queries for 8.4M agents [P] <https://arxiv.org/html/2409.10568v3> |
| D. LLM for **content only** | Per content item, or cached templates | Partly | Post text, product reviews, memo fields, support chat | Structure from engine, text from LLM; can be done after the fact on a sample [U] |
| E. LLM **in the loop per agent step** | Per active agent per step | No (sec. 2.2) | Small qualitative studies, emergent-behavior exploration, red-teaming | OASIS, RecAgent, StockAgent [P links in 2.1] |

Recommendation [U]: A + B + C as the default; D where text realism matters; E only in a sandbox to discover behaviors that are then distilled into A/C.

### 3.2 LLM-as-compiler pipeline (authoring time)

1. Input: business description, optional real aggregates (rates, top-k shares), optional tracking plan or API spec. [U]
2. LLM emits a candidate **domain pack** under a fixed JSON Schema: event catalog, entities, journeys, distributions, typologies. Constrained decoding can guarantee schema-valid JSON, with documented exceptions: refusals, `max_tokens` truncation, enum casing, and unsupported keywords (e.g., `minimum`/`maximum`, `minLength`, recursive schemas are not supported in strict mode). So numeric ranges and cross-field rules still need a second validator. [P] <https://platform.claude.com/docs/en/build-with-claude/structured-outputs>
3. Engine-side semantic validation: every transition emits a cataloged event; every reference resolves; state machine has no unreachable/absorbing-by-mistake states; probabilities sum to 1; feasibility (e.g. degree sums). AMLSim's own example degree file is internally inconsistent, a reminder that hand- or LLM-written specs need this. [P for AMLSim observation via techniques doc sec. 4A.6; U for the checklist]
4. Dry run at small N; compute a report of achieved statistics; LLM or human repairs; repeat. [U]
5. Pin: commit the pack, record model ID, prompt hash, and output hash in run metadata; production runs never call the LLM. [U]

Evidence on code-generation fidelity: in an ODD-to-Python replication study of 17 LLMs on a predator-prey ABM, "behaviorally faithful implementations are achievable but not guaranteed", and executability alone was insufficient; implementations needed statistical comparison against a validated NetLogo baseline. [P] <https://arxiv.org/abs/2602.10140>. Earlier work found GPT-3.5 generated better NetLogo code with examples. [U, snippet] <https://informs-sim.org/wsc24papers/con303.pdf>. Implication: generate **config for a trusted engine**, not engine code, and test outputs statistically. [U]

### 3.3 Persona generation

- Free-text personas (PersonaHub style) must be mapped to engine parameters (activity rate, basket size, risk appetite, device mix). Do the mapping with an LLM once per persona (pattern B) or once per archetype cluster (pattern C), output to a numeric schema, then **re-weight to target marginals** (e.g., country, age, segment shares) so the population matches real aggregates rather than the LLM's priors. [U]
- OASIS generated its 1M profiles by sampling attributes as roughly independent variables and linking to core users via interests; that independence assumption is a known weakness when attributes are correlated in reality. [P for method] <https://arxiv.org/html/2411.11581>; [U for the weakness]
- RecAgent supports handcrafted, GPT-generated, and real-data-aligned profiles, combinable. [P] <https://arxiv.org/html/2306.02552v3>

### 3.4 Calibration of LLM-authored distributions

- LLM-proposed distributions are priors; treat them as initial values and fit to real aggregates (marginals, top-k shares, funnel conversion rates, inter-event gap quantiles). [U]
- Precedents: AgentTorch fits structural parameters by gradient through a differentiable simulator against historical infection/unemployment data [P] <https://arxiv.org/html/2409.10568v3>; IBM AML generator calibrated to real transactions; Simod tunes simulation parameters from logs (techniques doc sec. 4A.6) [P links there].
- Known homogenization means LLM priors under-disperse; check variance and tails explicitly, not only means. [P for homogenization] <https://arxiv.org/abs/2507.02919>; [U for the check]

### 3.5 Cost and scale arithmetic

- OASIS reference: ~3,356 input + ~168 output tokens per active agent-step (335.6k / 16.75k for 100 agents). [P, derived from] <https://github.com/camel-ai/oasis>
- If each emitted event required one such call, 1M events would need ~3.4B input tokens and ~0.17B output tokens; 100M events ~100x that. [U, arithmetic on the above; real ratio of events per call varies]
- RecAgent: 100 agents took ~1.9 h per round on one API key. [P] <https://arxiv.org/html/2306.02552v3>. OASIS 1M agents x 60 steps: ~1 week on 24 A100s. [P] <https://arxiv.org/html/2411.11581>
- By contrast, a vectorized NumPy/Polars engine like the repo's generates 100k events in seconds-to-minutes on a laptop. [U, not benchmarked here]
- Levers [U]: activation probability (OASIS uses 0.1/0.01 [P] <https://arxiv.org/html/2411.11581>); archetypes; caching keyed by (archetype, discretized context); small local models for routine choices and large models for rare decisions (TradingAgents' deep/quick split is a precedent [P] <https://github.com/TauricResearch/TradingAgents>); generating text only for a sample.

### 3.6 Distilling LLM behavior into cheap policies

- Archetype probabilities (pattern C) are the simplest distillation: a lookup table from (group, context) to action probabilities. [P for mechanism] <https://arxiv.org/html/2409.10568v3>
- Next step [U]: log (state, action) pairs from a pattern-E sandbox run, fit a transition matrix per persona cluster or a small classifier/sequence model, and use it as the runtime policy; validate by comparing sequence statistics (n-gram frequencies, dwell times) between LLM run and distilled run.
- LLM tabular generators (GReaT) fine-tune an LLM to emit rows and can condition on feature subsets; usable when real data exists, but per-row generation cost is high and constraints are not guaranteed. [P for method] <https://arxiv.org/abs/2210.06280>; [U for the cost claim]

### 3.7 Validation, hallucination and bias risks

| Risk | Example evidence | Mitigation [U unless cited] |
|---|---|---|
| Hallucinated facts/events | Generative Agents embellished knowledge [P] <https://ar5iv.labs.arxiv.org/html/2304.03442> | Engine is source of truth; LLM proposes, Game-Master-style arbiter validates (Concordia GM checks plausibility [P] <https://arxiv.org/abs/2312.03664>) |
| Invalid structure | Schema exceptions in constrained decoding [P] <https://platform.claude.com/docs/en/build-with-claude/structured-outputs> | Two-stage validation (schema + semantic) |
| Homogenization / modal answers | [P] <https://arxiv.org/abs/2507.02919>, <https://arxiv.org/abs/2302.07267> | Calibrate variance/tails; mix personas; temperature/sampling diversity |
| Alignment-induced niceness | Overly cooperative agents [P] <https://ar5iv.labs.arxiv.org/html/2304.03442> | Script adversarial typologies in the scenario layer rather than asking the LLM to "be a fraudster" |
| Training-data leakage in finance sims | StockAgent designs against test-set leakage from memorized market history [U, snippet] <https://arxiv.org/abs/2407.18957> | Use synthetic instruments/prices; never let the LLM see real future data |
| Prompt fragility across models | RecAgent prompts "may not be robust for different LLMs" [P] <https://arxiv.org/html/2306.02552v3> | Pin model ID; regression-test packs when model changes |
| Code-gen behavioral drift | ODD study [P] <https://arxiv.org/abs/2602.10140> | Generate config not code; statistical acceptance tests |

### 3.8 Reproducibility

- LLM outputs vary across runs even at temperature 0 on standard serving stacks; batch-invariant kernels fix this at some throughput cost. [P] <https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/>
- Model versions and providers change; results are model-specific (StockAgent, TradingAgents). [P] <https://arxiv.org/html/2407.18957v3>, <https://github.com/TauricResearch/TradingAgents>
- Practical rule [U]: treat every LLM output as an **artifact** (content-addressed, committed or stored), and make the seeded engine consume artifacts only. Then `seed + pack hash + engine version` reproduces the dataset bit-for-bit, matching the repo's existing determinism test.

---

## 4. Domain templates

Notation: lifecycles as `state -> state`. Signature statistics are calibration targets for the validation report. Standards/datasets are what a domain pack should borrow its schema from.

### 4.1 E-commerce

| Aspect | Template |
|---|---|
| Entities | user, session, device, product (category, brand, price), cart, order, payment, shipment, promotion, review |
| Events | GA4 recommended set: `view_item_list`, `select_item`, `view_item`, `add_to_cart`, `add_to_wishlist`, `view_cart`, `remove_from_cart`, `begin_checkout`, `add_shipping_info`, `add_payment_info`, `purchase`, `refund`, `view_promotion`, `select_promotion`; items array with `item_id`, `item_name`, `price`, `quantity`, `discount`, `coupon`, `item_brand`, `item_category`..`item_category5`, `item_variant`, `item_list_id`, `promotion_id`; up to 200 items, 27 custom item params [P] <https://developers.google.com/analytics/devguides/collection/ga4/ecommerce> |
| Lifecycles | Funnel: list -> item -> cart -> checkout -> shipping -> payment -> purchase (with drop-off at each step); order: placed -> paid -> shipped -> delivered -> (returned/refunded) [U] |
| Linkage | user-device, user-address, user-payment instrument, referral, product co-view/co-purchase graph [U] |
| Signature stats | Steep funnel drop-off; heavy-tailed product popularity (Zipf-like) and spend per user; diurnal/weekly and promotion spikes; cart abandonment [U, no primary source fetched] |
| Public data/schemas | GA4 obfuscated sample e-commerce dataset (Google Merchandise Store, 2020-11-01 to 2021-01-31, `events_*` daily shards; obfuscated, limited internal consistency) [P] <https://developers.google.com/analytics/bigquery/web-ecommerce-demo-dataset>; WebShop (1.18M products) for catalog realism [P] <https://arxiv.org/abs/2207.01206>; Agent4Rec/RecSim for recommender interaction loops [P] links in 2.1 |
| Fraud/scenario templates | Promo/referral abuse (repo's bounty-hunter scenario), account takeover, card testing, reseller bots [U] |

### 4.2 Centralized crypto exchange (CEX)

| Aspect | Template |
|---|---|
| Entities | user (KYC tier), account/sub-account, wallet (per asset), deposit address, symbol/market, order, trade, API key, device/IP |
| Events | Orders with types `LIMIT`, `MARKET`, `STOP_LOSS`, `STOP_LOSS_LIMIT`, `TAKE_PROFIT`, `TAKE_PROFIT_LIMIT`, `LIMIT_MAKER`; time in force `GTC`/`IOC`/`FOK`; execution types `NEW`, `CANCELED`, `REPLACED`, `REJECTED`, `TRADE`, `EXPIRED`, `TRADE_PREVENTION` [P] <https://developers.binance.com/docs/binance-spot-api-docs/enums>; market data streams: `trade` (fields `e,E,s,t,p,q,T,m`), `aggTrade`, `kline_{interval}`, partial and diff `depth`, `bookTicker` [P] <https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams>; account events: signup, KYC, deposit, withdrawal, transfer, login, API-key create [U] |
| Lifecycles | Order: `NEW -> PARTIALLY_FILLED -> FILLED`, or `-> CANCELED / EXPIRED / EXPIRED_IN_MATCH (STP) / REJECTED` [P] <https://developers.binance.com/docs/binance-spot-api-docs/enums>; withdrawal: requested -> risk review -> approved -> broadcast -> confirmed / rejected [U] |
| Linkage | user-device-IP, deposit/withdrawal addresses linking to on-chain graph, wash-trading counterparties, referral [U] |
| Signature stats | Cont's stylized facts of returns: absence of linear autocorrelation, heavy tails, gain/loss asymmetry, aggregational Gaussianity, intermittency, volatility clustering, conditional heavy tails, slow decay of absolute-return autocorrelation, leverage effect, volume/volatility correlation, timescale asymmetry; on 2018-19 Dow 30 intraday data 8 held and gain/loss asymmetry, leverage effect, timescale asymmetry were not supported [P] <https://arxiv.org/html/2311.07738v2> (Cont 2001 original paywalled, not fetched); self-exciting order flow modeled with Hawkes processes [P] <https://arxiv.org/abs/1502.04592>; crypto-specific confirmation of these facts not fetched [U] |
| Public simulators/data | ABIDES (exchange + value/momentum/noise/market-maker agents, ITCH/OUCH-style messages) [P] <https://arxiv.org/abs/1904.12066>, <https://github.com/jpmorganchase/abides-jpmc-public> (archived June 2025); LLM trader sims (StockAgent, TradingAgents, Lopez-Lira) in 2.1 |
| Scenario templates | Wash trading, spoofing/layering, pump-and-dump around a listing, withdrawal-address takeover, exchange outage/price shock incident [U] |
| Design note | Prices should come from a matching engine fed by agent orders (ABIDES style) or from a stochastic price process with order flow conditioned on it; independent sampling of trades breaks the order-book identities [U] |

### 4.3 Layer-one blockchain

| Aspect | Template |
|---|---|
| Entities | Account (EOA) / address, contract (token, DEX, bridge), validator, block, transaction, receipt, log; Bitcoin variant: UTXO |
| Events / objects | Ethereum JSON-RPC objects. Block: `number`, `hash`, `parentHash`, `miner`, `gasLimit`, `gasUsed`, `timestamp`, `transactions`...; Transaction: `hash`, `from`, `to`, `value`, `gas`, `gasPrice`, `nonce`, `input`, `blockNumber`, `transactionIndex`; Receipt: `status`, `gasUsed`, `cumulativeGasUsed`, `effectiveGasPrice`, `contractAddress`, `logs`; Log: `address`, `topics`, `data`, `logIndex` [P] <https://ethereum.org/en/developers/docs/apis/json-rpc/>; spec in `ethereum/execution-apis`; Python executable reference of the execution layer in `ethereum/execution-specs` [P] <https://github.com/ethereum/execution-specs>; ERC-20 `Transfer(from, to, value)` (mint from `0x0`) and `Approval(owner, spender, value)` [P] <https://eips.ethereum.org/EIPS/eip-20> |
| Validator/consensus events | 12 s slots, 32-slot epochs; one pseudo-random proposer per slot; committees attest once per epoch; 32 ETH deposit; checkpoint justification/finalization at 2/3 of stake; slashing for double proposal or contradictory attestations; inactivity leak after >4 epochs without finality [P] <https://ethereum.org/en/developers/docs/consensus-mechanisms/pos/> |
| Lifecycles | Tx: submitted -> pending (mempool) -> included -> (receipt status success/failure) -> finalized; or dropped/replaced (same nonce) [U for mempool details]; validator: deposited -> pending -> active -> exiting/slashed -> withdrawn [U] |
| Bitcoin variant | Inputs spend previous outputs by (txid, index); outputs spent whole; change outputs; fee = inputs - outputs; coinbase exception [P] <https://developer.bitcoin.org/devguide/transactions.html> |
| Hard invariants | Nonce strictly increasing per sender; balances non-negative; sum(gasUsed) <= gasLimit per block; block timestamps on slot grid; UTXO spent at most once; logs belong to receipts belong to txs belong to blocks [P for the object model; U for listing as generator invariants] |
| Linkage | Address transfer graph, contract-call graph, exchange hot/cold wallets, bridges; clustering heuristics (common-input ownership) [U] |
| Signature stats | Bitcoin transaction network grows by linear preferential attachment; wealth by sublinear preferential attachment; degree-wealth scaling [P] <https://arxiv.org/abs/1308.3892>; whale concentration (small share of addresses hold most supply) [U, no primary figure fetched] |
| Public data | Elliptic: 203,769 Bitcoin tx nodes, 234,355 edges, 49 time steps ~2 weeks apart, 4,545 illicit (~2%), 42,019 licit (~21%), ~77% unlabeled, 166 features (94 local + 72 aggregated) [P] <https://arxiv.org/html/1908.02591>; SNAP soc-sign-bitcoin-otc/alpha trust networks and ERC20-stablecoin / ethereum-exchanges datasets listed [P] <https://snap.stanford.edu/data/> |
| Scenario templates | Peel chains, mixer usage, rug pull, airdrop farming (Sybil clusters), bridge exploit, MEV sandwich [U] |
| Design note | Use a real execution engine only if contract semantics matter; otherwise simulate at the receipt/log level with an explicit balance ledger to keep invariants [U] |

### 4.4 Social network (SNS)

| Aspect | Template |
|---|---|
| Entities | Actor (person/organization/bot), post/note, comment, media, follow edge, block/mute, community/group, report/moderation case |
| Events | ActivityPub/ActivityStreams 2.0: `Create`, `Update`, `Delete`, `Follow`, `Accept`, `Reject`, `Like`, `Announce` (repost/boost), `Undo`, `Block`, `Add`, `Remove`; actors have `inbox`, `outbox`, `followers`, `following`; Follow is effective only after `Accept` [P] <https://www.w3.org/TR/activitypub/>; OASIS action list (sign up, post, repost, like, dislike, comment, follow, unfollow, mute, search, trend, refresh, do nothing) [P] <https://arxiv.org/html/2411.11581> |
| Lifecycles | Follow: requested -> accepted/rejected -> (undone); post: created -> (edited) -> (reported -> moderated/removed) -> deleted; account: created -> active -> (suspended) -> deleted [P for Follow/Accept; U for the rest] |
| Linkage | Directed follow graph, reply/repost cascades, shared device/IP for bot farms, community structure [U] |
| Signature stats | Twitter 2009 crawl (41.7M profiles, 1.47B follows): follower distribution fits a power law with exponent 2.276 up to ~10^5 followers, with a heavier-than-power-law tail beyond (celebrities, media); reciprocity only 22.1% of linked pairs (vs 68% Flickr, 84% Yahoo!360 cited there); 67.6% of users not followed back by anyone they follow; retweet-tree sizes power-law [P] <https://www.ece.ucdavis.edu/~chuah/rubinet/people/chuah/classes/eec273/eec273-s14/refs/%5BKL+10%5Dwww-twitter.pdf> (WWW 2010 paper; text extracted from PDF; ACM page 403); bursty activity and diurnal cycles (OASIS hourly vectors) [P] <https://arxiv.org/html/2411.11581> |
| Public simulators/data | OASIS, Y Social, AgentSociety, RecAgent (sec. 2.1); SNAP: ego-Twitter (81,306 nodes / 1.77M edges), soc-LiveJournal1 (4.85M / 69M), higgs-twitter, twitter7 (17M users / 477M tweets) [P] <https://snap.stanford.edu/data/> |
| Scenario templates | Bot farm/coordinated inauthentic behavior, spam bursts, follow-for-follow rings, harassment campaign, viral misinformation cascade [U] |
| Where LLMs add most value | Post/comment text (pattern D) and topic/opinion dynamics; graph and timing stay mechanistic [U] |

### 4.5 Payment system

| Aspect | Template |
|---|---|
| Entities | Customer, merchant, payment method/card, PaymentIntent/charge, refund, dispute, payout, bank account, issuer/acquirer, device/IP |
| Events | Stripe naming `resource.event`: `payment_intent.created`, `.processing`, `.requires_action`, `.succeeded`, `.payment_failed`, `.canceled`, `.amount_capturable_updated`, `.partially_funded`; `charge.succeeded`, `.failed`, `.pending`, `.captured`, `.refunded`, `.expired`; `charge.dispute.created`, `.updated`, `.closed`, `.funds_withdrawn`, `.funds_reinstated`; `refund.created/updated/failed`; `payout.created/paid/failed/canceled/reconciliation_completed` [P] <https://docs.stripe.com/api/events/types> |
| Lifecycles | PaymentIntent: `requires_payment_method -> requires_confirmation -> requires_action -> processing -> succeeded`, optional `requires_capture`; failure returns to `requires_payment_method`; `canceled` before processing/succeeded (some bank debits cancellable in processing) [P] <https://docs.stripe.com/payments/paymentintents/lifecycle>; Dispute: inquiry statuses `warning_needs_response`, `warning_under_review`, `warning_closed` (120 days); chargeback `needs_response` -> evidence -> `won`/`lost` (rare late win); cardholders typically have 120 days to dispute, merchant 7-21 days to respond, issuer 60-75 days to decide, 2-3 months total; ~40% of Visa/Mastercard early fraud warnings become fraud disputes if not refunded [P] <https://docs.stripe.com/disputes/how-disputes-work> |
| Interbank messages | ISO 20022 covers payments, securities, cards; SWIFT adoption began March 2023 [P] <https://en.wikipedia.org/wiki/ISO_20022> (iso20022.org returned 403); message roles: `pain.001` customer initiation, `pacs.008` FI-to-FI customer credit transfer, `pacs.002` status report, `pacs.004` return, `camt.053` end-of-day statement [U, bank guides via search snippet; official catalogue not fetched] |
| Linkage | Customer-card-device-IP-merchant bipartite graphs; mule accounts; merchant collusion [U] |
| Signature stats | Label delay is structural (dispute windows of months) [P for timelines above]; fraud base rates far below 1% (PaySim default `fraudProbability=0.001`) [P] <https://raw.githubusercontent.com/EdgarLopezPhD/PaySim/master/PaySim.properties>; amount distributions heavy-tailed [U] |
| Public simulators/data | PaySim, AMLSim, IBM AML generator, BankSim (techniques doc secs. 1, 4A); ULB credit-card fraud dataset (Kaggle page did not render; figures not verified) [U] <https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud> |
| Scenario templates | Card testing, account takeover, friendly fraud (disputes on delivered goods), refund abuse, mule fan-in/fan-out (AMLSim typologies), merchant bust-out [U; AMLSim typologies P in techniques doc] |

### 4.6 What is shared across domains

| Shared concept | E-com | CEX | L1 | SNS | Payments |
|---|---|---|---|---|---|
| Actor | user | user/API key | address/validator | actor | customer/merchant |
| Long-lived object with lifecycle | order | order, withdrawal | transaction, validator | post, follow | PaymentIntent, dispute |
| Ledger / conservation invariant | inventory (weak) | balances per asset | balances, UTXO, gas | none | balances, payouts |
| Clock | wall clock, diurnal | wall clock + trading sessions (24/7) | slot grid (12 s) | wall clock, diurnal | wall clock + settlement/dispute windows |
| Graph | referral, co-purchase | addresses, counterparties | transfer graph | follow graph | card-device-merchant |
| Concentration knob | spend per user | volume per trader | balance per address | followers | volume per merchant |

[U, synthesis from 4.1-4.5]. This table is the argument for a common core: actors, lifecycle objects, ledgers, clocks, graphs, and concentration specs are domain-agnostic; event names and invariants are domain packs.

---

## 5. Recommended architecture

All of sec. 5 is design synthesis [U], grounded in the sources above and in the repo (read-only).

### 5.1 Core abstractions

| Abstraction | Responsibility | Notes |
|---|---|---|
| `EventType` | Name, version, JSON Schema of payload, entity references, emitted-by | Loaded from catalog; exportable to Snowplow/Segment/Weaver formats |
| `EntityType` | ID namespace, population/arrival, attributes (cardinality x volatility, coupled change groups) | Generalizes repo `EntitySpec`/`AttrSpec` |
| `Relation` | Edge type between entity types, generator, caps, concentration target | Generalizes repo `RefSpec` + choosers |
| `Lifecycle` (state machine) | States, transitions (weight, guard on entity/ledger state, delay distribution, emitted event) | Per long-lived object (order, PaymentIntent, tx) |
| `Journey` | Actor-level policy choosing which lifecycles to start, with persona-dependent weights and think times | Locust/Gatling semantics: weighted tasks, open arrival model |
| `Ledger` | Conserved quantities and invariants (balances, nonces, UTXO, inventory) | Transitions that violate invariants are rejected or repaired |
| `Clock` | Time grid and intensity: diurnal/weekly, domain grids (slots), Hawkes bursts, calendar events | One per domain; journeys sample against it |
| `Scenario` | Injections: typologies, incidents, label rules, signal strength, decoys | Generalizes repo planted-signal + AMLSim typologies |
| `Policy` provider | Where decisions come from: table (Markov/weights), archetype table (LLM-derived), Python class, or (sandbox only) live LLM | One interface, so LLM-derived behavior is swappable with hand-written |
| `Run` | Seed, N, span, sinks, versions; per-component RNG streams; meta.json + validation report | Extends repo `meta.json` |

### 5.2 How domains plug in

- A **domain pack** is a directory: `catalog/*.json` (event schemas), `entities.yaml`, `lifecycles/*.yaml`, `relations.yaml`, `clock.yaml`, `scenarios/*.yaml`, optional `plugins.py` (custom generators, policies, invariants), and `targets.yaml` (signature statistics to report and test against).
- Packs register through an entry point / registry dict, as `datagen.scenarios.SCENARIOS` does today.
- Engine guarantees the cross-domain machinery: ordering, point-in-time joins, references existing before use, RNG streams, export, validation report.
- Cross-domain runs (e.g. CEX withdrawals landing on an L1 pack) connect through shared entity types (address) and a bridge lifecycle.

### 5.3 Where LLM agents fit

| Phase | LLM role | Output | Checked by |
|---|---|---|---|
| Authoring | Compile business description / API docs / tracking plan into a domain pack (pattern A) | YAML/JSON pack | JSON Schema + semantic validator + dry-run report; human review |
| Authoring | Generate personas and map to numeric parameters (B) | `personas.parquet` with parameters | Re-weighting to target marginals |
| Authoring / per-epoch | Archetype action probabilities for context-sensitive behavior (C) | Cached table keyed by (archetype, context bucket) | Spot checks; variance/tail checks |
| Post-processing | Text fields for a sample of events (D) | Text columns | Toxicity/PII filters; schema |
| Research sandbox | Live agents to discover behaviors (E); distill into tables/policies | Logs -> fitted policies | Sequence-statistic comparison |
| Never at production runtime | -- | -- | Runtime is seeded engine only |

### 5.4 Config sketch

```yaml
# packs/payments/pack.yaml  (illustrative, not an implemented format)
pack: payments
version: 0.1.0
catalog: catalog/            # JSON Schema per event; names follow stripe-like resource.event
entities:
  customer: {arrival: {curve: linear, span_frac: 0.9},
             attrs: [{name: country, card: low, vol: static, k: 30},
                     {name: address, card: high, vol: slow, couple: geo}]}
  card:     {per: customer, count: {dist: poisson, mean: 1.3}}
  device:   {per: customer, count: {dist: poisson, mean: 1.5}, share: {cap: 5}}
  merchant: {n: 2000, volume_concentration: {metric: top_k_share, k: 0.01, target: 0.4}}
lifecycles:
  payment_intent:
    initial: requires_payment_method
    transitions:
      - {from: requires_payment_method, to: processing, p: 0.93, emit: payment_intent.processing,
         delay: {dist: lognormal, median_s: 4}}
      - {from: requires_payment_method, to: requires_action, p: 0.05, emit: payment_intent.requires_action}
      - {from: processing, to: succeeded, p: 0.97, emit: payment_intent.succeeded}
      - {from: processing, to: requires_payment_method, p: 0.03, emit: payment_intent.payment_failed}
  dispute:
    start_on: {event: charge.succeeded, p: 0.004, delay: {dist: gamma, mean_days: 35, max_days: 120}}
    # needs_response -> under_review -> won|lost ; delays from Stripe docs
clock: {diurnal: hourly_profile.csv, weekly: [1,1,1,1,1.1,1.2,0.9]}
journeys:
  shopper: {policy: table, tasks: {pay: 10, refund_request: 0.3, add_card: 0.2},
            think_time: {dist: exponential, mean_h: 30}}
scenarios:
  - {type: card_testing, count: 20, cards_per_ring: [50, 300], amount_usd: [0.5, 2],
     window_h: [1, 6], label: true}
  - {type: friendly_fraud, share_of_customers: 0.002, label: delayed}
targets:                      # reported and asserted in validation report
  fraud_rate: [0.001, 0.003]
  merchant_top1pct_share: [0.35, 0.45]
provenance:                   # filled when an LLM authored the pack
  authored_by: {model: "<model-id>", prompt_sha256: "...", output_sha256: "..."}
```

```python
# packs/payments/plugins.py  (escape hatch; illustrative)
@register_policy("payments.risk_averse_shopper")
class RiskAverse(Policy):
    def choose(self, actor, state, rng):          # pure function of (actor, state, rng)
        ...

@register_invariant("payments.no_refund_over_charge")
def no_overrefund(ledger, event): ...
```

### 5.5 Relation to the existing repo

| Repo today (read-only review) | Keeps / generalizes into | Gap to close |
|---|---|---|
| `neorisk_simkit.attributes`: `AttrSpec(name, Cardinality, Volatility, k)`, change points at Poisson rates (slow 1/90 per day, fast 1/2 per day), fast attrs reflecting random walk, long-form timelines | Entity attribute layer (layer 2/4) | Coupled change groups (geo/IP), configurable rates per attribute, declarative form |
| `entities`: `EntitySpec`, `build_entities`, `attach_asof` (point-in-time join) | Entity layer + point-in-time contract | Arrival curves, per-parent child counts, sharing caps |
| `references`: `RefSpec(column, target_entity, chooser)` with `uniform`/`skewed`/`hubs` | Relation layer | Generator catalog (BA/SBM/config model), concentration targets, achieved stats in report |
| `features.rolling` / `rolling_asof` over `[t-w, t)` | Golden-feature and validation tooling | Reuse for signature-stat reports per domain |
| `scorer` (`XGBScorer`, `calibrate`, `sample_labels`) planted-signal labels | Scenario layer label rules | Label delay (essential for payments disputes), decoys |
| `export` (UUIDs at export, golden columns refused in `events.parquet`), `meta.json` with seed/config/versions | Run layer | Add pack hash, LLM provenance, validation report |
| `apps/datagen`: Python scenario modules registered in `SCENARIOS`, `FraudConfig` dataclass with `validate()`, CLI `--scenario --n-events --seed --span-days --bad-rate` | Domain-pack registry + run config | Event catalog, lifecycle/journey engine, declarative pack format loaded into the same dataclasses |
| Determinism: same seed gives identical output (tested) | Non-negotiable runtime property | LLM outputs must enter only as pinned artifacts (sec. 3.8) |

Suggested path [U]:
1. Add an `EventType` catalog and a `Lifecycle` engine to simkit (vectorized where possible: sample per-object paths through the state machine, then times), keeping integer `idx` entities and `attach_asof`.
2. Re-express the fraud scenario as the first pack (e-commerce + referral abuse) to prove parity (identical outputs under the same seed is not required, but same statistics are).
3. Add a declarative loader that builds the existing dataclasses from YAML, validated by a JSON Schema; Python scenarios remain valid packs.
4. Add a payments pack (lifecycles from Stripe docs, dispute label delay) and an L1 pack (ledger invariants), which exercise the two features the fraud scenario lacks: lifecycles and conservation.
5. Add the LLM authoring tool as a separate CLI (`datagen author --describe ...`) whose only output is a pack plus provenance; the generator stays LLM-free.

---

## 6. Open problems and risks

- **Validity of LLM-authored behavior.** No source surveyed shows LLM-authored simulation configs reproducing real business aggregates without calibration; social-science evidence shows homogenization and structural inconsistency. Calibration data is the bottleneck. [P for the bias evidence: <https://arxiv.org/abs/2507.02919>; U for the gap]
- **Adversarial realism.** Fraud and abuse are adversarial and adaptive; aligned LLMs under-produce them, and scripted typologies are only as good as the analyst's imagination. Planted signals risk being trivially learnable (techniques doc sec. 7). [P for cooperativeness <https://ar5iv.labs.arxiv.org/html/2304.03442>; U otherwise]
- **Reproducibility of anything LLM-touched** depends on artifact pinning; provider-side model updates and non-batch-invariant serving break replays. [P] <https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/>
- **Cost cliffs.** Per-step LLM agents scale linearly in tokens with agents x steps x activation; 1M-agent runs took a week on 24 A100s. [P] <https://arxiv.org/html/2411.11581>
- **Cross-domain coherence.** Joining packs (CEX withdrawals -> L1 transfers -> payments off-ramps) requires shared identity and consistent clocks/ledgers; no surveyed system covers multiple business domains at once. [U]
- **Ledger and invariant enforcement vs vectorization.** Conservation (balances, nonces, UTXO) is sequential only where later decisions read the state: updates to one owner's state must be ordered, but independent owners can run in parallel, and additive totals that no decision consults can be reduced after the fact. Vectorized generation therefore needs per-owner sequential passes (compiled loops, parallel across owners) and an ordered path only for genuinely shared, decision-relevant state, rather than repair steps. [U]
- **Stylized facts are domain- and era-specific.** 3 of Cont's 11 facts failed on modern intraday Dow 30 data; Twitter followers are not a clean power law. Targets must be sourced per domain and period, not assumed. [P] <https://arxiv.org/html/2311.07738v2>, Kwak et al. PDF above
- **Schema drift.** Real event schemas evolve (Snowplow SchemaVer, Segment event versions); packs need versioned catalogs and migration rules. [P for versioning features in 1.2; U for the need]
- **Licensing of persona/data sources.** PersonaHub is CC BY-NC-SA 4.0, which constrains commercial use. [P] <https://huggingface.co/datasets/proj-persona/PersonaHub>
- **Evaluation.** TSTR and column-level metrics (techniques doc sec. 5.5) do not test journeys, lifecycles, or graph statistics; a per-domain "signature statistic" test suite is still to be designed. [U]

---

## Claims lacking primary sources (summary)

- All rows/bullets tagged [U]: the layered design and its rules (1.4), the five LLM-placement patterns and recommendation (3.1), compiler-pipeline steps (3.2), persona re-weighting, distillation procedure, cost extrapolation to 1M/100M events, mitigation column in 3.7, all of sec. 5 (architecture, config sketch, path), and open-problem items marked [U].
- Domain statistics without a fetched primary source: e-commerce funnel drop-off, Zipf product popularity, cart abandonment; crypto-specific stylized facts (only equity-based Cont replication fetched); on-chain whale concentration figures (only Kondor et al. abstract on preferential attachment); payment amount heavy tails; mempool and validator lifecycle details beyond ethereum.org PoS page.
- ISO 20022 message roles (`pain.001`, `pacs.008`, `pacs.002`, `pacs.004`, `camt.053`): from bank-guide search snippets only; iso20022.org (403), SWIFT (403), Fedwire and ECB pages did not show them.
- ULB credit-card fraud dataset figures: Kaggle page did not render.
- Lopez-Lira 2025 LLM market simulation and StockAgent "external factors" findings: search snippets only (StockAgent HTML was fetched for setup details only).
- Cont (2001) original: paywalled (403); stylized-fact list taken from the 2023 replication paper.
- Kwak et al. 2010: ACM page 403; figures extracted from a university-hosted PDF copy (treated as [P]).
- Ampli's relation to Iteratively: not on the fetched page.
- Martinez et al. WSC 2024 (GPT-3.5 NetLogo): search snippet only.
- Generative Agents limitations and cost came from ar5iv HTML (arXiv PDF exceeded fetch size).
- Not fetched at all: Gretel, Simod details beyond techniques doc, BPMN executable engines, Snowplow SchemaVer rules, Segment's segment.com domain (403; Twilio mirror used).
