# mew-darklist

- **What it is:** MyEtherWallet's `addresses-darklist.json` in
  [MyEtherWallet/ethereum-lists](https://github.com/MyEtherWallet/ethereum-lists): addresses that
  should carry a warning (impersonators, fake giveaways, phishing collectors).
- **Access:** raw GitHub `master/src/addresses/addresses-darklist.json`.
- **Format:** `[{"address", "comment", "date"}]`.
- **Mapping:** scam, trust low, `observed_at` = `date` when it parses (616 of 652 do), comment
  kept as `source_ref`.
- **Size:** 652 addresses (2026-10-24).
- **Quirks:** mostly 2017-2021; the README says it "may not always be up to date". Few will be
  active in a recent window.
