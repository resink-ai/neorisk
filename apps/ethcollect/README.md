# ethcollect

Ethereum data collection for the bad-address model. Each source is a connector in
`src/ethcollect/connectors/<source>/`; all of them write three shared tables under `data/eth/`
(git-ignored). The agent drives it through the `eth-collect` skill
(`.claude/skills/eth-collect/`), whose references hold the per-source knowledge.

```sh
uv run eth-collect --help                       # every connector, with its one-line summary
uv run eth-collect ofac                         # one connector
uv run eth-collect labels                       # every label connector
uv run eth-collect blockscout --address 0x...   # history of one address, no key
uv run eth-collect sample toy                   # the toy set: ~1,000 addresses, capped history
uv run eth-collect status                       # last runs, table sizes, toy-sample checks
uv run eth-collect new-source chainabuse --kind label
```

Shared options on every connector: `--since/--until` (default: the last 365 days), `--limit N`
for a quick check, `--out`, `--refresh` to bypass the raw cache, `--rate` calls per second.

Layout of `data/eth/`:

| path | what |
| --- | --- |
| `labels/<source>.parquet`, `transfers/<source>.parquet`, `addresses/<source>.parquet` | each source's rows, replaced or appended by its own runs |
| `raw/<source>/` | every response as fetched; reruns read from here |
| `runs/<source>-<time>.json` | options, counts, warnings and errors of each run |
| `samples/toy/` | the capped toy set + `manifest.json`, what the modeling side reads |

Secrets come only from the environment (`ETHERSCAN_API_KEY`, `ETH_RPC_URL`) and are stripped
from cache keys and run records. Keep them in the git-ignored `.env` and run
`uv run --env-file .env eth-collect ...`; `ETHERSCAN_RATE` there sets Etherscan's calls per
second (default 2).
