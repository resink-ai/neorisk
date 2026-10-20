# Event-Based Systems: Knowledge Base

Compiled 2026-10-14. Each claim carries a URL. Tags: **[P]** = traced to a primary source fetched during research; **[U]** = unverified (general knowledge or a source that could not be fetched; treat as unconfirmed).

---

## 1. What an event-based system is

### 1.1 Definition
- **Event sourcing**: "capture all changes to an application state as a sequence of events", kept in order, so current state can be rebuilt, past states queried, and history corrected. [P] <https://martinfowler.com/eaaDev/EventSourcing.html>
- **Log as backbone**: a log is "an append-only, totally ordered sequence of records"; apps append changes to a shared log and each datastore (cache, index, view) consumes it in order and can be rebuilt by replay. Consumers are eventually consistent. [P] <https://martin.kleppmann.com/2015/05/27/logs-for-data-infrastructure.html>
- Working definition for this repo: a system whose source of truth is an append-only stream of immutable, timestamped facts about entities; all state, features and metrics are derived views over that stream. [U, synthesis]

### 1.2 Anatomy of an event

| Part | Purpose | Example sources |
|---|---|---|
| Event ID | Unique per event; dedup key | CloudEvents `id` (producer-unique; `source`+`id` must be unique per distinct event, retries may reuse it) [P] <https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md>; Snowplow `event_id` UUID [P] <https://docs.snowplow.io/docs/fundamentals/canonical-event/>; Segment `messageId` [P] <https://www.twilio.com/docs/segment/connections/spec/common>; Stripe event IDs [P] <https://docs.stripe.com/webhooks> |
| Event type / name | What happened | CloudEvents `type`, Segment `type`/`event` |
| Event time | When it happened (in the world) | CloudEvents `time` (RFC 3339, optional) [P] same spec |
| Entity IDs | Who/what it is about (user, device, account, order) | Segment `userId`/`anonymousId` [P]; CloudEvents `subject` [P] |
| Properties | Event-specific attributes (amount, channel...) | Amplitude: event properties describe a specific instance of an event [P] <https://amplitude.com/docs/data/data-planning-playbook> |
| Context / enrichment | Device, IP, geo, derived fields added later | Snowplow enrichment + entities [P] <https://docs.snowplow.io/docs/fundamentals/events/> |

### 1.3 Immutability
- Event ID, event time and entity IDs must never change after emission; corrections are new events (compensating or superseding), not edits. Stripe states Event objects cannot be changed after creation. [P] <https://docs.stripe.com/webhooks> (API versioning section). Fowler: a wrong past event is handled by reversing it and later events, i.e. new facts, not mutation. [P] <https://martinfowler.com/eaaDev/EventSourcing.html>
- Immutability of "event time" is a design rule, not something the sources spell out as such. [U for the generalized rule]

### 1.4 Client sends bare-bones, server enriches
- Snowplow pipeline: trackers send events, which are validated and enriched (e.g. `derived_tstamp` is computed in enrichment, not by the tracker) before warehouse load. [P] <https://docs.snowplow.io/docs/fundamentals/events/>, <https://docs.snowplow.io/docs/fundamentals/canonical-event/>
- Segment: `timestamp` is computed server-side as `receivedAt - (sentAt - originalTimestamp)` to correct client clock skew. [P] <https://www.twilio.com/docs/segment/connections/spec/common>
- Rationale (never trust the client for IP, geo, account tier; keep payloads small) is common practice. [U]

### 1.5 Event time vs ingestion/processing time
| Time | Meaning | Source |
|---|---|---|
| Occurred / event time | When it happened on the device | Segment `originalTimestamp`; Snowplow `dvce_created_tstamp` [P] |
| Sent time | When the client sent the batch | Segment `sentAt`; Snowplow `dvce_sent_tstamp` [P] |
| Received / collector time | When the platform got it | Segment `receivedAt`; Snowplow `collector_tstamp` [P] |
| Corrected time | Clock-skew-adjusted | Segment `timestamp`; Snowplow `derived_tstamp` [P] |
| Enrichment/ETL time | When enriched | Snowplow `etl_tstamp` [P] |
| Recorded time | When the system recorded it (bitemporal pair with occurred) | Fowler's example records both occurred and recorded times [P] <https://martinfowler.com/eaaDev/EventSourcing.html> |

Segment advises `timestamp` for chronological analysis because `originalTimestamp`/`sentAt` are skew-prone. [P]

### 1.6 Coarse vs fine-grained events: deposit-flow example
Coarse: one `deposit_completed` event with everything. Cheap, but you lose where users drop and cannot see intermediate status.
Fine-grained: one event per meaningful state change.

| # | Event | Emitted by | Entity IDs | Notes |
|---|---|---|---|---|
| 1 | `deposit_page_viewed` | client | user/device/session | funnel top |
| 2 | `deposit_start_tapped` | client | user/device/session | intent |
| 3 | `deposit_transaction_created` | server | user, `order_id` | first time the order ID exists; this is the join key from here on |
| 4 | `deposit_status_changed` (`pending`->`processing`->`succeeded`/`failed`) | server / PSP webhook | `order_id` | one event per transition, with `from`/`to` |

Design points: steps 1-2 carry no order ID (it does not exist yet), so linking to step 3 requires user/device/session identity; steps 3-4 are keyed by `order_id`. Payment providers model the same shape: Stripe PaymentIntent moves `requires_payment_method` -> `requires_confirmation` -> `requires_action` -> `processing` -> `succeeded`/`canceled`, and a failed attempt returns to `requires_payment_method`. [P] <https://docs.stripe.com/payments/paymentintents/lifecycle> Adyen delivers asynchronous outcomes by webhook carrying a snapshot of the resource. [P] <https://docs.adyen.com/development-resources/webhooks/> (event names such as AUTHORISATION/CAPTURE not verified: [U]).

---

## 2. Data perspective

### 2.1 Facts, dimensions, grain
- **Grain** = what one fact-table row represents; declare it first, prefer atomic grain, one grain per fact table. [P] <https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/grain/>
- Events map to **transaction fact tables** (one row per event); status/lifecycle objects map to accumulating or periodic snapshots. Kimball technique list names these (definitions not on the index page). [P for names] <https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/>; the mapping itself [U].
- **Dimensions** describe who/what/where; **conformed dimensions** are shared across fact tables so they can be drilled across. [P for names, definitions U] same index page.

### 2.2 Slowly changing dimensions
- **Type 1** overwrite, **Type 2** add new row, **Type 3** add new attribute. [P for names] index page above.
- Type 2: new row with new surrogate key; at least effective date, expiration date and current-row indicator columns. [P] <https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/type-2/>

Two ways to know "what was true then":

| Approach | Shape | Pros | Cons |
|---|---|---|---|
| SCD2 valid_from/valid_to | one row per version | exact change time, compact | range joins; needs reliable change timestamps |
| Periodic snapshot partitions (hourly/daily) | full state per `snapshot_ts` partition | simple equi-join on partition; easy backfill | resolution limited to snapshot cadence; storage grows; a change inside the interval is invisible [U, engineering tradeoff] |

```sql
-- SCD2 as-of join
SELECT t.*, a.risk_tier
FROM txn t
JOIN account_scd2 a
  ON a.account_id = t.account_id
 AND t.event_time >= a.valid_from
 AND t.event_time <  COALESCE(a.valid_to, TIMESTAMP '9999-12-31');

-- Daily snapshot: use the PRIOR day's snapshot to avoid leakage
SELECT t.*, s.risk_tier
FROM txn t
JOIN account_snapshot s
  ON s.account_id = t.account_id
 AND s.snapshot_date = DATE(t.event_time) - INTERVAL 1 DAY;
```

### 2.3 Point-in-time (as-of) queries and joins
- Snowflake `ASOF JOIN ... MATCH_CONDITION(left.t >= right.t)` returns, per left row, the closest right row (<= for the example), optional equality `ON` keys; ties are non-deterministic; no match gives NULLs. [P] <https://docs.snowflake.com/en/sql-reference/constructs/asof-join>
- Table time travel (state of a table at a past instant, different from event-time as-of): Delta `TIMESTAMP AS OF` / `VERSION AS OF` [P] <https://docs.delta.io/latest/delta-batch.html>; BigQuery default 7-day window, configurable 2-7 days [P] <https://docs.cloud.google.com/bigquery/docs/time-travel>; Iceberg has "time travel queries" in Spark docs [P for existence] <https://iceberg.apache.org/docs/latest/spark-queries/>.
- Feature stores: Feast `get_historical_features` joins on entity timestamps, scanning back from each row's timestamp, limited by TTL; late-arriving/backfilled values can leak unless `filter_by_created_timestamp=True`. [P] <https://docs.feast.dev/getting-started/concepts/point-in-time-joins> (Tecton docs page could not be fetched: [U]).

```sql
-- generic as-of join (no ASOF support)
SELECT e.event_id, f.feature_value
FROM events e
LEFT JOIN LATERAL (
  SELECT feature_value FROM features f
  WHERE f.entity_id = e.entity_id AND f.feature_time <= e.event_time
  ORDER BY f.feature_time DESC LIMIT 1) f ON TRUE;
```

### 2.4 Enrichment
Add context at ingest (geo from IP, device parse) or at query time via dimension joins. Prefer ingest-time for facts that can change later (so they reflect state at the time). Snowplow does ingest-time enrichment. [P] <https://docs.snowplow.io/docs/fundamentals/events/>; guidance itself [U].

### 2.5 Leakage
Using information with a timestamp after the prediction/decision time: joining the latest dimension row instead of the as-of row, using `ingestion_time` features that were not yet available, labels maturing after the cutoff, or corrected values backfilled later. Feast documents the backfill case. [P] <https://docs.feast.dev/getting-started/concepts/point-in-time-joins> Two clocks matter: when the value was true (event time) and when it was knowable (recorded/created time). Fowler's occurred vs recorded pair is the same idea. [P] <https://martinfowler.com/eaaDev/EventSourcing.html>

### 2.6 Late and out-of-order events
- Stripe does not guarantee event delivery order, and `created` has second resolution so ties happen; do not use it for ordering. [P] <https://docs.stripe.com/webhooks>
- Fowler: replay can handle events received in the wrong sequence. [P] <https://martinfowler.com/eaaDev/EventSourcing.html>
- Practical handling: watermark / lateness window, reprocess partitions, store both event and ingestion time. [U, general stream-processing practice]

### 2.7 Idempotency and dedup
- Webhooks can be delivered more than once; log processed event IDs and skip repeats; sometimes two separate Event objects exist, so also compare `data.object.id` + `type`. [P] <https://docs.stripe.com/webhooks>
- API idempotency keys: client-generated unique key (<=255 chars), server replays the saved response; v1 keys prunable after 24 h. [P] <https://docs.stripe.com/api/idempotent_requests>
- CloudEvents: consumers may treat same `source`+`id` as duplicates. [P] spec above.

```sql
SELECT * FROM (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY ingested_at) rn
  FROM raw_events) WHERE rn = 1;
```

### 2.8 Identity resolution / stitching
- Segment requires `userId` or `anonymousId`; use `anonymousId` when no user identifier exists. [P] <https://www.twilio.com/docs/segment/connections/spec/common>
- Amplitude user properties persist across later events until changed, whereas event property values are as of the event. [P via search summary] <https://amplitude.com/docs/data/data-planning-playbook>
- Amplitude's device ID / user ID / Amplitude ID merge model: official page could not be fetched. [U] (try <https://amplitude.com/docs/get-started/identify-users>)
- Stitching pattern: map anonymous IDs to a user ID at login, then re-key earlier events. Beware retroactive re-keying changes history, so version the mapping with a timestamp. [U]

```sql
SELECT e.*, COALESCE(m.user_id, e.user_id, e.anonymous_id) AS resolved_id
FROM events e LEFT JOIN id_map m
  ON m.anonymous_id = e.anonymous_id AND m.linked_at <= e.event_time;
```

---

## 3. Analysis perspective

All of this section is standard analytics practice. Primary sources fetched only for experimentation; the rest is **[U]** unless a link is given.

- **Funnel**: ordered steps within a window, counted per entity, e.g. deposit page -> start -> created -> succeeded. Conversion = users reaching step n / users at step 1. [U]
- **Retention**: share of a cohort that performs a return event on day/week N; classic (on day N) vs rolling (on or after N). [U]
- **Cohort**: group users by a shared first event or property in a period (signup week). [U]
- **Sessionization**: split a user's events on an inactivity gap (commonly 30 min). [U]
```sql
SUM(CASE WHEN t - LAG(t) OVER (PARTITION BY user_id ORDER BY t) > INTERVAL 30 MINUTE
         OR LAG(t) OVER (PARTITION BY user_id ORDER BY t) IS NULL THEN 1 ELSE 0 END)
  OVER (PARTITION BY user_id ORDER BY t) AS session_idx
```
- **Metrics**: define as (event filter, entity unit, aggregation, window); keep grain explicit. [U]

### Experimentation
- **Assignment**: Statsig randomizes units to control/test; a deterministic bucketing means each unit value always gets the same variant; unit (userID, stableID, sessionID) should match where in the journey assignment happens, else crossovers. [P] <https://docs.statsig.com/experiments/overview>
- **Exposure events**: log when a unit actually experiences the variant, separate from assignment; Statsig's SDK logs exposures automatically on check, and decoupling can cause SRM. [P via search summary] <https://statsig.com/blog/sample-ratio-mismatch>. Full exposure-event definition page not fetched: [U].
- **Exposure-based analysis**: only include units after their first exposure; metrics counted from exposure time forward to avoid diluting with never-exposed units. [U] (Statsig/Eppo/Optimizely docs not fetched).
- **SRM**: observed split differs from expected; Statsig runs a chi-squared test; causes include client crash before exposure log, conditional exposure rules, truncated bulk logs. [P via search summary] <https://docs.statsig.com/experiments/monitoring/srm>
- **Unit of analysis**: should equal randomization unit (or use variance corrections like delta method / clustering). [U]
- **Growth analysis**: acquisition -> activation -> retention -> revenue funnels, cohort LTV, with exposure-aware experiments. [U]

---

## 4. Use-case survey

| Domain | How events are used | Source |
|---|---|---|
| Product analytics (Amplitude, Segment, Snowplow) | event + user (+group) properties; taxonomy planning; funnels/retention | <https://amplitude.com/docs/data/data-planning-playbook>, <https://docs.snowplow.io/docs/fundamentals/events/> [P] |
| Payments / fintech | lifecycle state machines emitted as events; async outcomes via webhooks; idempotency keys | <https://docs.stripe.com/payments/paymentintents/lifecycle>, <https://docs.stripe.com/webhooks>, <https://docs.adyen.com/development-resources/webhooks/> [P] |
| Experimentation | assignment + exposure events, SRM checks | <https://docs.statsig.com/experiments/overview> [P] |
| Growth | funnels, cohorts, LTV | [U] |
| Fraud / risk | rolling-window features over event streams (counts/sums per entity over 1h/24h/7d); point-in-time-correct joins for training; decision-time features must use only events before the decision | Feast PIT docs [P] <https://docs.feast.dev/getting-started/concepts/point-in-time-joins>; fraud-specific design [U] |
| Observability / audit | append-only logs, replayable history, CloudEvents as interchange | <https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md> [P] |
| Event sourcing / CQRS | events as source of truth, derived read models by replay | Fowler [P] <https://martinfowler.com/eaaDev/EventSourcing.html>; Kleppmann [P]; CQRS-specific source not fetched [U] (Fowler's CQRS page: <https://martinfowler.com/bliki/CQRS.html>) |

---

## 5. Terminology cheat sheet

| Perspective | Term | Definition | Source |
|---|---|---|---|
| System | Event | Immutable record that something happened | Fowler <https://martinfowler.com/eaaDev/EventSourcing.html> |
| System | Event sourcing | State stored as sequence of events | Fowler (same) |
| System | Log | Append-only, totally ordered record sequence | <https://martin.kleppmann.com/2015/05/27/logs-for-data-infrastructure.html> |
| System | CloudEvents | Vendor-neutral event envelope (`id`,`source`,`specversion`,`type` required) | <https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md> |
| System | Webhook | Provider pushes async event to your HTTPS endpoint | <https://docs.stripe.com/webhooks> |
| System | Idempotency key | Client key making retries safe | <https://docs.stripe.com/api/idempotent_requests> |
| System | Enrichment | Server-side addition/derivation of fields | <https://docs.snowplow.io/docs/fundamentals/events/> |
| Data | Event time / `originalTimestamp` | When it occurred on client | <https://www.twilio.com/docs/segment/connections/spec/common> |
| Data | `receivedAt` / `collector_tstamp` | When platform received it | Segment page; <https://docs.snowplow.io/docs/fundamentals/canonical-event/> |
| Data | `derived_tstamp` | Clock-skew-corrected time | Snowplow canonical event page |
| Data | Grain | What one fact row represents | <https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/grain/> |
| Data | Fact / dimension table | Measurements vs descriptive context | Kimball techniques index (names only) |
| Data | SCD Type 2 | New row per change with effective/expiry dates | <https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/type-2/> |
| Data | As-of / point-in-time join | Latest right row at or before left timestamp | <https://docs.snowflake.com/en/sql-reference/constructs/asof-join> |
| Data | Time travel | Query table as of past version/time | <https://docs.delta.io/latest/delta-batch.html> |
| Data | TTL (feature) | Max lookback for PIT feature join | <https://docs.feast.dev/getting-started/concepts/point-in-time-joins> |
| Data | Leakage | Future info in training/decision features | Feast PIT page |
| Data | Anonymous ID / user ID | Pre-login vs known identity | Segment common-fields page |
| Analysis | Funnel / retention / cohort / session | See section 3 | [U] |
| Analysis | Assignment | Allocation of a unit to a variant | <https://docs.statsig.com/experiments/overview> |
| Analysis | Exposure | Logged moment unit experiences variant | <https://statsig.com/blog/sample-ratio-mismatch> |
| Analysis | SRM | Observed split deviates from expected | <https://docs.statsig.com/experiments/monitoring/srm> |
| Modeling | Event property | Attribute of one event instance | <https://amplitude.com/docs/data/data-planning-playbook> |
| Modeling | User property | Trait persisting until changed | same |
| Modeling | Group property | Attribute of an account/org level group | Amplitude group properties page not reached [U] |
| Modeling | Taxonomy | Naming/hierarchy conventions for events | Amplitude playbook |
| Modeling | Self-describing event / entity | Schema-referenced payload / attached context | <https://docs.snowplow.io/docs/fundamentals/events/> |
| Modeling | Conformed dimension | Dimension shared across facts | Kimball index (name only) |

---

## 6. Link to this repo (apps/bench, datagen)

Synthetic fraud event data with point-in-time rolling features maps directly:
- Each generated transaction is a transaction-fact row whose grain is one event; rolling counts/sums per card/account/device are windowed aggregates that must include only events with `event_time` strictly before the scored event (the Feast "no future data" rule).
- Labels (chargeback/fraud) mature later than the event, so train/test splits must respect label maturity and out-of-time ordering (what the `bench temporal` command targets); using labels or corrections recorded after the cutoff is leakage.
- Faithful datagen should simulate event time vs ingestion time, late/duplicate events and entity re-keying if the benchmark is meant to stress those failure modes; otherwise they are idealized away. [U, design suggestion]
- Evaluation reporting convention (memory note): show ROC and PR curves side by side.

## Not traced to a primary source
Sections 3 (funnel/retention/cohort/sessionization/growth, unit of analysis, exposure-based analysis), the fraud-feature design, CQRS, Amplitude identity/group-property pages, Tecton, Eppo/Optimizely/LaunchDarkly, PayPal, Kimball SCD1/3/conformed/snapshot definitions, Adyen event names, and the snapshot-vs-SCD2 tradeoffs.
