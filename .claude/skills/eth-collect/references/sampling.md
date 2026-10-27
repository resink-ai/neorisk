# The toy sample

`uv run eth-collect sample toy` builds about 1,000 addresses (300 labeled seeds + 700 random) and
their latest 5 transfers each, from the last 12 months, into `data/eth/samples/toy/`:
`addresses.parquet`, `transfers.parquet`, `labels.parquet`, `manifest.json`.

Two ways to get history, picked by `--history` (`auto` = etherscan when `ETHERSCAN_API_KEY`
is set, else `aws-scan`):

**`--history aws-scan`** (no key): one `aws-public --mode scan` pass over `--days` whole days
(default 30, one per equal slice of the 12 months). It keeps every row touching a risk-labeled
address plus hash-picked random addresses, capped per address (see `aws-public.md`). Seeds are
the risk addresses that showed up, in `seed_candidates` order; background is a random 700 of
the picked addresses. Then steps 4-5 below. About 30-45 minutes, no API calls except RPC for
hashes and contract flags. What it means for the data: an address's "latest 5" are its latest
on the scanned days, not overall; dormant labeled addresses never become seeds; no internal
transfers; token rows have no tx_hash.

**`--history etherscan|blockscout`** (explorer):


1. Every label connector (skip with `--skip-labels`).
2. **Seeds:** risk labels only (never services), interleaved across label kinds so no one list
   dominates, dated labels first. History is pulled 50 candidates at a time until `--seeds`
   are active in the window or `4 x --seeds` candidates were tried. Most crowd-reported phishing
   addresses are years old and inactive, so expect to try 2-4 candidates per active seed.
3. **Background:** `aws-public --mode addresses` on 12 random days, then history for each.
4. **Cap:** each sampled address keeps its latest `--cap` (default 5) transfers in or out.
   Counterparties are listed as `counterparty` addresses but not expanded.
5. **Contract flags** for sampled addresses and counterparties over `rpc`.

Cost with the defaults: seeds about 3 calls x (300 to 1,200 candidates), background about
3 x 700 calls. On Etherscan's free tier (3/s) that is roughly 15 to 30 minutes; keyless
Blockscout cannot do it (about 10 calls per half hour). The AWS step reads 12 small row-group
extracts (a few MB each), about 10 s per day.

Options: `--seeds`, `--background`, `--cap`, `--history auto|aws-scan|etherscan|blockscout`, `--days`, `--seed`
(random seed; same seed + same cache = same sample).

## Reading the checks in `status`

- **per sampled address**: how many of the 1,000 got any transfer; median should be near
  `--cap`. Many with fewer means inactive addresses got in.
- **risk-labeled sampled addresses**: seeds plus any random address that happens to be labeled.
  Background addresses with risk labels are interesting: they were not chosen for the label.
- **transfers after a label's observed_at**: activity after the flag date; the model must drop
  these to avoid learning from the future.
- **contracts / unknown**: unknown means the rpc step did not run or failed.
