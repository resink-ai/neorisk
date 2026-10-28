# etherscan and blockscout (Etherscan-compatible explorer APIs)

Both connectors share `connectors/explorer.py` and `connectors/history.py`; only the base URL
and the key differ. `stablecoin-freezes` uses the same client for `getLogs`.

| | etherscan | blockscout |
| --- | --- | --- |
| base | `https://api.etherscan.io/v2/api` (+ `chainid=1`) | `https://eth.blockscout.com/api` |
| key | `ETHERSCAN_API_KEY` (free: https://etherscan.io/myapikey) | none |
| limit | free tier 3 calls/s, 100,000/day ([docs](https://docs.etherscan.io/rate-limits)) | keyless: about 10 calls, then HTTP 429 with `x-ratelimit-reset` of ~30 minutes (observed 2026-10-24) |
| default `--rate` | `$ETHERSCAN_RATE`, else 2.0 | 1.0 |

Every Etherscan call (`etherscan`, `stablecoin-freezes --via etherscan`, `sample --history
etherscan`) is paced at `ETHERSCAN_RATE` calls per second, set in the environment or `.env`
(e.g. `ETHERSCAN_RATE=1` on a key shared with another machine, `5` on a paid plan); `--rate`
on the command line wins over it. The quota is per key, so two machines using one key share it:
on 2026-10-27 one client at 1 call/s still got 3 of 12 calls refused.

`--history auto` / `--via auto` pick etherscan when the key is set, else blockscout. Keyless
Blockscout is only good for a handful of addresses or a one-off check.

## Calls per address

`txlist`, `txlistinternal`, `tokentx`, each `sort=desc&page=1&offset=<--per-kind>` between the
window's blocks (`getblocknobytime` twice per run, cached). 3 calls per address.

## Field mapping

| action | fields | row |
| --- | --- | --- |
| txlist | hash, from, to, value (wei), isError, methodId / input[:10] | external, log_index -1, ETH |
| txlistinternal | transactionHash, from, to, value, isError, index or traceId | internal, log_index = index |
| tokentx | hash, from, to, value, contractAddress, tokenDecimal, tokenSymbol, logIndex | erc20, amount scaled by tokenDecimal |

## Answers and errors

- `{"status":"0","message":"No transactions found","result":[]}` is an empty result, not an
  error.
- `status 0` with a string result raises, and the body is dropped from the cache so a rerun
  retries. The exception is Etherscan's per-second limit (`NOTOK: Max calls per sec rate limit
  reached (3/sec)`, sent with HTTP 200), which is retried in place up to 5 times with 1-16 s
  back-off and counted as `retries` in the run record. The daily limit and `Invalid API Key`
  are not retried.
- `getLogs` returns at most 1,000 logs per call; a full page makes the client split the block
  range in four and retry each part.
- Etherscan pages cap at 10,000 results (`page x offset`); the toy only needs the newest few, so
  the cap does not bite. For full histories, walk `startblock` forward instead of paging.
- Blockscout's `txlistinternal` may answer `"Some internal transactions within this block range
  have not yet been processed"` with a partial list; it is kept.
