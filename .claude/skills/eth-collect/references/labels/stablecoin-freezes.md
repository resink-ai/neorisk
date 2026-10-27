# stablecoin-freezes

- **What it is:** addresses the USDT (Tether) and USDC (Circle) issuers froze, read from the token
  contracts' own events. Issuers freeze for sanctions, law-enforcement requests and hacks; the
  reason is not on chain.
- **Access:** explorer `getLogs` (etherscan with a key, else keyless blockscout), one query per
  token over the window, split when a page hits 1,000 logs.
- **Events (topic0 verified against live logs 2026-10-24):**

| token | contract | event | topic0 | frozen address |
| --- | --- | --- | --- | --- |
| USDT | 0xdac17f958d2ee523a2206206994597c13d831ec7 | AddedBlackList(address) | 0x42e160154868087d6bfdc0ca23d96a1c1cfa32f1b72ba9ba27b69b98a0d819dc | last 20 bytes of `data` |
| USDC | 0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48 | Blacklisted(address indexed) | 0xffa4e6181777692565cf28528fc88fd1516ea86b56da075235fa575af6a4b855 | last 20 bytes of topic 1 |

- **Mapping:** `frozen`, trust high, `observed_at` = block date of the event (`date_known` true);
  an address frozen twice keeps its first date. `source_ref` names the token and freeze tx.
- **Size:** about 650 USDT and 530 USDC freezes in the 12 months to 2026-10-24.
- **Not yet:** unfreezes (`RemovedBlackList`, `UnBlacklisted`) are not read, so an address
  later unfrozen keeps its label.
