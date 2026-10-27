# huione

Huione Group (FinCEN 311), hand-curated seeds.csv with a source URL per row.

```sh
uv run eth-collect huione --help
uv run eth-collect huione --limit 10   # quick check
```

Source details, field mapping and known quirks: `.claude/skills/eth-collect/references/labels/huione.md`.

## Adding addresses

Edit `seeds.csv` (`address,chain,claim,source_url,observed_at`). Add an address only when a
public page states it belongs to Huione Group, and put that page in `source_url`; rows without
one are rejected. Use `chain=ethereum` (others are kept for later but skipped).
