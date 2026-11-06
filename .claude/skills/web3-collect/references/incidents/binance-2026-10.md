# Binance hot-wallet hack, 2026-10-29

Collected 2026-11-05/06. Figures are from the first week and still moving.

## Facts

- **When**: 2026-10-29, first attacker transfer ~20:05 UTC, EVM drain ~20:20–20:24 UTC;
  about 20 minutes, ~11 chains (Ethereum largest, ~$3.8B; also Bitcoin, Tron, Solana, XRP,
  Base, Optimism, Arbitrum, Avalanche, Polygon, NEAR).
- **Amount**: ~$6.3B (Binance $6.34B; Chainalysis $6.4B; tayvano $6.36B). Largest crypto theft
  on record, ahead of Bybit 2025 ($1.5B).
- **Attribution**: FBI, 2026-10-31: DPRK "TraderTraitor" (Lazarus). TRM, Chainalysis, ZachXBT
  agree. North Korea denies.
- **Entry**: a wallet-team employee ran a tampered AI tool; fake job interview; attacker code
  executed by hot wallet "Binance 14".
- **Freezes**: Tether ~$1.5B+ within an hour (first at 21:01 UTC), Circle, Ripple, World
  Liberty; ~$2.7–3B frozen in total. Binance covered user losses from reserves.
- **Laundering**: THORChain and Relay bridges to BTC/ETH, a self-minted token + liquidity pool
  on Tron (most active branch early November), JustLend on Tron, Tornado Cash for gas.

## Where the addresses are

| source | how | count (date) | notes |
| --- | --- | --- | --- |
| Elliptic blocklist | `blacklist.py elliptic` | 18,134 (2026-11-06, last-modified 14:40 UTC); 17,160 the day before | tron 6,381, solana 6,188, evm 4,374, bitcoin 973, cosmos (dYdX) 102, xrp 72, near 44 |
| FBI alert | browser only (403) | 628: 608 ETH, 19 BTC, 1 SOL | not fetched yet |
| USDT/USDC freezes, Ethereum | `blacklist.py freezes --chain eth --since 2026-10-29 --until 2026-11-06` | 19 USDT + 22 USDC = 38 unique | 19 (50%) in Elliptic |
| USDT freezes, Tron | `blacklist.py freezes --chain tron ...` | 112 unique by 11-06 | 11 (10%) in Elliptic — most are unrelated |
| tayvano `hacks-and-thefts/binance.md` | `blacklist.py tayvano` | 64 (29 EVM, 29 BTC, 4 Tron, 1 SOL, 1 XRP) | 52 (81%) in Elliptic; misses are mostly Binance wallets |
| Bitquery investigation | WebFetch of `bitquery.io/investigations/binance-hack` | ~150 with roles | best role source |
| TRM / Elliptic / Hacker News articles | read | 0 addresses | narrative only |
| OFAC | — | none designated yet | re-check later |

## Victim addresses — never label these as bad

From Bitquery and the freeze logs; all are absent from Elliptic's list, as they should be.

| chain | address | what |
| --- | --- | --- |
| Ethereum | `0x28c6c06298d514db089934071355e5743bf21d60` | Binance 14 hot wallet (ran attacker code; frozen by Tether and Circle) |
| Ethereum | `0xdfd5293d8e347dfe59e90efd55b2956a1343963d` | Binance hot wallet (drained 20:24) |
| Ethereum | `0xee7ae85f2fe2239e27d9c1e23fffe168d63b4055` | Binance hot wallet, USDC source (frozen by Circle) |
| Bitcoin | `bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h` | Binance hot wallet |
| Tron | `TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf` | Binance hot wallet |
| Solana | `5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9` | Binance hot wallet |
| Tron | `TXJgMdjVX5dKiQaUi9QobwNxtSQaFqccvd` | JustLend USDT market (service, received funds) |

## Sample attacker addresses

Every one is in Bitquery (role below), Elliptic and tayvano, checked 2026-11-06.

| chain | address | role (Bitquery) | freeze |
| --- | --- | --- | --- |
| Ethereum | `0x7c8601d4645b93cea45f71e118a729332e6b5ca0` | caller wallet | — |
| Ethereum | `0x5227f603c1ee34ce3c06efe6477003bdfccb2f8c` | main receiver | USDT 21:01, USDC 21:04 |
| Ethereum | `0xa97bf7836f8a08f9ed91d41453d371493fae8d10` | second receiver | USDC 10-30 04:11 |
| Ethereum | `0x8532fa14acaf483729c449b8458aeddb900543d4` | ETH stash | — |
| Bitcoin | `bc1q0mtc2f5agpkvlq6hhahmfr3hlr55kyfjhl2mnm` | first receiver | — |
| Tron | `TG5iBMQPrDzJJAUM8GMVBf1hRaJ1wvzsGi` | first receiver, 312.7M USDT | USDT 21:09 (first Tron freeze) |
| Solana | `AffzFDKZbyMiU11zmVBoAqD25ugpr7xoWWyRyGigBEaU` | main receiver | — |
| XRP | `rK21t6nGLy4MNDqhvy3pGwcLFy25qgfzMx` | receiver, emptied 2 Nov | — |

## Lessons

- Elliptic's free CSV was the single best source: biggest, multi-chain, victims excluded.
  It has no chain or role column — join with Bitquery/tayvano for roles.
- Freeze windows need a cross-check; Tron freezes in particular are mostly noise for a
  given incident.
- The FBI list is the one authoritative source we couldn't script; fetch it via a browser
  if a government-grade label is needed.

## Links

- FBI alert: https://www.fbi.gov/investigate/cyber/alerts/2026/north-korea-responsible-for-6-billion-binance-attack
- Elliptic blocklist: https://www.elliptic.co/binance-hack-2026-blocklist/ (CSV: https://data-cdn.elliptic.co/blocklists/binance-hack-blocklist.csv)
- Elliptic analysis: https://www.elliptic.co/insights/binance-largest-hack-in-history/
- Bitquery: https://bitquery.io/investigations/binance-hack
- TRM: https://www.trmlabs.com/resources/blog/binance-hack-update-north-korea-launders-proceeds-through-self-minted-tokens-and-chained-bridges
- tayvano: https://github.com/tayvano/lazarus-bluenoroff-research/blob/main/hacks-and-thefts/binance.md
- Wikipedia: https://en.wikipedia.org/wiki/2026_Binance_hack
- ACAMS timeline: https://www.acams.org/en/opinion/binance-hack-compliance-story-four-lessons-financial-crime-teams
