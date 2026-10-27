# cryptoscamdb

- **What it is:** CryptoScamDB, a crowd-reported list of scam sites with the addresses they
  showed.
- **Access:** the API `api.cryptoscamdb.org` answered 502 on 2026-10-24, so the connector reads
  the GitHub dump: raw `CryptoScamDB/blacklist/master/data/urls.yaml` (~2 MB). Last pushed
  2023-04-29.
- **Format:** YAML list of `{name, url, category, subcategory, addresses: {ETH: [...]}}`.
- **Mapping:** each ETH address -> phishing if `category: Phishing`, else scam; trust low; site
  URL as `source_ref`; no dates.
- **Size:** 2,991 labels (2026-10-24): 2,174 scam, 817 phishing.
- **Quirks:** stale; an NDSS 2023 study found it covers well under 1% of observed scam wallets.
