# etherscan-extras

ETH balance, first funder and NFT transfers per address from Etherscan V2; needs
ETHERSCAN_API_KEY.

```sh
uv run eth-collect etherscan-extras --help
uv run eth-collect etherscan-extras --addresses data/eth/work/risk_addresses.parquet --limit 10
uv run eth-collect etherscan-extras --addresses <file> --parts funder   # one part only
```

Source details, field mapping and known quirks: `.claude/skills/eth-collect/references/etherscan.md`.
