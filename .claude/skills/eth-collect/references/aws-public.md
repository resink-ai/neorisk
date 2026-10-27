# aws-public

- **What it is:** AWS Public Blockchain Data, daily Ethereum tables as Parquet
  ([registry](https://registry.opendata.aws/aws-public-blockchain/)).
- **Access:** `s3://aws-public-blockchain/v1.0/eth/<table>/date=YYYY-MM-DD/*.parquet`, region
  `us-east-2`, anonymous (no account, `--no-sign-request`). Updated daily.
- **Tables (checked 2026-10-24):** blocks, contracts, logs, token_transfers, traces,
  transactions, from 2015-08-07 to yesterday.
- **Size:** one day of `transactions` is one ~820 MB file, ~2M rows in 7 row groups;
  `token_transfers` ~480 MB. Values are DOUBLE (wei), timestamps naive UTC.

## Columns used

| table | columns | becomes |
| --- | --- | --- |
| transactions | hash, block_number, block_timestamp, from_address, to_address, value, receipt_status | external transfers (value / 1e18 ETH) |
| token_transfers | transaction_hash, log_index, block_number, block_timestamp, from_address, to_address, value, token_address | erc20 transfers; USDT/USDC scaled by 1e6, others raw (no decimals in this table) |

`input` (calldata) is deliberately not read: it is most of the bytes, so `method_id` is null for
this source.

**token_transfers stores `from_address` / `to_address` as 32-byte log topics**
(`0x` + 24 zeros + the address). The connector strips the padding (`unpad`); `tables.norm`
alone would reject them. `token_address` is a plain address.

## Bytes per day (Parquet footers, 2026-10-20)

| table | column | MB |
| --- | --- | --- |
| transactions (1.8M rows) | input 573, hash 117, from 55, to 29, value 6, the rest small | ~850 total |
| token_transfers (6.3M rows) | transaction_hash 281, to 149, from 143, value 31, block/ts/log_index ~10 each, token 9 | ~700 total |

## `--mode scan`: history without an explorer

The keyless RPC cannot search logs (refused even 30 days back) and keyless Blockscout allows
about 10 calls per half hour, so per-address history needs Etherscan. Scan mode flips the
lookup: read whole days, cheap columns only (~90 MB of transactions + ~360 MB of token
transfers, no hash columns), and keep the rows that touch

- a **risk-labeled** address (service labels are not watched: exchanges alone are ~760k rows a
  day), or
- a **random** address, picked by `crc32(seed:address) < rate`, so the same address is picked on
  every day it appears (default rate 1/5000, ~400 picks a day across both tables).

Each address keeps its latest `--cap` rows, per day (cached as small Parquet under
`raw/aws-public/`, keyed by the watch list, so new labels mean a re-read) and again across days.
External transactions then get their hash from the RPC
(`eth_getTransactionByBlockNumberAndIndex`, 50 per batch). Token rows keep `tx_hash` null: the
RPC does not serve old receipts and the hash column would triple the read. They are identified
by `(block_number, log_index)`, which is why `block_number` is in the transfers key.

Days are one random day per equal slice of the window (`--days`, default 12; the toy uses 30).
Measured: ~85-110 s per day, ~2.5 GB peak memory per day in flight, `--workers 2` by default.
A day had 30-60 risk addresses active in transactions and 40-115 in token transfers.

## Speed (measured from the user's laptop, 2026-10-24; better since 2026-10-26)

Remote reads ran at roughly 0.4 MB/s; after a network fix on 2026-10-26, a single stream ran at
~2.3 MB/s and pyarrow's parallel whole-file reads at ~4-6 MB/s. Timings below are from before. One row group of `from_address,to_address` took ~6-12 s;
`hash` alone ~60 s; a full-day `logs` scan did not finish in 10 minutes. Hence:

- `--mode addresses` (the sampling use) reads one random row group per day, two columns.
- `--mode transfers` reads one row group per day of each table; expect ~4 minutes per day.
- Never scan whole days remotely (e.g. filtering `logs` by contract); use an explorer's
  `getLogs` for that. Bulk history belongs to BigQuery or a machine in us-east-2.

Each extract is cached as Parquet under `data/eth/raw/aws-public/`, so reruns are instant.
