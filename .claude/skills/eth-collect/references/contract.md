# The connector contract

A connector is `apps/ethcollect/src/ethcollect/connectors/<module>/connector.py` (+ README.md),
registered in `connectors/__init__.py` under its kebab-case `--source` name. It exposes:

| name | meaning |
| --- | --- |
| `KIND` | `"chain"` (writes transfers/addresses) or `"label"` (writes labels) |
| `SUMMARY` | one line: what it gives, access, trust |
| `DEFAULT_RATE` | calls per second when `--rate` is not given |
| `add_arguments(p)` | its own argparse options |
| `run(ctx, args)` | fetch through `ctx`, parse, write tables, `ctx.note(...)` counts |
| `parse(...)` | pure function, raw bytes or records in, table rows out; unit-tested |

## Five rules

1. **One entry point:** `uv run eth-collect <source> [options]`, with `--help`.
2. **Shared inputs:** `--since/--until` (default last 365 days), `--limit`, `--out`, `--refresh`,
   `--rate`; address-driven sources take `--address`/`--addresses`.
3. **Shared outputs only:** rows in `transfers`, `addresses`, `labels` (schemas in
   `tables.py`), each row tagged with `source`. Build rows with `tables.frame` /
   `tables.label_rows`; never invent columns or label kinds.
4. **Raw cache first:** fetch with `ctx.get(url, params=...)`, `ctx.cached(key, fetch)` or
   `ctx.http(...)` + `ctx.cached`. Bodies land in `data/eth/raw/<source>/` and reruns read them.
   Never cache an error body (`ctx.forget`).
5. **Run record:** the CLI writes `data/eth/runs/<source>-<UTC time>.json` with options, counts,
   `warnings`, `error`, `seconds`. Put anything a person debugging needs into `ctx.note`.

## Tables

Stored as `data/eth/<table>/<source>.parquet`. Label connectors `tables.write` (replace: their
source is a snapshot); chain connectors `tables.append` (add, de-duplicated on the key).
`tables.load(root, table)` unions all sources: transfers and labels de-duplicate on their key
(first source by name wins); addresses merge per address (any `is_contract`, earliest
`first_seen`, strongest `sample_reason`, all sources listed).

| table | key | notes |
| --- | --- | --- |
| transfers | tx_hash, log_index, kind | `log_index` -1 for the transaction itself; `amount` in whole units when `decimals` known; `ts` UTC |
| addresses | address | `sample_reason`: seed, random, counterparty, given |
| labels | address, label_kind, source | `trust` 0.9/0.6/0.3; `observed_at` + `date_known` |

Label kinds: risk = sanctioned, scam, phishing, hack, laundering, frozen; service = exchange,
bridge, mixer, dex, service. Trust: high (official lists, issuer freezes), medium (explorer and
security-vendor tags), low (crowd reports).

**Timing rule:** `observed_at` is the earliest date the source shows the claim; when the source
gives none it is the fetch date and `date_known` is false. The modeling side drops a labeled
address's transfers after `observed_at`; `status` counts how many there are.

## Secrets

Only from the environment: `ETHERSCAN_API_KEY`, `ETH_RPC_URL`, later
`GOOGLE_APPLICATION_CREDENTIALS`. `apikey`/`key`/`token` query parameters are stripped from cache
keys, run records and error messages (`context.redact`).
