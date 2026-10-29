# stablecoin-freezes

- **What it is:** addresses the USDT (Tether) and USDC (Circle) issuers froze, read from the token
  contracts' own events. Issuers freeze for sanctions, law-enforcement requests and hacks; the
  reason is not on chain.
- **Access:** explorer `getLogs` (etherscan with a key, else keyless blockscout), one query per
  token from 2017-11 (USDT's launch) unless `--since` is given, split when a page hits 1,000 logs.
- **Events (topic0 verified against live logs 2026-10-24):**

| token | contract | event | topic0 | frozen address |
| --- | --- | --- | --- | --- |
| USDT | 0xdac17f958d2ee523a2206206994597c13d831ec7 | AddedBlackList(address) | 0x42e160154868087d6bfdc0ca23d96a1c1cfa32f1b72ba9ba27b69b98a0d819dc | last 20 bytes of `data` |
| USDC | 0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48 | Blacklisted(address indexed) | 0xffa4e6181777692565cf28528fc88fd1516ea86b56da075235fa575af6a4b855 | last 20 bytes of topic 1 |
| EURC | 0x1abaea1f7c830bd89acc67ec4af516284b1bc33c | Blacklisted(address indexed) | same as USDC | topic 1 |
| USDP, BUSD, PYUSD, PAXG (Paxos) | 0x8e870d…, 0x4fabb1…, 0x6c3ea9…, 0x458048… | AddressFrozen(address indexed) | 0x90811a8edd3b3c17eeaefffc17f639cc69145d41a359c9843994dc2538203690 | topic 1 |

Checked and absent (2026-10-27): USDG (Paxos, no AddressFrozen logs), TUSD (no `Blacklisted`
logs under either signature). An issuer freezing its own contract (one USDP event) is skipped.

- **Mapping:** `frozen`, trust high, `observed_at` = block date of the event (`date_known` true);
  an address frozen twice keeps its first date. `source_ref` names the token and freeze tx.
- **Size:** 3,813 addresses all time (2026-10-27, via etherscan): USDT 3,179, USDC 906, EURC
  631, PAXG 291, BUSD 266, USDP 167, PYUSD 158 events; the non-USDT/USDC issuers add only 111
  new addresses. USDT/USDC alone were 3,702; about 650 USDT and
  530 USDC freezes in the 12 months to 2026-10-24.
- **Not yet:** unfreezes (`RemovedBlackList`, `UnBlacklisted`) are not read, so an address
  later unfrozen keeps its label.
