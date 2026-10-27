# forta

- **What it is:** [forta-network/labelled-datasets](https://github.com/forta-network/labelled-datasets),
  Ethereum mainnet files built from Etherscan and Luabase tags.
- **Access:** raw GitHub, branch `main`, three CSVs under `labels/1/`. Each file is recognised by
  its header, not its name:

| header starts with | rows | mapping |
| --- | --- | --- |
| `address,etherscan_tag,etherscan_labels,is_contract` | phishing wallets | kind from `etherscan_labels` + tag |
| `contract_address,contract_tag,contract_creator,...` | malicious contracts | contract **and** its creator, kind from `contract_creator_etherscan_label` |
| `banned_address,wallet_tag,data_source` | Etherscan malicious labels | kind from tag + data source |

- **Kind rule:** "phish" -> phishing; exploit/heist/hack/attacker/drainer -> hack; else scam.
  Trust medium, no dates.
- **Size:** 7,904 labels (2026-10-24): 7,530 phishing, 354 hack, 20 scam.
- **Quirks:** last meaningful update is old; many addresses are inactive. Fake_Phishing tags are
  Etherscan's and include some false positives.
