# Blacklist sources

Assessed 2026-11-06 while collecting the Binance hack (`incidents/binance-2026-10.md`).
"Fetchable" means fetched by script from this machine without a login.

| source | publisher | trust | fetchable | chains | per-address role? |
| --- | --- | --- | --- | --- | --- |
| FBI / IC3 alert | US government | high (official attribution) | no: fbi.gov 403s scripts | ETH, BTC, SOL | no |
| OFAC SDN list | US Treasury | high (legal sanction) | partly: `sanctionslist.ofac.treas.gov` CSV 403s plain curl; `eth-collect ofac` works | many | no |
| Elliptic incident blocklist | analytics firm | high | yes, public CDN CSV | all hit chains | no |
| USDT / USDC freeze events | Tether, Circle (on-chain) | high as fact, low as reason | yes (Blockscout keyless, Etherscan, TronGrid) | ETH, Tron (+ other chains Tether is on) | no |
| freeze status view | same contracts | high as fact | yes (public RPC, TronGrid) | ETH, Tron | no |
| tayvano/lazarus-bluenoroff-research | independent DPRK researcher, CC0 | medium | yes, GitHub raw | all | in free text |
| Bitquery investigation page | analytics vendor | medium | page only; bulk data paid | ETH, BTC, Tron, SOL, XRP, OP, ARB | yes, best roles |
| TRM Labs / Chainalysis blogs | analytics firms | high for narrative | yes, but no addresses published | — | — |
| Etherscan labels | explorer | medium | no: 403 to scripts; API needs key and has no label endpoint on free plans | EVM | label names |
| Chainabuse | community reports | low | no: redirects / bot wall | many | report text |

## Government

**FBI / IC3 alerts.** The FBI publishes the address list for big DPRK thefts
(Bybit 2025: PSA on ic3.gov; Binance 2026: 628 addresses — 608 ETH, 19 BTC, 1 SOL — at
`fbi.gov/investigate/cyber/alerts/2026/north-korea-responsible-for-6-billion-binance-attack`).
Most authoritative attribution there is, but it is a snapshot from day 2 and is far smaller
than vendor lists. fbi.gov returns 403 to curl and WebFetch, and the Wayback availability API
rate-limited us; get it by opening the page in a browser (Playwright MCP is available) and
saving the list. Treat every FBI address as `high`, role "holds or held stolen funds".

**OFAC SDN.** Sanctions are legal facts and the strongest label, but designations lag
incidents by weeks to months and none existed for Binance 2026 on 2026-11-06. The repo
already parses it: `uv run eth-collect ofac` (see `eth-collect/references/labels/ofac.md`).

## Analytics-firm blocklists

**Elliptic.** For major incidents Elliptic publishes a free blocklist page
(`elliptic.co/<incident>-blocklist/`) whose download link is a plain CDN file, e.g.
`https://data-cdn.elliptic.co/blocklists/binance-hack-blocklist.csv`. The page shows an email
form, but the CSV link itself needs no sign-up. Format: one address per line, **no header, no
chain column, no role**. Check `last-modified`/`etag` — Elliptic updates it as tracing
continues. Quality checks done on the Binance list: it excludes Binance's victim hot wallets
(Ethereum, Tron, Solana) and the JustLend USDT market contract, and includes all sampled
attacker and attacker-controlled intermediary wallets from Bitquery. The page states no
licence; using it for internal screening and model labels matches its stated purpose
("any business can download it"), but don't republish it. Use as `high`.

TRM Labs and Chainalysis publish good narratives and attribution but keep addresses inside
their paid products. Read them for roles and laundering paths, not for lists.

## On-chain issuer freezes

The freeze itself is public contract state, so it can't be wrong — only misinterpreted.

| token | chain | contract | freeze event | status view |
| --- | --- | --- | --- | --- |
| USDT | Ethereum | `0xdac17f958d2ee523a2206206994597c13d831ec7` | `AddedBlackList(address)`, address in `data`, topic0 `0x42e16015…19dc` | `isBlackListed(address)` `0xe47d6060` |
| USDC | Ethereum | `0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48` | `Blacklisted(address indexed)`, address in topic1, topic0 `0xffa4e618…b855` | `isBlacklisted(address)` `0xfe575a87` |
| USDT | Tron | `TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t` | `AddedBlackList`, `result._user` is 0x-hex (convert to base58 `T…`) | `getBlackListStatus(address)` |

Paxos tokens and EURC are covered by `eth-collect stablecoin_freezes` (Ethereum, all history).

How to read freezes:
- **Reason is not on-chain.** In the Binance hack week Tether froze 19 Ethereum and 104 Tron
  addresses; only 50% (Eth) and 10% (Tron) were also in Elliptic's hack list. Tron freezes
  are dominated by everyday scam / fraud freezes.
- **Timing helps.** Freezes minutes after the theft (21:01 UTC, 37 minutes after the drain)
  are the incident; days later they mix with routine freezes.
- **Victims get frozen.** Tether froze Binance's hot wallet `0x28c6c062…` at 22:06 on the hack
  day; Circle froze two Binance hot wallets.
- **Unfreezes exist** (`RemovedBlackList`, `UnBlacklisted`) and aren't collected yet; use
  `check` for the current state before acting on an old freeze.
- `DestroyedBlackFunds` (USDT) means Tether burned the frozen balance and usually re-issued it
  to the victim — a strong "this was criminal" signal when present.

## Researchers

**tayvano/lazarus-bluenoroff-research** (GitHub, CC0). One markdown file per DPRK incident
under `hacks-and-thefts/` and `more-hacks-and-thefts/`, updated within a day of big hacks
(`binance.md` created 2026-10-30, updated 2026-11-05). Free-form notes: amounts, links, and
addresses of attackers **and victims, signers, deposit addresses**. The script keeps each
address's section heading and line in `ref` so victims can be dropped by reading them. 52 of
64 extracted Binance addresses are in Elliptic's list; the rest are mostly Binance's own
wallets. `eth-collect lazarus` already ingests the EVM part with victim filtering.

**ZachXBT** posts on X and Telegram; high signal, no machine-readable list. Cite, don't scrape.

## Vendor write-ups

**Bitquery investigations** (`bitquery.io/investigations/<incident>`) list ~150 full addresses
with roles (hot wallet, attacker, frozen, intermediary, service) across chains — the best
role source found. Page only; the underlying datasets are paid. Fetch the page with WebFetch
and ask for a table of address / chain / role, then save it as CSV in the incident folder.
Treat as `medium`; trust roles more than counts.

## Not usable as a list

- **Etherscan / Tronscan labels**: valuable tags but blocked to scripts and not exposed on
  free APIs. Use by hand to confirm a role.
- **Chainabuse**: community reports, gated behind a bot wall; low trust anyway.
- **News articles / Wikipedia**: use for incident facts and links to primary sources only.
