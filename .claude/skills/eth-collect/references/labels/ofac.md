# ofac

- **What it is:** Ethereum addresses on the US Treasury OFAC SDN list, extracted nightly from the
  official SDN XML by [0xB10C/ofac-sanctioned-digital-currency-addresses](https://github.com/0xB10C/ofac-sanctioned-digital-currency-addresses).
- **Access:** `https://raw.githubusercontent.com/0xB10C/ofac-sanctioned-digital-currency-addresses/lists/sanctioned_addresses_ETH.txt`, no key.
- **Format:** one checksummed address per line. No dates, no entity names.
- **Mapping:** every line -> `sanctioned`, trust high, `date_known` false.
- **Size:** 120 addresses (2026-10-24).
- **Quirks:** no designation date, so `observed_at` is the fetch date. For the date and entity,
  look the address up in the SDN XML (not automated yet). Tornado Cash was delisted on
  2025-03-21 and no longer appears.
