---
name: eth-collect
description: Collect Ethereum transaction, address and label data for the bad-address model by driving the `eth-collect` connector scripts in apps/ethcollect. Use whenever the user wants Ethereum data or labels pulled, refreshed, sampled, checked or extended with a new source — e.g. "/eth-collect --source ofac", "collect the labels", "pull the history of these addresses", "build the toy sample", "how much data do we have", "add Chainabuse as a source", "why did the etherscan run fail" — even if they don't name the skill.
argument-hint: "--source <name> | --sample toy | --status | --new-source <name> [connector options]"
---

# eth-collect

You drive one script, `uv run eth-collect`, which has one subcommand per data source
(a *connector*) plus `labels`, `sample`, `status` and `new-source`. The scripts do the fetching
and parsing; your job is to pick the right runs, run them, read the results, and explain or fix
what went wrong. Read `references/contract.md` once before changing any connector.

## Map the request to commands

| user says | run |
| --- | --- |
| `--source <name> [opts]` | `uv run eth-collect <name> [opts]` |
| `--source labels`, "refresh the labels" | `uv run eth-collect labels` |
| `--sample toy`, "build the toy set" | `uv run eth-collect sample toy` (add `--skip-labels` if labels are fresh) |
| `--status`, "what do we have" | `uv run eth-collect status` |
| `--new-source <name>` | `uv run eth-collect new-source <name> --kind label\|chain`, then see "Adding a source" |
| "history of these addresses" | `uv run eth-collect etherscan --addresses <file>`; with no key, only day snapshots: `aws-public --mode scan` (watches risk labels) |

`uv run eth-collect <name> --help` lists a connector's own options. Shared options on every
connector: `--since/--until` (default last 365 days), `--limit N` (quick check), `--refresh`
(bypass the raw cache), `--rate` (calls per second), `--out` (default `data/eth`).

Before a run that costs many calls (a sample, history for hundreds of addresses), tell the user
roughly how many calls and minutes it will take; the numbers are in each source's reference.

## The run-then-check loop

1. Run the command. Each run prints `ok`/`FAILED`, its row counts and the run record path.
2. On `FAILED`, read the run record (`data/eth/runs/<source>-<time>.json`: `error`,
   `warnings`, `failed_addresses`) and the source's reference for known failure modes. Common:
   - `ETHERSCAN_API_KEY is not set` → ask the user for a key (see references/etherscan.md).
   - `rate limited by eth.blockscout.com for N more minutes` → keyless Blockscout allows about
     10 calls per half hour; switch to etherscan, or wait.
   - a parse error after a format change → open the cached raw file in `data/eth/raw/<source>/`,
     update `parse()` and the reference together, add a test with the new shape.
3. Reruns are cheap: responses are cached, so a rerun re-parses without re-fetching. Use
   `--refresh` only when the source itself changed.
4. Finish with `uv run eth-collect status` and report the counts that changed, not the whole
   report.

## Adding a source

1. Check the source's terms of use allow automated access. If they forbid scraping, stop and
   tell the user; do not add it.
2. `uv run eth-collect new-source <name> --kind label|chain` creates
   `apps/ethcollect/src/ethcollect/connectors/<name>/` and `references/[labels/]<name>.md`.
3. Register it in `connectors/__init__.py` (`SOURCES`), write a pure `parse(body)`, and a
   unit test on a small real sample saved from the raw cache.
4. Fill the reference: access, format, field mapping, trust, quirks. For web pages, follow
   `references/html-parsing.md`.
5. Run with `--limit 10`, check rows, then a full run, then `status`.

## Ground rules

- Labels are noisy positives: never write a "good" label. Exchanges, bridges, mixers and DEXes
  are service labels (`is_risk = false`), not clean negatives.
- Every label keeps its `source`, `source_ref` and `trust`; a hand-curated label needs a
  source URL (the `huione` connector rejects rows without one).
- Secrets come only from environment variables and never go into files, records or chat.
- Do not touch the modeling code from this skill; the modeling side reads `data/eth/` only.

## References

- `references/contract.md` — the connector rules, tables, cache and run records
- `references/sampling.md` — the toy recipe and what its checks mean
- chain: `aws-public.md`, `etherscan.md` (also Blockscout), `rpc.md`
- labels: `labels/<source>.md`, one per label connector
- `references/html-parsing.md` — extracting addresses from web pages, terms check first
