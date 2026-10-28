# Data sources for the device fingerprinting model

Survey date: 2026-10-28. Goal: find every public source of **device profiles**
(user-agent, screen, GPU, fonts, battery, network, VPN/proxy, sensors, …) and
**device identifiers** (device IDs, IMEI/TAC, MAC/OUI, TLS/TCP fingerprints) that
could train or support a model that embeds device profiles so that the same or
similar devices land close together in euclidean space.

Status column: **verified** = page fetched or confirmed by search this session;
**known** = from prior knowledge, not re-checked this session.

## What the model needs, and why it shapes this list

A metric-learning model (triplet / contrastive / proxy loss) needs **positive
pairs**: two observations known to come from the same device. Most public data
has attributes but no stable device label, so the sources fall into four tiers:

| Tier | Use | Scarcity |
|---|---|---|
| A. Multi-attribute profiles **with** a device/browser/user identity | Direct training and evaluation (positive pairs, drift over time) | Rare, small |
| B. Profiles or distributions **without** identity | Realistic marginals/joints for a synthetic generator; negatives | Plentiful |
| C. Lookup/enrichment databases | Turn raw strings (UA, JA4, IP, TAC) into structured features | Plentiful |
| D. Bot / spoofing labels | Hard negatives, "lying device" detection | Rare |

## A. Profiles with an identity label (positive pairs)

| Source | What's in it | Size | Access | Status |
|---|---|---|---|---|
| [FP-Stalker](https://github.com/Spirals-Team/FPStalker) (Vastel et al., IEEE S&P 2018) | Browser fingerprints collected by the AmIUnique extension, **linked to a browser instance over time** — the canonical dataset for fingerprint evolution/linking | Paper: 98,598 fps from 1,905 browsers over 2 years; repo ships a 15k random sample (`tableFingerprints.sql`) | Repo, AGPL-3.0 (no separate data licence stated) | verified |
| [Berke et al., "How Unique is Whose Web Browser?"](https://arxiv.org/abs/2410.06954) (PoPETs 2025) | Browser attributes + demographics (gender, age, income, race) + survey answers; also a data-collection tool | 8,400 US participants, Dec 2023, one snapshot per person | [aberke/fingerprinting-study](https://github.com/aberke/fingerprinting-study) `/data`, gated: researchers accept terms of use | verified |
| [AmIUnique](https://amiunique.org/fingerprint) (Univ. Lille / Inria) | Largest academic browser-fingerprint corpus (~4.5M fps per site counter); extension users give longitudinal data | ~4.5M | No public dump. Aggregate stats public; raw data on request: browser-fingerprinting@univ-lille.fr | verified |
| [FP-Scanner](https://www.usenix.org/system/files/conference/usenixsecurity18/sec18-vastel.pdf) (USENIX Sec 2018) | Labelled fingerprints of genuine vs. **spoofed** (countermeasure-altered) browsers | small | Paper says released for reproducibility; location not confirmed | verified (claim), link not found |
| [MSMDF](https://zenodo.org/records/15554712) (TU Berlin, 2025) | Motion-sensor (accelerometer/gyroscope) raw data + fingerprints labelled by phone | 1,200 samples, 42 smartphones | Zenodo | verified |
| [Google Smartphone Decimeter Challenge 2023–24](https://www.kaggle.com/competitions/smartphone-decimeter-2023) | Gyro/IMU/GNSS logs from several phone models in identical mounts; used for phone-model identification (≈99% from 1–2 s of gyro) | Kaggle competition | Kaggle | verified (via paper citing it) |
| [UNSW IoT traces](https://iotanalytics.unsw.edu.au/) | PCAPs from a smart-home lab, CSV mapping MAC → device | 28 IoT devices, ~6 months | Public, academic | verified (via survey) |
| [UNSW HomeNet](https://researchprofiles.canberra.edu.au/en/publications/unsw-homenet-a-network-traffic-flow-dataset-for-ai-based-smart-ho/) | Network flows labelled by device | >200M flow records, 105 IoT + non-IoT devices | Academic | verified |
| [CIC IoT 2022](https://www.unb.ca/cic/datasets/iotdataset-2022.html) | Device traffic in power-on / idle / interaction states, for device profiling | ~60 devices | Free with registration | verified |
| [TalkingData Mobile User Demographics](https://www.kaggle.com/c/talkingdata-mobile-user-demographics) | `device_id` → phone brand, model, app events, geolocation, gender/age | ~187k devices, 1 week (May 2016) | Kaggle | verified |
| TalkingData AdTracking Fraud | Clicks with `ip`, `app`, `device`, `os`, `channel`, and an is-fraud label; `device`/`os` are coded IDs | ~200M clicks | Kaggle | known |
| Avazu CTR | `device_id`, `device_ip`, `device_model`, `device_type`, `device_conn_type` (hashed) | ~40M rows | Kaggle | known |

**Note on IEEE-CIS Fraud Detection** ([Kaggle / IEEE DataPort](https://ieee-dataport.org/documents/ieee-cis-fraud-detection)):
its `train_identity` table has `DeviceType`, `DeviceInfo` and `id_12`–`id_38`
(id_30 ≈ OS, id_31 ≈ browser, id_33 ≈ screen resolution, plus several masked
proxy/network flags), joined on `TransactionID` to ~590k transactions, ~144k with
identity rows (verified that the columns exist; meanings are known from the
competition forum, not re-checked). No device ID, but card/address/email columns
let you build "probably same user" pseudo-pairs. Likely the best real-world
fraud-context device table available.

**Bank Account Fraud (BAF, NeurIPS 2022)** has `device_os` (5 values),
`keep_alive_session`, `session_length_in_minutes`, `device_distinct_emails_8w`,
`device_fraud_count` — coarse, synthetic-from-real, but labelled for fraud
(verified via HF mirror schema).

## B. Profiles / distributions without identity (for generation and priors)

| Source | What's in it | Access | Status |
|---|---|---|---|
| [intoli/user-agents](https://github.com/intoli/user-agents) | **Joint** records of UA + platform + screen size + viewport + `navigator.connection` (downlink, effectiveType, rtt) + vendor, weighted by real traffic, rebuilt daily | npm package, BSD-2 | verified |
| [Browser traffic volume database](https://zenodo.org/records/15170958) (Zenodo, 2025) | User-agent traffic volume per UA per day (`agentgraph.sql.gz`, 1.2 GB) | CC BY 4.0 | verified |
| [WhatIsMyBrowser UA database](https://developers.whatismybrowser.com/useragents/) | >410M parsed user agents | API (commercial for bulk) | verified |
| [random-user-agent](https://pypi.org/project/random-user-agent/1.0.1/), [simple-useragent](https://github.com/Lennolium/simple-useragent/releases) | 326k+ real UAs bundled; daily-refreshed lists | PyPI | verified |
| [Cloudflare Radar API](https://radar.cloudflare.com/) | Share of traffic by OS, browser, device type (desktop/mobile/other), bot vs. human, HTTP version, per country, over time | Free API token | verified (via SDK docs) |
| [Firefox Public Data Report — hardware](https://data.firefox.com/dashboard/hardware) | CPU vendor/cores, RAM, GPU vendor/model, screen resolution, OS/arch shares from telemetry | Public dashboard + data | verified (older articles) |
| Steam Hardware & Software Survey | Monthly GPU, CPU, RAM, resolution, OS, language shares | Public web page | verified (older articles) |
| [Google Play device catalog](https://support.google.com/googleplay/android-developer/answer/1727131) | Every certified Android model: model code, RAM, SoC, GPU, screen size/density, ABIs, SDK levels | CSV export from Play Console (needs a developer account) | verified |
| HTTP Archive / Chrome UX Report | Device-class and connection-type distributions for real Chrome users | BigQuery, public | known |

## C. Lookup and enrichment databases

**User-agent / client-hint → device**
- [Matomo device-detector](https://github.com/matomo-org/device-detector) — regex DB for browser, OS, device type, **brand and model**; LGPL-3; Python/Go/Ruby/Java ports. Verified.
- uap-core / ua-parser (Apache-2) — the BrowserScope regexes. Known.
- [handset-detect](https://www.npmjs.com/package/handset-detect) — free subset of HandsetDetection (35k devices, 3.2k vendors). Verified.
- Commercial: 51Degrees (has a free "Lite" tier), WURFL (ScientiaMobile), DeviceAtlas. Known.

**TLS / HTTP / TCP / DHCP fingerprints**
- [JA4+ database](https://ja4db.com/) — JA4/JA4S/JA4H/JA4X/JA4T… mapped to application, library, OS; JSON download at `ja4db.com/api/download/`; `pip install ja4plus[lookup]`. Verified. The strongest network-layer device signal: it shows whether the "Chrome on Windows" UA really comes from Chrome's TLS stack.
- abuse.ch SSLBL JA3 list — malware JA3s. Verified (through Satori).
- [Satori](https://www.github.com/xnih/satori) — passive fingerprints for DHCP, TCP, HTTP UA/Server, SMB, TLS. Verified.
- [p0f v3](https://lcamtuf.coredump.cx/p0f) — passive TCP/IP OS signatures (TTL, MSS, window, options). Signatures are dormant (3.09b) and miss modern OSes. Verified.
- nmap-os-db — active OS fingerprints, NPSL licence. Verified.
- [Fingerbank](https://www.packetfence.org/news/2011/new-sister-project-fingerbank-open-dhcp-fingerprints-database.html) — DHCP/MAC/UA → device; now API only (free tier). Verified.
- Akamai HTTP/2 fingerprint (SETTINGS frame, WINDOW_UPDATE, priority, pseudo-header order): a published method with no public DB; compute it yourself. Known.

**Hardware identifiers**
- [Osmocom TAC DB](https://tacdb.osmocom.org/) — IMEI prefix (TAC, first 8 digits) → manufacturer/model; community DB. Verified (bulk export not confirmed).
- IEEE OUI registry (`oui.csv`) — MAC prefix → vendor; free download. Known. MAC randomisation on modern phones limits it.
- Apple model identifiers (e.g. `iPhone15,2` → iPhone 14 Pro) — community-maintained lists on GitHub. Known.

**IP / network intelligence (VPN, proxy, Tor, datacenter)**
- [X4BNet/lists_vpn](https://github.com/X4BNet/lists_vpn) — VPN-only and VPN+datacenter IPv4 lists, rebuilt by CI, MIT. Verified.
- [bad-asn-list](https://github.com/bountyyfi/bad-asn-list), [is-vpn](https://github.com/josephrocca/is-vpn), [reckart-everstream/VPNs](https://github.com/reckart-everstream/VPNs). Verified.
- [IP2Proxy LITE](https://www.ip2location.com/database/lite) — free proxy DB updated daily, attribution required. The pages disagree on whether VPN/Tor/DC types are in the free tier. Verified.
- [IPinfo Lite](https://ipinfo.io/products/free-ip-data-downloads) — country + ASN, unlimited, CC BY-SA 4.0, no VPN flag. Verified.
- MaxMind GeoLite2 ASN/City — free with an account key, EULA. Verified.
- [Tor bulk exit list](https://check.torproject.org/torbulkexitlist) — authoritative, changes often. Verified.
- FireHOL blocklists — aggregated IP reputation. Known.

## D. Bot and spoofing labels

| Source | What | Status |
|---|---|---|
| [FP-Inconsistent](https://arxiv.org/abs/2406.07647) (IMC 2025) | Honeysite traffic from 20 paid bot services, checked against DataDome and BotD; open-sourced inconsistency rules (e.g. UA vs. platform vs. screen mismatches) | verified (rules released; raw data not confirmed) |
| [Web Bot Detection Dataset](https://m4d.iti.gr/web-bot-detection-dataset/) (CERTH / Bournemouth, 2020) | Web logs + mouse movements: humans vs. "moderate" bots (browser fingerprint) vs. "advanced" bots (fingerprint + human-like behaviour); ~106 human sessions plus as many of each bot type | verified |
| [Krumnow et al., ESORICS 2019](https://cs.ou.nl/members/hugo/papers/ESORICS19.pdf) | Fingerprint surfaces of 14 automation frameworks (Selenium, Puppeteer, …) + measurement code | verified |

## Collectors (to generate first-party data)

No public source covers **battery** (the Battery Status API is gone from Firefox
and Safari, and Chrome only exposes it on secure origins) or **VPN use labelled
at the device level**. To get those, plus true device IDs at scale, we would need
our own collection or a simulator:
- FingerprintJS (open-source, MIT), CreepJS, ThumbmarkJS, BotD — JS collectors with 50–100+ attributes. Known.
- Berke et al. released their collection tool (above).
- `apps/datagen` in this repo could generate synthetic devices: sample joint
  profiles from tier B (intoli joints + Play catalog + Firefox/Steam hardware
  marginals), add per-device noise and drift (browser updates, IP changes,
  VPN on/off, battery level) learned from FP-Stalker, and use the generator's
  device ID as the positive-pair label.

## Recommendation

1. **Real-pair core:** FP-Stalker sample (longitudinal browser linking) + Berke
   et al. (request access now, since it's gated) + IEEE-CIS identity (fraud context).
   Email AmIUnique for the larger corpus.
2. **Generator priors:** intoli/user-agents, Google Play catalog, Firefox
   hardware report, Cloudflare Radar, Zenodo UA-volume DB.
3. **Feature enrichment:** device-detector (UA → brand/model), JA4DB, X4BNet +
   IP2Proxy LITE + Tor list + GeoLite2 ASN (network/VPN), TAC/OUI.
4. **Hard negatives / robustness:** FP-Inconsistent rules, FP-Scanner, CERTH bot dataset.
5. **Separate sub-models, later:** sensor (MSMDF, Decimeter) and IoT traffic
   (UNSW, CIC) are different modalities and shouldn't be mixed into the browser
   embedding at the start.

Open items: check licences before ingesting (FP-Stalker is AGPL; Berke data has
its own terms; Kaggle competition data is generally non-commercial), find where
FP-Scanner's data is hosted, and check whether IP2Proxy LITE's free tier includes VPN types.
