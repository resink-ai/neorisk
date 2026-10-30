# lazarus

- **What it is:** [tayvano/lazarus-bluenoroff-research](https://github.com/tayvano/lazarus-bluenoroff-research),
  a security researcher's notes on DPRK (Lazarus, TraderTraitor, Contagious Interview…) hacks
  and thefts, one markdown file per incident. CC0.
- **Access:** one GitHub API call for the tree, then one raw file per incident under
  `hacks-and-thefts/` and `more-hacks-and-thefts/` (~320 files, ~90 s at 5 calls/s; cached).
- **Mapping:** `hack`. Trust **medium** when the line or its heading says what the address did
  (exploiter, theft, hacker, laundering, Tornado, bridge…), else **low**. `observed_at` from a
  date in the file name when there is one (`date_known` true), else today (`date_known` false).
  `source_ref` = file path + the line (first 120 characters). An address in several files keeps
  its highest-trust row.
- **Dropped:** lines or sections that name victims or services (cold/hot wallet, signer, Safe,
  exchange, deposit/"Depo", token, router, returned, seized, "Amt Stolen"…), lines on other
  chains (BNB, Polygon, Arbitrum, bscscan…), tx hashes (64 hex). Skipped file:
  `pulsex-provex-richard-heart.md` (where PulseX sacrifice funds went; not a theft).
- **Size:** 7,541 addresses (3,265 medium, 4,276 low) on 2026-10-27. Largest: WazirX 658,
  Poloniex 614, Ronin 399, HTX/HECO 354, Upbit 231.
- **Quirks:** free-form notes, so the filter is a heuristic: it errs on dropping (e.g. HTX's
  "Tornado Cash Depositors" list goes, because of "deposit"). Before relying on a file, read its
  section headings. 3 addresses overlap eth-labels service labels (a Bancor deployer, Chainflip,
  a Tornado router); service labels win in the model's candidate filter. `atomic_wallet.md`'s
  big list is victims ("Amt Stolen") and is dropped by heading.
