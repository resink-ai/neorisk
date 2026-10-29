# defihacklabs

- **What it is:** [SunWeb3Sec/DeFiHackLabs](https://github.com/SunWeb3Sec/DeFiHackLabs), Foundry
  reproductions of DeFi exploits, one file per incident under `src/test/<YYYY-MM>/`. Apache-2.0.
- **Access:** one GitHub API call for the tree (`git/trees/main?recursive=1`), then one raw file
  per incident (about 900 files, ~3.5 minutes at 5 calls/s; cached after).
- **Mapping:** the `@KeyInfo` comment lines `Attacker`, `Attacker EOA`, `Attack Contract`,
  `Exploit Contract`, `Exploiter` with an `etherscan.io/address/` link → `hack`, trust medium,
  `observed_at` = first day of the incident's month folder (`date_known` true). `source_ref` is
  the file path plus which line it came from.
- **Skipped:** links to other explorers (bscscan, basescan, arbiscan…: other chains) and
  `Vulnerable Contract` / `Victim` lines (those are the victims).
- **Size:** 308 addresses from 179 Ethereum incidents out of 915 files (2026-10-27); most since
  2023.
- **Quirks:** the header format is a convention, not a schema; a few files spell it differently
  and are missed. Attack contracts are often single-use, so their own histories are short; the
  attacker EOA is the more useful seed.
