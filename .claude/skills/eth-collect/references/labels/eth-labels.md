# eth-labels

- **What it is:** [dawsbot/eth-labels](https://github.com/dawsbot/eth-labels), a public copy of
  Etherscan's account labels across EVM chains.
- **Access:** `https://raw.githubusercontent.com/dawsbot/eth-labels/v1/data/csv/accounts.csv`
  (~12 MB; also `data/json/accounts.json` and `data/db.sqlite3`).
- **Format:** `address,chainId,label,nameTag`. 144k rows, 113k on chain 1.
- **Mapping (`classify`):** only chain 1; most labels (genesis, charity, token contracts,
  airdrop-hunter, ...) are skipped.

| label | kind | trust |
| --- | --- | --- |
| ofac-sanctions-lists, ofac-sanctioned | sanctioned | high |
| contains "phish", or nameTag Fake_Phishing | phishing | medium |
| *-exploit, exploit, heist, phish-hack, nameTag "exploiter" | hack | medium |
| tornado-cash, mixer, ethereum-mixer | mixer (service) | medium |
| known exchange names (EXCHANGES), *-exchange | exchange (service) | medium |
| bridge, *-bridge (not bridged-token), allbridge, debridge, ... | bridge (service) | medium |
| dex, uniswap, sushiswap, balancer, curve-finance, ... | dex (service) | medium |

- **Size:** 40,910 labels (2026-10-24), mostly exchange (30,634) and dex (9,517); 253 hack,
  93 sanctioned, 66 mixer, 29 phishing.
- **Quirks:** bitget alone is ~19k exchange addresses (deposit addresses). Services are context
  for the model, never "good" labels. Extend the name sets when a new exchange shows up in
  `status` as unlabeled but busy.
