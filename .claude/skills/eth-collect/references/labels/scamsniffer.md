# scamsniffer

- **What it is:** [scamsniffer/scam-database](https://github.com/scamsniffer/scam-database),
  ScamSniffer's open phishing blacklist. GPL-3.0.
- **Access:** raw GitHub `main/blacklist/all.json` (`{"address": [...], "domains": [...]}`; the
  address list is a superset of `address.json`) and `blacklist/combined.json` (phishing domain →
  the addresses its drainer paid out to; the domain goes into `source_ref`). `domains.json` and
  the dated `blacklist/archive/*.json` snapshots hold domains only and are not used.
- **Mapping:** phishing, trust medium, no dates (`date_known` false).
- **Size:** 4,681 addresses (2026-10-27; `address.json` alone had 2,530).
- **Quirks:** the open copy is delayed 7 days; real time is a paid API ($999/month). Mostly
  drainer and fake-airdrop receivers; chain not stated, so some may be other EVM chains.
