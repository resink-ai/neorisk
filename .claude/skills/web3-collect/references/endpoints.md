# Free endpoints: what works and what doesn't

Tested 2026-11-05/06 from this machine. Limits change; when one fails, read the error body —
providers say what they want.

## Ethereum logs (freeze events over a date range)

| endpoint | result |
| --- | --- |
| `eth.blockscout.com/api?module=logs&action=getLogs` | **works keyless**, a week of logs in one call; ~10 calls per half hour on bursts, 1000 logs per page (the script splits ranges) |
| `api.etherscan.io/v2/api` (`chainid=1`) | works with `ETHERSCAN_API_KEY`; the repo's `.env` has the variable but it was empty |
| `ethereum-rpc.publicnode.com` `eth_getLogs` | 403 "Archive requests require a personal token" for blocks a week old |
| `cloudflare-eth.com` | max 800-block range, then frequent `Internal error` / `Cannot fulfill request` |
| `eth.drpc.org` | "ranges over 10000 blocks are not supported on free plan" even for 2048 blocks |
| `1rpc.io/eth` | 50-block range limit |
| `eth.llamarpc.com` | HTTP 525 |
| `eth.merkle.io` | rate limited immediately |

Blocks for a date: Blockscout/Etherscan `module=block&action=getblocknobytime`.

## Ethereum current state (`eth_call`, freeze status)

`ethereum-rpc.publicnode.com` works keyless for latest-state calls; send a `user-agent`
header — without it some requests 403.

## Tron

| endpoint | result |
| --- | --- |
| `api.trongrid.io/v1/contracts/<contract>/events?event_name=AddedBlackList&min_block_timestamp=…` | **works keyless**; 200 per page, follow `meta.links.next`; timestamps in ms |
| `api.trongrid.io/wallet/triggerconstantcontract` | works keyless but 429 after ~4 quick calls; pace 1.5 s or use `TRON_PRO_API_KEY` |

TronGrid event results give addresses as `0x` + 20-byte hex. Convert: prefix `41`, append the
first 4 bytes of double SHA-256, base58-encode (`tron_from_hex` in the script).

## Web pages

| page | result |
| --- | --- |
| fbi.gov alerts | 403 to curl (even with a browser UA) and to WebFetch; use a real browser |
| archive.org Wayback availability API | 429 when tried |
| etherscan.io address pages | 403 |
| chainabuse.com address pages | 308 redirect into a bot wall |
| sanctionslist.ofac.treas.gov SDN CSV | 403 to plain curl; `eth-collect ofac` has the working path |
| elliptic.co blocklist page and `data-cdn.elliptic.co` CSV | 200, no auth |
| bitquery.io investigations | 200 via WebFetch |
| GitHub raw / `gh api` | fine |

## Shell pitfalls hit

- The user's shell is zsh: `$var` holding several words is **not** word-split, and a
  `?` in an unquoted URL is a glob (`no matches found`). Quote URLs; pass arguments
  explicitly instead of `set -- $t`.
- `"…$2000000…"` in zsh is positional parameter 2000000, not `$2` then zeros ("number
  truncated after 19 digits"); write `${2}`, or better, build JSON payloads in Python.
- Run downloaded-data scripts with `python3 -I` from a directory you control.
