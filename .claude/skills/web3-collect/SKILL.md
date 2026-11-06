---
name: web3-collect
description: Find, fetch, check and interpret blacklisted wallet addresses across chains (Ethereum and other EVM chains, Tron, Bitcoin, Solana, XRP) — hack and theft addresses, stablecoin issuer freezes, incident blocklists — using the stdlib script in scripts/blacklist.py and the source catalogue in references/. Use whenever the user asks where to get bad / black / sanctioned / frozen wallet addresses, wants the addresses of a specific hack or exploit pulled, asks whether an address is frozen or blacklisted, asks how reliable a blacklist source is, or wants a new incident or chain covered — e.g. "get the addresses from the Binance hack", "is this Tron address frozen by Tether", "which blacklist sources can we trust", "add the Bybit hack", even if they don't name the skill.
argument-hint: "elliptic | freezes --since D --until D | tayvano --file F | check ADDR... | overlap A B"
---

# web3-collect

Multi-chain blacklist collection. One script, `scripts/blacklist.py` (standard library only),
fetches each source into the same CSV shape — `source, chain, address, observed_at, ref` —
so lists from different sources can be compared and merged. The Ethereum-only labelling
pipeline with caching and parquet output is the `eth-collect` skill (`apps/ethcollect`); use
this skill for incidents, non-Ethereum chains and quick checks, and promote a source to an
`eth-collect` connector once it proves useful.

Read before acting:
- `references/sources.md` — every source: trust, access, format, how to read it. **Read it
  before telling anyone a source is reliable.**
- `references/endpoints.md` — which free endpoints work, their limits, and the failure modes
  already hit (so you don't rediscover them).
- `references/incidents/` — one file per incident: what happened, where its addresses are,
  samples, cross-check numbers. Start from an existing one for a new incident.

## Commands

Run from anywhere; write outputs to the scratchpad or `data/`, not into this folder.

```
S=.claude/skills/web3-collect/scripts/blacklist.py
python3 -I $S elliptic --out elliptic.csv                       # default: Binance 2026 list
python3 -I $S elliptic --url <other elliptic csv> --out x.csv
python3 -I $S freezes --since 2026-10-29 --until 2026-11-06 --out freezes.csv   # eth + tron
python3 -I $S freezes --chain tron --since ... --until ...
python3 -I $S tayvano --file hacks-and-thefts/binance.md --out tayvano.csv
python3 -I $S check 0x5227f603c1ee34ce3c06efe6477003bdfccb2f8c TG5iBMQPrDzJJAUM8GMVBf1hRaJ1wvzsGi
python3 -I $S overlap freezes.csv elliptic.csv --show 10
```

Optional keys, read from the environment (`.env` at the repo root holds them; load with
`set -a; . ./.env; set +a` or `uv run --env-file .env python ...`): `ETHERSCAN_API_KEY`
(Ethereum logs via Etherscan, faster than keyless Blockscout), `TRON_PRO_API_KEY`
(TronGrid without anonymous throttling).

## Collecting an incident

1. **Confirm the incident** from two independent reputable outlets (date, victim, amount,
   attribution). Note disagreements instead of picking one figure.
2. **Find the address lists**, in this order (details and trust in `references/sources.md`):
   government alerts (FBI/IC3, OFAC) → analytics-firm blocklists (Elliptic publishes free
   CSVs per big incident; TRM/Chainalysis usually don't) → issuer freezes on-chain → curated
   researcher notes (tayvano, ZachXBT) → vendor write-ups with role-tagged addresses (Bitquery).
3. **Fetch** with the script; if a source has no command, save the raw page/file and record
   how it was obtained in the incident file.
4. **Cross-check** with `overlap`. Expect: researcher notes mostly inside the vendor list;
   freezes only partly inside it (issuers freeze for unrelated reasons every day).
5. **Write it down** in `references/incidents/<victim>-<yyyy-mm>.md`: sources tried and
   whether each was fetchable, counts, samples, overlaps, caveats.

## Interpreting the addresses — the rules that matter

- **A freeze is a fact, not a reason.** Issuer freeze events prove the issuer froze the
  address at that time; they don't say why. Within an incident window only the freezes that
  another incident source also lists are incident addresses. Victims get frozen too (Tether
  froze Binance's own hot wallet), so a freeze is never "attacker" on its own.
- **Exclude victims and services.** Incident notes and vendor write-ups name the victim's hot
  wallets, bridges, DEX pools, lending markets and exchange deposit addresses alongside
  attacker wallets. Blacklisting those poisons a model. Keep the role column and drop
  anything whose role is victim, service, contract or exchange.
- **Address format only gives the chain family.** `0x…` is any EVM chain; the source must
  say which (Ethereum, Base, Arbitrum, BSC…). `guess_chain` is a format guess, so label it as
  a guess.
- **Lists grow for weeks.** Snapshot with the fetch date and the server's `last-modified`;
  re-fetch rather than assume completeness. Elliptic's Binance list went 8,000 → 18,134 in a
  week.
- **Trust tiers for labels**: `high` = government list, issuer freeze cross-confirmed by an
  incident list, curated analytics blocklist; `medium` = named researcher notes, role-tagged
  vendor analysis; `low` = unconfirmed freeze, community reports, single-source mentions.
