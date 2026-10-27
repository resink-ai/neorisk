# Extracting addresses from web pages

Use this when a label source has no file or API, only pages (reports, scam databases, press
releases).

## First: may we?

1. Read the site's terms of use and `robots.txt`. If they forbid automated access or scraping,
   stop and tell the user; do not build a connector. (This rules out Etherscan's own label
   pages and paid vendors such as Chainalysis.)
2. Prefer any download, feed or API the site offers, even an old dump, over parsing pages.
3. Keep the rate low (`DEFAULT_RATE = 0.5` or less) and identify the client (the context's
   user agent already does).

## Extracting

- Fetch with `ctx.get(url)` so the HTML is cached under `data/eth/raw/<source>/` and the parse
  can be re-run offline.
- Parse with the standard library `html.parser` or a regex on visible text; add a dependency
  only if the page truly needs one.
- An Ethereum address is `0x` + 40 hex characters: `re.findall(r"\b0x[a-fA-F0-9]{40}\b", text)`.
  Run every hit through `tables.norm`.
- Pages often show other chains' addresses beside ETH ones (Tron `T...`, Bitcoin). Keep only
  hits in a section that says Ethereum / ERC-20, or record the chain if it's ambiguous and skip.
- Tx hashes are `0x` + 64 hex; the 40-char pattern with `\b` will not match inside them, but check.
- Every label row gets `source_ref` = the page URL (plus a heading or anchor if the page lists
  many claims) and `observed_at` = the page's publication date when it shows one.

## Hand curation instead

When a source is a handful of PDFs or articles (e.g. Huione reports), skip the parser: add rows
to a curated CSV such as `connectors/huione/seeds.csv` with a `source_url` per row.
