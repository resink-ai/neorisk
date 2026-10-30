# Device fingerprinting model v1: design and performance

Date: 2026-10-28. Code: `apps/devicefp`. Data sources: [device-fingerprint-data-sources.md](device-fingerprint-data-sources.md).

The model maps a device profile (user-agent, screen, GPU, canvas, fonts, network, ...) to a
point in euclidean space. Fingerprints of the same device should land close together, similar
devices closer than dissimilar ones, and different devices far apart.

## Summary

- **Data.** We have one public dataset with real device identities: the FP-Stalker sample
  (15,000 browser fingerprints from 1,819 browser instances, 2015-16, with 28 profile fields).
  364 of those browsers use fingerprint countermeasures, mostly user-agent spoofing. We keep
  them as a separate, unseen robustness test. A synthetic modern set (3,000 devices, 21k
  profiles) adds the attributes the old data lacks: battery, VPN, connection type, client
  hints, ASN. It is built from real browser configurations (intoli/user-agents), but its
  drift is simulated by us.
- **Model.** The encoder has two channels:
  - an *identity* channel: a frozen random code per field value, times a learned field weight;
  - a *semantic* channel: learned token embeddings, then a small transformer.

  The output is a unit-length vector of 960 numbers (928 on the synthetic set). Training is
  supervised contrastive learning, with the field weights initialised from a naive Bayes
  linker. It trains in about 20 s per fold on an RTX 2070.
- **Results on FP-Stalker** (5-fold CV over unseen devices, mean of folds):

  | | linking top-1 | open-set acc | enroll top-1 | enroll top-1, >3 months | TAR @ FAR 0.1% | spoofers, linking top-1 |
  |---|---|---|---|---|---|---|
  | **model** | **0.985** | **0.949** | **0.915** | **0.827** | **0.793** | 0.934 |
  | naive Bayes linker | 0.981 | 0.938 | 0.894 | 0.772 | 0.741 | 0.920 |
  | field-mismatch count | 0.972 | 0.904 | 0.862 | 0.735 | 0.638 | **0.949** |

  The model beats the strongest baseline on every test metric. The gap is small for
  short-term tracking (+0.004 ± 0.002 paired over folds). It is clear for long-term
  re-identification: enroll top-1 +0.022 ± 0.012, and +0.055 after more than 3 months. On
  spoofers, the plain mismatch count is still best.
- **Geometry.** For pairs of different devices, distance rises steadily with the number of
  fields that differ (Spearman 0.89). Same-device pairs have median distance 0.60; 95% of
  different-device pairs are farther than 0.97.
- **Synthetic set.** The model ties naive Bayes on normal devices (linking top-1 0.951 vs
  0.957). It wins on verification (TAR @ FAR 0.1% 0.949 vs 0.871) and on spoofers (0.890 vs
  0.776). Battery adds no identity; hardware and rendering fields carry most of it.
- **Main limitation.** The real data is ten years old (Flash, NPAPI plugins, no client hints)
  and small: about 450 training devices with repeat visits per fold. The numbers show the
  method works and beats strong baselines on real drift. They do not predict performance on
  2026 traffic, which needs first-party data (see Next steps).

## 1. Data

### FP-Stalker (real identities)

Cloned from [Spirals-Team/FPStalker](https://github.com/Spirals-Team/FPStalker): a 15k random
sample of AmIUnique's browser extension data, collected 2015-10 to 2016-08, AGPL-3.0. Each row is
one fingerprint *state* of a browser instance `id`. A new row is written when something changes,
so consecutive rows of one browser almost always differ in at least one field. `devicefp prepare`
reads the MySQL dump as text (it is never executed), drops the canvas/WebGL data URLs (their hashes
are kept) and constant columns, and turns the plugin list, Flash font list, user-agent words and
Accept-Language into sets.

| group | fingerprints | browsers | browsers with ≥2 fps | notes |
|---|---|---|---|---|
| consistent | 6,776 | 1,455 | 758 | the paper's "no countermeasure" list |
| spoofer | 8,224 | 364 | — | UA switchers etc.; one browser has 3,635 rows |

Field change rate between consecutive fingerprints of one consistent browser: IP hash 53%, Flash
fonts 38%, user-agent 31%, screen 28%, plugins 27%, canvas hash 7%, timezone 7%, WebGL renderer
2%. In the spoofer group, platform changes 37% of the time (against ~0% for consistent browsers):
the same machine claims iPad, Linux and Mac in turn.

### Synthetic modern devices

`devicefp synth` samples real configurations from intoli/user-agents v2.1.227 (10k records
weighted by traffic). It adds simulated hardware, network and behaviour (`synth.py` docstring has
the rules): stable hardware and rendering hashes shared by every device with the same stack; home
ISP, mobile carrier or VPN (with geo/timezone mismatch); battery level and charging; connection
type; browser updates every ~30 days; window resizes; rare font installs. 10% of devices are
anti-detect spoofers: a new user-agent and canvas noise on every visit, mostly behind a VPN.
Calibration: 52% of normal devices have a unique stable profile, and the largest group of
identical stable profiles is 38 devices. Studies of real browsers report roughly 33-90% unique,
depending on population.

A finding along the way: **35% of intoli's traffic weight is internally inconsistent**, e.g. an
iPhone user-agent with `navigator.platform = "Linux x86_64"`, or desktop Chrome at 375×812. These
look like DevTools emulation or bots. Normal synthetic devices start only from consistent records.
For production this is a ready-made bot signal.

What the synthetic set can and cannot say: it tests whether the model uses battery, VPN and
network fields sensibly, and how it handles many look-alike devices. Its absolute numbers depend
on drift rules we wrote, so they are not evidence about real traffic.

## 2. Task, protocols, metrics

Devices, not fingerprints, are split: 5 folds over devices (stratified by one vs several
fingerprints). For each fold the test part is unseen, 10% of the rest is validation, the rest is
training. Spoofers are never trained on; all 364 are scored in every fold, capped at their first
50 fingerprints so the 3,635-row browser does not dominate.

- **track** (FP-Stalker's setting). Fingerprints arrive in time order. Each is compared with the
  latest fingerprint of every device seen so far. *top-1*: a returning device ranks its own
  latest fingerprint first. *open-set acc*: with a distance threshold tuned on validation
  devices, a returning device is linked correctly and a new device is called new.
- **enroll.** Each device is enrolled once with its first fingerprint; every later fingerprint
  is matched against all enrolments. This is harder than track because drift accumulates;
  results are broken down by time since enrolment.
- **verify.** All pairs of test fingerprints (about 1.4M per fold), same device or not, from the
  distance alone: ROC-AUC, EER, true-accept rate at a 1% and 0.1% false-accept rate.

Baselines, fitted on the same training devices:
- **hamming:** number of fields that differ.
- **naive Bayes:** per field, a match adds log P(match|same)/P(match|different) and a mismatch
  adds log P(differ|same)/P(differ|different). Probabilities come from consecutive fingerprints
  and from value collision rates. Eckersley's Panopticlick linker and FP-Stalker's rules are
  hand-tuned versions of this idea; it is the strong baseline.

Selection: every design choice below was decided on the **validation** score: the mean of track
and enroll top-1 on validation devices, averaged over folds. Test numbers are reported, not
selected on.

## 3. Model

A profile is a list of hashed tokens grouped by field: one token for a scalar field, one per item
for a set field, hashed as `field=value` into 2^18 buckets. Per field, the token vectors are
averaged, so a 300-font list and a one-value field weigh the same.

- **Identity channel.** Each bucket has a frozen random unit vector of size 32. A field's vector
  is the mean of its item vectors, re-normalised, times a learned weight w_f. Two profiles then
  have squared distance Σ_f w_f² |r(a_f) − r(b_f)|²: about 2 Σ w_f² over the fields that differ,
  with partial credit for overlapping sets. This is a weighted mismatch count: it can express the
  naive Bayes linker exactly, and it works for values never seen in training (a new IP hash, a
  new canvas hash). w_f starts from the naive Bayes weights, √(match − differ).
- **Semantic channel.** Trainable embeddings of the same tokens, a 2-layer transformer over the
  28 field vectors (width 64), mean-pooled and projected to 64 numbers, times a learned weight.
  It learns that Firefox/41 and Firefox/42, or two font lists one font apart, are close.
- **Output.** Both channels concatenated and L2-normalised. On the unit sphere euclidean distance
  is monotone in cosine (d² = 2 − 2cos), so any euclidean nearest-neighbour index works.
- **Training.** Supervised contrastive loss (SupCon, τ = 0.07). A batch holds 128 devices with
  two views each: two different real fingerprints for a device seen several times, or two copies
  of the only one. AdamW with one-cycle LR 2e-3, 60 epochs, best epoch on validation. About
  17M parameters, almost all in the token table.

### How we got here

Each design re-run with the same 5-fold CV. Decisions follow the val column; test is shown for
context. Rows 1-4 use drift augmentation scaled to real change rates.

| step | val | test track top-1 | test enroll top-1 | what we learned |
|---|---|---|---|---|
| v0 design: semantic channel only | 0.952 | 0.972 | 0.888 | loses to naive Bayes: exact equality of rare values (IP, canvas hashes) is the strongest signal, and a learned embedding washes it out; collapses on spoofers (0.79) |
| + identity channel (code 16), random weight init | 0.947 | 0.982 | 0.890 | catches up with naive Bayes |
| + naive Bayes weight init, drift scaled to real change rates | 0.955 | 0.984 | 0.891 | training starts from the baseline; a first single-split run with one 15% swap rate for all fields kept epoch 1 as best: it made stable fields look volatile |
| + code size 32 | 0.960 | 0.984 | 0.915 | |
| **+ no drift augmentation (final)** | **0.963** | **0.985** | **0.915** | real repeat fingerprints already supply the drift |

Other configurations (5-fold CV each, full table from `devicefp report`):

| change from code32 / calibrated drift | val | test enroll top-1 | spoofers track top-1 |
|---|---|---|---|
| identity channel only (no semantic) | 0.944 | 0.868 | 0.924 |
| semantic channel only | 0.952 | 0.888 | 0.793 |
| no naive Bayes init | 0.947 | 0.890 | 0.936 |
| uniform drift (one swap rate for all fields) | 0.948 | 0.867 | 0.936 |
| spoof augmentation 20% / 40% (UA fields swapped jointly) | 0.941 / 0.944 | 0.883 / 0.875 | 0.921 / 0.920 |
| temperature 0.05 / 0.15 | 0.953 / 0.951 | 0.908 / 0.860 | 0.921 / 0.899 |
| code 64 | 0.958 | 0.919 | 0.922 |
| semantic width 128 | 0.962 | 0.911 | 0.925 |

The two channels need each other. Without the semantic channel, enroll top-1 loses 0.05 (0.13
beyond 3 months).
Without the identity channel, spoofers fall to 0.79. Spoofing augmentation did not help
spoofers, probably because those tools also change fields outside the user-agent group. The top four
configurations are within 0.005 on validation, so the choice among them is a close call.

## 4. Results on FP-Stalker

5 folds × 292 unseen test devices (1,696 fingerprints) per fold, means over folds.

**Tracking and open-set decisions**

| | top-1 | top-5 | MRR | open-set acc | returning linked | new rejected |
|---|---|---|---|---|---|---|
| model | **0.985** | 0.998 | **0.991** | **0.949** | **0.974** | **0.859** |
| naive Bayes | 0.981 | 0.999 | 0.989 | 0.938 | 0.966 | 0.838 |
| hamming | 0.972 | 0.997 | 0.983 | 0.904 | 0.952 | 0.728 |

**Re-identification against the first fingerprint, by time since enrolment**

| | <1 week | 1-4 weeks | 1-3 months | >3 months | all |
|---|---|---|---|---|---|
| queries per fold | 130 | 231 | 345 | 358 | 1,064 |
| model | **0.983** | **0.969** | **0.943** | **0.827** | **0.915** |
| naive Bayes | 0.981 | 0.968 | 0.936 | 0.772 | 0.894 |

The gain comes from long gaps, where many fields have drifted. There the partial credit of the
set codes and the semantic channel matter.

**Verification from distance alone**

| | ROC-AUC | EER | TAR @ FAR 1% | TAR @ FAR 0.1% |
|---|---|---|---|---|
| model | **0.9987** | **0.0156** | **0.973** | **0.793** |
| naive Bayes | 0.9983 | 0.0158 | 0.965 | 0.741 |
| hamming | 0.9959 | 0.0343 | 0.884 | 0.638 |

**Spoofers (unseen, never trained on)**

| | track top-1 | enroll top-1 |
|---|---|---|
| model | 0.934 | 0.726 |
| naive Bayes | 0.920 | 0.672 |
| hamming | **0.949** | 0.721 |

Spoofers are where the learned field weights hurt a little. Training on honest browsers teaches
the model to trust `os` (the largest weight, 1.12) and `user_agent`, which are exactly what
spoofers fake. The unweighted mismatch count is not misled.

**Embedding geometry** (`devicefp geometry`, test devices, fold means)

| | 5% | 25% | median | 75% | 95% |
|---|---|---|---|---|---|
| distance, same device | 0.29 | 0.47 | 0.60 | 0.71 | 0.83 |
| distance, different devices | 0.97 | 1.11 | 1.19 | 1.27 | 1.34 |

| fields differing (different devices) | 1 | 2 | 4 | 6 | 8 | 10 | 12 | 15 | ≥20 |
|---|---|---|---|---|---|---|---|---|---|
| mean distance | 0.30 | 0.42 | 0.55 | 0.69 | 0.83 | 0.92 | 1.00 | 1.09 | 1.29 |

The Spearman correlation between distance and number of differing fields is 0.89. For 65% of
fingerprints, the nearest other device is farther than the farthest fingerprint of their own
device.

Learned field weights (fold mean, top): os 1.12, accept_language 1.03, canvas_hash 0.96,
ip_hash 0.95, webgl_hash 0.90, semantic 0.87, webgl_renderer 0.82, timezone 0.81. Bottom:
fonts 0.34, adblock 0.36, flash_state 0.38. Fonts are diverse but change often (Flash
click-to-play toggles), and the set code already gives partial credit.

## 5. Results on the synthetic modern set

5 folds × 544 test devices (3,766 fingerprints), 280 spoofers.

| | track top-1 | open-set acc | enroll top-1 | TAR @ FAR 0.1% | EER | spoofers track | spoofers enroll |
|---|---|---|---|---|---|---|---|
| model | 0.951 | **0.923** | 0.929 | **0.949** | **0.0025** | **0.890** | **0.870** |
| naive Bayes | **0.957** | 0.912 | **0.931** | 0.871 | 0.0081 | 0.776 | 0.735 |
| hamming | 0.859 | 0.776 | 0.798 | 0.589 | 0.0409 | 0.638 | 0.578 |

Among look-alike devices (same iPhone, same carrier), top-1 linking is a tie with naive Bayes.
The model's distances are much better calibrated for accept/reject decisions, and it is far more
robust to anti-detect setups.

**Which signals carry identity** (model retrained without each group; code32 config with drift)

| dropped | test track top-1 | test enroll top-1 | TAR @ FAR 0.1% | spoofers track |
|---|---|---|---|---|
| nothing | 0.956 | 0.931 | 0.868 | 0.907 |
| battery level and charging | 0.954 | 0.931 | 0.873 | 0.904 |
| network (IP prefix, ASN, IP type, geo, VPN flag, connection, downlink) | 0.950 | 0.909 | 0.749 | 0.914 |
| user-agent and platform | 0.941 | 0.926 | 0.897 | 0.928 |
| hardware and rendering (cores, memory, GPU, touch, canvas, audio, screen, fonts) | 0.896 | 0.824 | 0.801 | 0.459 |

Battery adds nothing: it changes on every visit, and the model learned a low weight for it
(0.31). It stays useful as a liveness/emulator signal, not an identity signal. VPN on/off is
handled: the `vpn` flag and IP type get low weights, and home ISP and ASN carry the network
identity. The user-agent helps honest devices but costs robustness, since it is the field
spoofers control.

## 6. Limitations

- **Old, small real data.** The browsers are from 2015-16, with Flash fonts and NPAPI plugins.
  There are no client hints, no Battery API and no modern anti-fingerprinting (Safari ITP,
  Firefox RFP, Brave farbling). About 450 repeat-visit devices train each fold. Numbers on
  current traffic will differ, likely lower for Safari/iOS, where fingerprints are more uniform.
- **Hashed IP only.** FP-Stalker gives a hash of the address, so no ASN, geo or VPN enrichment
  was possible on real data.
- **Synthetic drift is ours.** Synthetic results check the pipeline and the model's use of
  fields. They are not a measurement.
- **Thresholds** are tuned per fold on validation devices; the open-set threshold depends on
  the gallery size.
- **Evaluation cost.** Exact all-pairs verification is O(n²). Production would use an ANN index
  (FAISS/HNSW) over the embeddings.

## 7. Next steps

1. Get modern labelled data:
   - request the Berke et al. 2023 dataset (8.4k US browsers, gated) and the full AmIUnique
     corpus;
   - deploy a first-party collector (FingerprintJS/CreepJS fields plus client hints, battery,
     JA4 TLS fingerprint, IP enrichment) with a login or cookie as the identity label.
2. Add JA4/TLS and HTTP/2 fingerprints as fields. They are hard to spoof from JavaScript and
   should close the spoofer gap.
3. Learn per-field change *transitions* (e.g. browser update, then UA +1) instead of random
   swaps, if we bring augmentation back for low-data fields.
4. Add a consistency head that flags impossible profiles (the 35% inconsistent intoli traffic,
   UA versus platform versus TLS), feeding the bot/fraud models.

## Reproduce

```bash
uv sync --all-packages
mkdir -p data/devicefp/raw && git clone --depth 1 https://github.com/Spirals-Team/FPStalker data/devicefp/raw/fpstalker
(cd data/devicefp/raw/fpstalker && tar zxf extension1.txt.tar.gz && tar zxf extension2.txt.tar.gz \
  && cat extension1.txt extension2.txt > tableFingerprints.sql)
(mkdir -p data/devicefp/raw/intoli && cd data/devicefp/raw/intoli && npm pack user-agents@2.1.227 \
  && tar xzf user-agents-2.1.227.tgz)
uv run devicefp prepare && uv run devicefp synth
for d in fpstalker synth; do
  uv run devicefp baselines --data data/devicefp/$d
  uv run devicefp cv --data data/devicefp/$d --name final
  uv run devicefp geometry --data data/devicefp/$d --name final
  uv run devicefp report --data data/devicefp/$d
done
```

Runs land in `data/devicefp/runs/<dataset>/<run>/fold<k>/` (encoder, embeddings, split,
history, weights, metrics). Training takes 20-40 s per fold on an RTX 2070; the all-pairs
baseline evaluation is the slow part.
