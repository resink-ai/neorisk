# huione

- **What it is:** Huione Group (Cambodia), named a primary money laundering concern by FinCEN
  under section 311; the [final rule](https://www.federalregister.gov/documents/2025/10/16/2025-19571/imposition-of-special-measure-regarding-huione-group-as-a-foreign-financial-institution-of-primary)
  was published 2025-10-16, effective 2025-11-17. Covers Huione Pay, Huione Guarantee
  (Haowang), Huione Crypto; a June 2026 proposal would add H-Pay Service PLC.
- **Access:** no public bulk address list was found (2026-10-24). Neither the rule nor the
  proposal lists addresses in the text checked. Elliptic labels hundreds of Huione addresses
  but sells them. Most Huione flow is USDT on Tron, not Ethereum.
- **Format:** hand-curated `apps/ethcollect/src/ethcollect/connectors/huione/seeds.csv`:
  `address,chain,claim,source_url,observed_at`. Only `chain=ethereum` rows load; a row without
  `source_url` is rejected.
- **Mapping:** sanctioned, trust high, `observed_at` from the row.
- **How to add rows:** take an address only from a page that states it belongs to Huione
  (court filings, government notices, investigators' published reports, Tether freeze notices).
  Put that page in `source_url` and its publication date in `observed_at`. Tron addresses can
  go in with `chain=tron` for later; they are skipped for now.
- **Use:** treat as an evaluation case, not a training class, until there are 20+ active
  Ethereum addresses.
