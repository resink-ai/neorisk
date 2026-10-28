# devicefp

Device fingerprinting model. It embeds device profiles (user-agent, screen, GPU, network, VPN
use, battery, ...) so that observations of the same or similar devices are close in euclidean
distance and different devices are far apart.

Status: workspace only, no model yet. Data sources are surveyed in
[docs/research/device-fingerprint-data-sources.md](../../docs/research/device-fingerprint-data-sources.md).
Local data goes in `data/devicefp/` (gitignored, like `data/eth/`).
