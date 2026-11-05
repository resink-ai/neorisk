# Self-supervised learning on entity profiles: survey and options for devicefp

Date: 2026-11-03. Related: [device-fingerprint-model.md](device-fingerprint-model.md) (v1),
`apps/devicefp/src/devicefp/v3.py` (v3). No training was run for this note.

Question: given *unlabelled* device and user profiles, in how many distinct ways can we build a
model that learns about the entities without human labels, and which of them are worth adding to
devicefp v3? DINOv2's framing applies directly: the augmentations (or natural views) define what
counts as noise, and the representation is whatever survives them. For profiles, the main design
decision is therefore *which variation is noise* (browser update, IP change, battery level) and
*which is identity* (GPU, canvas hash, font set).

## Summary

- **There are about ten distinct design families** for profile SSL (section 4). Each is set by
  where its views or targets come from: (1) repeat observations over time, (2) field corruption
  with an invariance loss (SCARF), (3) masked field modelling (VIME, BERT/MAE style), (4) field-subset
  views and towers (SubTab), (5) latent prediction between field groups (JEPA), (6) cross-field
  consistency, (7) co-occurrence graphs (shared IP, /24, Wi-Fi, account), (8) event sequences,
  (9) clustering and prototypes, (10) pseudo-labels from heuristic linkers. Most real systems
  combine two or three of them.
- **v3 is already partly self-supervised.** The spec and pref towers are regressed onto a
  Fellegi-Sunter agreement kernel computed from the raw fields. The env tower is regressed onto
  network keys that are never model inputs. Only the identity tower depends on an external weak
  label, `tmx_fuzzy_device_id`, so it distils a third-party linker and inherits its errors.
- **The largest untapped resource is the unlinked rows.** v3 has 859,109 profiles in 692,352
  connected components (`data/devicefp/runs/v3/meta.json`), and 71% of rows are singleton
  components with no linked partner by any key. The identity loss only uses entities with at
  least 2 training rows, which is 52% of training rows (computed from `labels.npz`). The other 48%
  never reach the identity loss. Masked field modelling and
  corruption-based objectives can train on every row.
- **Best option for us: masked field modelling as an auxiliary loss and as pretraining**, with
  binned or capped-class targets (BinRecon-style). It suits v3's token-per-field transformer,
  uses all rows, and yields a per-field surprisal score as a spoof and consistency signal (v1 doc,
  next step 4). It also has the best tabular evidence: Rubachev et al. found that reconstruction
  and mask prediction beat contrastive pretraining.
- **The v1 lesson still applies, and v3 does not use it.** v3's `FieldEncoder` maps values seen
  fewer than 3 times, or outside the top 4,096 per field, to one out-of-vocabulary code. Every SSL
  objective that rewards "semantic" similarity pushes further in the direction that hurt v1. Any SSL
  addition should sit next to an exact-match channel (frozen random codes, or the FS score as a
  feature), not replace it. Current local results agree: on web test pairs, FS has PR AUC 0.650 and
  the served v3 run (`factor_tmxweb_s1`) has 0.456. On mobile, v3 has 0.825 and FS 0.714
  (`data/devicefp/runs/v3/{factor_tmxweb_s1/result.json,baseline_fs.json}`).
- **Ranked recommendation** (section 6): (1) masked field modelling with a cross-field
  surprisal head; (2) an exact-match identity channel with label-free collapse monitoring (RankMe,
  alignment/uniformity), plus VICReg/KoLeo-style spread terms if collapse shows; (3) linker-ensemble
  pseudo-labels (tmx, devId, FS, network) in place of tmx alone; (4) a co-occurrence graph embedding
  as a separate *network/farm* factor, not mixed into identity. JEPA, DINO-style prototypes and
  sequence models come after these.
- **Main pitfall: shortcuts through shared identifiers.** If a field that produced the positive
  pair (IP, /24, a cookie, anything tmx uses internally) is an input, the model learns to read it
  back. v3 already keeps ID columns, `bssid` and `privateIp` out of the inputs. `ip_subnet24` and
  `ip_geo_cell` remain inputs while positives come from a linker that probably uses IP, so they
  need a leave-one-group-out check.

## 1. General self-supervised families

"Views" are the inputs whose agreement is enforced. "Anti-collapse" is what stops the trivial
solution (constant output, or a low-rank subspace; Jing et al. 2021, arXiv 2110.09348, show that
dimensional collapse occurs even with negatives). Key results are quoted from each abstract unless
noted otherwise.

| method | pretext task | views | anti-collapse | one key result |
|---|---|---|---|---|
| SimCLR (Chen et al. 2020, [2002.05709](https://arxiv.org/abs/2002.05709)) | match two views of an image among in-batch negatives (NT-Xent) | crop, colour distortion, blur; "composition of data augmentations plays a critical role" | negatives in a large batch; projection head | 76.5% ImageNet linear top-1, ResNet-50 |
| MoCo (He et al. 2019, [1911.05722](https://arxiv.org/abs/1911.05722)); v2 [2003.04297](https://arxiv.org/abs/2003.04297) | contrastive dictionary look-up | crops plus augmentation | negatives from a queue; momentum (EMA) key encoder | beats supervised pretraining on 7 detection/segmentation tasks |
| BYOL (Grill et al. 2020, [2006.07733](https://arxiv.org/abs/2006.07733)) | online network predicts the target network's embedding of the other view | SimCLR-style | EMA target, predictor, no negatives | 74.3% linear, ResNet-50 (79.6% larger ResNet) |
| SimSiam (Chen & He 2020, [2011.10566](https://arxiv.org/abs/2011.10566)) | as BYOL without EMA | SimCLR-style | stop-gradient plus predictor; abstract: collapsing solutions exist, stop-gradient is essential | competitive without negatives, large batches or momentum |
| Barlow Twins (Zbontar et al. 2021, [2103.03230](https://arxiv.org/abs/2103.03230)) | cross-correlation of the two views' embeddings → identity | SimCLR-style | off-diagonal (redundancy) term | on par with SOTA linear; best low-label semi-supervised |
| VICReg (Bardes et al. 2021, [2105.04906](https://arxiv.org/abs/2105.04906)) | invariance (MSE) between views | SimCLR-style | explicit variance hinge per dimension, plus covariance decorrelation | the variance term also stabilises other methods |
| DINO (Caron et al. 2021, [2104.14294](https://arxiv.org/abs/2104.14294)) | student matches EMA teacher's softmax over K prototypes | multi-crop: global and local crops; teacher sees only global ones | teacher centering plus sharpening (low temperature), EMA | 80.1% linear ViT-B; 78.3% k-NN with ViT-S |
| iBOT (Zhou et al. 2021, [2111.07832](https://arxiv.org/abs/2111.07832)) | DINO on [CLS] plus self-distillation on masked patch tokens ("online tokenizer") | crops plus patch masking | as DINO | 82.3% linear, 87.8% fine-tune |
| DINOv2 (Oquab et al. 2023, [2304.07193](https://arxiv.org/abs/2304.07193), [repo](https://github.com/facebookresearch/dinov2)) | DINO + iBOT losses, untied heads | multi-crop plus masking on curated LVD-142M | Sinkhorn-Knopp centering (from SwAV), KoLeo regulariser | ViT-g/14 86.5% linear (Table 4). KoLeo raises Oxford-M retrieval mAP from 55.6 to 63.9 (Table 3a) |
| BERT (Devlin et al. 2018, [1810.04805](https://arxiv.org/abs/1810.04805)) | predict masked tokens (plus next sentence) | one view with masked tokens | none needed: the target is the fixed input | GLUE 80.5 (+7.7) |
| MAE (He et al. 2021, [2111.06377](https://arxiv.org/abs/2111.06377)) | reconstruct pixels of masked patches | 75% random patch mask; encoder sees visible patches only | fixed input target | ViT-H 87.8% on ImageNet-1K only |
| data2vec (Baevski et al. 2022, [2202.03555](https://arxiv.org/abs/2202.03555)) | predict the EMA teacher's contextual latents of the full input from a masked input | masking | EMA teacher; the target averages top layers | one method for speech, vision and NLP; SOTA or competitive |
| I-JEPA (Assran et al. 2023, [2301.08243](https://arxiv.org/abs/2301.08243), [repo](https://github.com/facebookresearch/ijepa)) | from one context block, predict latents of several target blocks | no hand-crafted augmentation; large, spread-out target blocks | EMA target encoder plus predictor | ViT-H/14 trained on 16 A100s in under 72 h |
| DeepCluster (Caron et al. 2018, [1807.05520](https://arxiv.org/abs/1807.05520)) | classify k-means pseudo-labels of its own features, then iterate | single view plus augmentation | (paper body) reassign empty clusters, sample uniformly over clusters | beats prior unsupervised SOTA on all standard benchmarks |
| SwAV (Caron et al. 2020, [2006.09882](https://arxiv.org/abs/2006.09882)) | predict one view's prototype assignment from the other ("swapped") | multi-crop | equipartition of assignments via Sinkhorn-Knopp | 75.3% linear, ResNet-50 |

Cross-cutting results worth keeping:
- **Views should share only the task-relevant information** (InfoMin; Tian et al. 2020,
  [2005.10243](https://arxiv.org/abs/2005.10243)). Stronger augmentation lowered the mutual
  information between views and improved accuracy (73% linear, ResNet-50). For profiles this means
  views should differ in everything except identity. Two copies of the same row (v1's singleton
  views) teach nothing.
- **Alignment and uniformity** (Wang & Isola 2020, [2005.10242](https://arxiv.org/abs/2005.10242),
  [code](https://github.com/SsnL/align_uniform)): contrastive loss asymptotically optimises
  closeness of positives and uniformity on the hypersphere. Both are measurable without labels,
  and optimising them directly matched contrastive learning.
- **Why non-contrastive methods do not collapse:** the predictor, stop-gradient, EMA and weight
  decay all play a part (Tian et al. 2021, [2102.06810](https://arxiv.org/abs/2102.06810)).
  Collapse is a real failure mode; a low loss does not rule it out.
- **KoLeo** comes from Sablayrolles et al. 2018 ([1806.03198](https://arxiv.org/abs/1806.03198)).
  It is a Kozachenko-Leonenko entropy regulariser that spreads vectors uniformly for nearest-neighbour
  search, which is exactly what an identity index needs.
- **SupCon** (Khosla et al. 2020, [2004.11362](https://arxiv.org/abs/2004.11362)), v3's identity
  loss, is SimCLR with label-defined positives. With a weak label it sits between supervised and
  self-supervised learning.

## 2. Self-supervised learning on tabular and categorical data

| method | pretext | views / corruption | anti-collapse | reported result |
|---|---|---|---|---|
| VIME (Yoon et al., NeurIPS 2020, [paper](https://proceedings.neurips.cc/paper/2020/file/7d97667a3e056acab9aaf653807b4a03-Paper.pdf), [repo](https://github.com/jsyoon0823/VIME)) | estimate the binary mask *and* reconstruct the original values from a corrupted row | random mask; masked entries replaced by draws from each feature's marginal | reconstruction target | beat supervised, context-encoder and MixUp baselines on genomics and clinical data. Reviewers called the novelty limited (NeurIPS reviews) |
| SCARF (Bahri et al. 2021, [2106.15147](https://arxiv.org/abs/2106.15147)) | InfoNCE between a row and its corrupted copy | replace a random subset of features with marginal draws | in-batch negatives | improves accuracy on the 69 OpenML-CC18 datasets, also with label noise and in the semi-supervised setting |
| SubTab (Ucar et al. 2021, [2110.04361](https://arxiv.org/abs/2110.04361), [repo](https://github.com/AstraZeneca/SubTab)) | reconstruct the full row from each feature subset, plus contrastive and distance terms between subset embeddings | disjoint or overlapping column subsets (± noise) | reconstruction | 98.31% on tabular MNIST; aggregates subset latents at test ("collaborative inference") |
| TabTransformer (Huang et al. 2020, [2012.06678](https://arxiv.org/abs/2012.06678)) | MLM or replaced-token detection (ELECTRA-style) over categorical column embeddings | masked or replaced categories | fixed targets | pretraining gives an average 2.1% AUC lift in the semi-supervised setting |
| SAINT (Somepalli et al. 2021, [2106.01342](https://arxiv.org/abs/2106.01342)) | contrastive plus denoising pretraining; row (inter-sample) attention | CutMix in input space, mixup in embedding space (paper body) | negatives, reconstruction | claims to beat XGBoost/CatBoost/LightGBM on average over its benchmark |
| TabNet (Arik & Pfister 2019, [1908.07442](https://arxiv.org/abs/1908.07442)) | encoder-decoder predicts masked features | random feature masks | fixed targets | "significantly improving performance ... when unlabeled data is abundant" |
| STab (Hajiramezanali et al., NeurIPS 2022 TRL workshop, [mlanthology](https://mlanthology.org/neuripsw/2022/hajiramezanali2022neuripsw-stab)) | augmentation-free; two stochastically regularised passes must agree | the views come from stochastic regularisation (dropout-like), not input changes | no negatives (mechanism per paper) | workshop claim of SOTA over contrastive and pretext methods; no arXiv version found |
| ReConTab (Chen et al. 2023, [2310.18541](https://arxiv.org/abs/2310.18541)) | asymmetric autoencoder plus regularised contrastive learning | corruption | reconstruction plus contrastive | embeddings used as extra features improve XGBoost and RF |
| T-JEPA (Thimonier et al. 2024, [2410.05016](https://arxiv.org/abs/2410.05016)) | predict the latent of one feature subset from another subset of the same row | feature-subset masks, no augmentation | EMA target plus "regularization tokens" (stated as critical) | lets some deep models match or beat GBDTs |
| BinRecon (Lee et al., ICML 2024, [2405.07414](https://arxiv.org/abs/2405.07414), [repo](https://github.com/kyungeun-lee/tabularbinning)) | reconstruct each feature's *bin index* (class or order), not its value | input masking or corruption optional | fixed targets | "consistently improves" SSL across diverse tabular datasets; puts categorical and numeric targets on the same footing |

**Does tabular SSL actually help? The evidence is mixed.**

- **Rubachev et al. 2022, "Revisiting pretraining objectives for tabular deep learning"**
  ([2207.03208](https://arxiv.org/abs/2207.03208)), the most careful comparison (11 datasets, tuned
  baselines, fully supervised setting):
  - "Contrastive is not superior". Reconstruction and mask prediction were preferred, and neither
    won everywhere.
  - Target-aware objectives (mask or reconstruction plus a supervised loss, or target-conditioned
    corruption) helped most. MLP average rank was 2.6-2.9, against 5.5 without pretraining.
  - Gains were large for plain MLPs and smaller for MLPs with numerical embeddings.
  - Fine-tuning on clean data was required.
  - Pretraining often cost about 10× the compute.
  - Pretrained MLPs beat GBDT on 4 of 11 datasets; with numerical embeddings they beat it on all
    but 2 (WE, MI).
- **Against GBDTs:**
  - Shwartz-Ziv & Armon 2021 ([2106.03253](https://arxiv.org/abs/2106.03253)): XGBoost beat the
    deep models (TabNet among them), including on those models' own datasets.
  - Grinsztajn et al. 2022 ([2207.08815](https://arxiv.org/abs/2207.08815)): trees remain SOTA on
    medium data (about 10k rows, 45 datasets).
  - Gorishniy et al. 2021 ([2106.11959](https://arxiv.org/abs/2106.11959)): no universally best model.
  - McElfresh et al. 2023 ([2305.02997](https://arxiv.org/abs/2305.02997), 176 datasets): the
    NN-vs-GBDT gap is often negligible, and GBDTs handle skewed and heavy-tailed features better.
- **Where it helps:** Levin et al. 2022 ([2206.15306](https://arxiv.org/abs/2206.15306)) found that
  upstream data gives tabular NNs "a decisive advantage" over GBDTs in transfer settings. That is
  our situation: many unlabelled rows, few trusted links.
- **Reading for us:**
  - Most per-method gains above come from the authors' own benchmarks and are small.
  - The robust finding is narrower: masked and reconstruction pretraining helps neural tabular
    encoders when unlabelled data is plentiful relative to labels, and adding a target signal helps
    further.
  - Our downstream task is metric learning (pair retrieval), not row classification, so none of
    these benchmarks measures it directly.

## 3. Entity, graph and sequence self-supervision

| method | views / context | objective | anti-collapse | note |
|---|---|---|---|---|
| word2vec SGNS (Mikolov et al. 2013, [1301.3781](https://arxiv.org/abs/1301.3781), [1310.4546](https://arxiv.org/abs/1310.4546)) | token and its window neighbours | skip-gram with negative sampling | negatives; frequent-word subsampling | the base of everything below |
| DeepWalk (Perozzi et al. 2014, [1403.6652](https://arxiv.org/abs/1403.6652)) | node and nodes on truncated random walks | skip-gram over walks | hierarchical softmax / negatives | F1 up to 10% higher when labels are sparse |
| node2vec (Grover & Leskovec 2016, [1607.00653](https://arxiv.org/abs/1607.00653)) | biased (p, q) random walks: BFS-like = structural role, DFS-like = community | SGNS | negatives | improves multi-label classification and link prediction |
| GraphSAGE unsupervised (Hamilton et al. 2017, [1706.02216](https://arxiv.org/abs/1706.02216)) | node u and node v co-occurring on short walks (50 walks of length 5, appendix) | Eq. 1: −log σ(z_u·z_v) − Q·E_{v_n∼P_n} log σ(−z_u·z_{v_n}) | negative sampling | inductive: embeds unseen nodes from their features and neighbourhood; this matters for new devices |
| DGI (Veličković et al. 2018, [1809.10341](https://arxiv.org/abs/1809.10341)) | node (patch) vs graph summary; negatives from a corrupted graph | mutual-information discriminator | corrupted negatives | sometimes beats supervised node classification |
| GraphCL (You et al. 2020, [2010.13902](https://arxiv.org/abs/2010.13902)) | two augmented graphs (node drop, edge perturbation, attribute mask, subgraph) | NT-Xent | negatives | augmentation choice is dataset-dependent |
| item2vec (Barkan & Koenigstein 2016, [1603.04259](https://arxiv.org/abs/1603.04259)) | items in the same basket or set | SGNS | negatives | competitive with SVD without user information |
| prod2vec (Grbovic et al. 2016, [1606.07154](https://arxiv.org/abs/1606.07154)) | products in a user's purchase sequence (e-mail receipts) | skip-gram | negatives | 9% CTR lift online; 29M users, 172 shops |
| Airbnb listing embeddings (Grbovic & Cheng, KDD 2018, [DOI 10.1145/3219819.3219885](https://doi.org/10.1145/3219819.3219885)) | listings in click sessions; the booked listing as global context (paper body) | skip-gram with negatives, including in-market negatives | negatives | the abstract says search ranking and similar-listing channels "drive 99% of conversions". The CTR uplift figure that circulates (≈21%) comes from secondary sources: **unverified** |
| SASRec (Kang & McAuley 2018, [1808.09781](https://arxiv.org/abs/1808.09781)) | prefix → next item | causal self-attention | softmax / negatives | baseline for the next two |
| BERT4Rec (Sun et al. 2019, [1904.06690](https://arxiv.org/abs/1904.06690)) | sequence with masked items | Cloze (masked item prediction) | fixed targets | beats sequential baselines on 4 datasets |
| CL4SRec (Xie et al. 2020, [2010.14395](https://arxiv.org/abs/2010.14395)) | two augmentations of one user sequence: item crop, item mask, item reorder | next-item loss plus contrastive | in-batch negatives | SOTA on 4 public datasets |
| CPC (van den Oord et al. 2018, [1807.03748](https://arxiv.org/abs/1807.03748)) | context so far vs future latents | InfoNCE on future prediction | negatives | one method for speech, images, text, RL |
| TS2Vec (Yue et al. 2021, [2106.10466](https://arxiv.org/abs/2106.10466)) | overlapping augmented context views of a series | hierarchical contrastive at instance and timestamp level | negatives | SOTA on 125 UCR and 29 UEA datasets |

Lesson for profiles: graph and sequence methods learn **co-occurrence**. They place together
entities that appear in the same context (same Wi-Fi, same session, same account). That is a
different notion from "same device". It is excellent for farms, households and account takeover,
and dangerous if it is mixed into the identity similarity.

## 4. Ways to build a self-supervised profile model

Notation: a profile is a set of fields {UA, platform, screen, GPU, fonts, canvas/audio hash,
IP-geo, /24, ASN, timezone, locale, languages, network type, battery, ...}. "Noise" is what the
objective makes the representation invariant to; "intrinsic" is what it must preserve.

### 4.1 Repeat observations as natural views (temporal positives)

- **Views:** two observations of the same entity at different times. Drift between them is the
  noise: browser updates, IP and network changes, window size, fonts added. The positive key must
  come from something other than the encoder's inputs: a login, an app-scoped ID, a first-party
  cookie. In v3 these are devId, osId and tmx.
- **Target:** contrastive (SupCon/InfoNCE) or BYOL/VICReg-style agreement.
- **Anti-collapse:** in-batch negatives, with look-alike hard negatives (v3's same-spec-bucket sampling).
- **Learns:** the real drift distribution, i.e. which fields are stable. It is the best signal for
  long-gap re-identification: v1's gain was largest beyond 3 months.
- **Fails:** for devices seen once, which carry no signal. It also inherits the key's errors: a
  cookie reset splits a device, and a shared login merges a family's devices. When the key is a
  fuzzy ID, the model learns that ID's linking rules, including its reliance on IP.
- **Fits:** whenever a deterministic first-party key exists. It is "self-supervised" only in that
  no human labels anything.

### 4.2 Corruption-invariance (SCARF-style)

- **Views:** a row and a copy where a random subset of fields is resampled from each field's
  marginal. The resampled fields are the noise. For identity, the corruption should follow
  *observed* per-field change rates: v1 found that uniform swap rates made stable fields look
  volatile and hurt (val 0.948 vs 0.963).
- **Target:** InfoNCE between a row and its corruption.
- **Anti-collapse:** negatives.
- **Learns:** robustness to partial drift on single-observation rows, where no natural pair exists.
- **Fails:**
  - Marginal resampling creates impossible combinations (iPhone UA with an NVIDIA GPU). The model
    learns to ignore inconsistency, which is the opposite of what spoof detection needs.
  - Instance discrimination also pushes two genuinely identical devices apart. Look-alikes are the
    hard case: 38 identical stable profiles in v1's synthetic set.
- **Fits:** as an auxiliary on singleton rows, with corruption calibrated per field. It is weaker
  than 4.1 wherever real repeats exist: v1's final model dropped drift augmentation for that reason.

### 4.3 Masked field modelling (VIME / BERT / MAE / BinRecon)

- **Views:** one view, with a subset of fields hidden or replaced. Nothing is declared noise; the
  model must explain each field from the others.
- **Target:** the class of each masked field (capped vocabulary or bin index, BinRecon-style), and
  optionally VIME's mask-estimation head ("which fields were replaced?").
- **Anti-collapse:** none needed, because the targets are fixed.
- **Learns:** the joint distribution of fields:
  - which GPUs go with which models and OS builds;
  - which timezones go with which IP geos;
  - which font sets go with which locales.
- **Fails:**
  - It does not learn identity directly: two devices of the same model look the same to it.
  - It cannot predict rare high-entropy values (canvas hash, exact subnet) and should not try. Mask
    them out of the target set, or predict only a coarse bucket.
- **Fits:** pretraining or an auxiliary loss on all rows. It also gives a free **consistency
  score**: the summed per-field negative log-likelihood (surprisal) of the observed value given
  the rest.

### 4.4 Field-subset views and towers (SubTab, multi-view)

- **Views:** disjoint field groups of the same row, e.g. hardware {GPU, screen, cores, memory,
  canvas} vs software {UA, fonts, locale} vs network {IP-geo, ASN, timezone}. The noise is
  "whatever is specific to one group".
- **Target:** reconstruct the full row from each subset (SubTab), or contrast the group embeddings
  of the same row.
- **Anti-collapse:** reconstruction or negatives.
- **Learns:** information shared across groups. That is mostly device *type* (Android vs iOS
  model class, country), because only coarse attributes are predictable across groups.
- **Fails:** information that lives in one group only (a canvas hash, a home ISP). The views
  agree on device class, not on the individual device.
- **Fits:** semantics, cohorts and consistency checks. As an identity objective it is weak.
  v3's towers have the right structure for it; their targets are currently agreement kernels,
  not cross-group agreement.

### 4.5 JEPA-style latent prediction (I-JEPA, T-JEPA, data2vec)

- **Views:** context fields → latent of target fields, with an EMA target encoder.
- **Target:** the target encoder's latent, not the raw value.
- **Anti-collapse:** EMA plus predictor; T-JEPA also needed regularisation tokens. Add a VICReg
  variance term as insurance.
- **Learns:** like 4.3, but it can ignore unpredictable detail (exact versions) instead of
  spending capacity on it.
- **Fails:** it is harder to tune and to diagnose. Collapse can be silent, and only RankMe or a
  uniformity check reveals it. The tabular evidence is one paper.
- **Fits:** only if 4.3 works and saturates.

### 4.6 Cross-field consistency (predict one group from another)

- **Views:** group A → group B. Examples:
  - UA and platform → hardware (GPU vendor, cores, touch points, screen);
  - IP geo → timezone and locale;
  - ASN → connection type and VPN.
- **Target:** classification of B's fields.
- **Anti-collapse:** fixed targets.
- **Learns:** a calibrated "this combination is unusual" score, with no labels. Spoof detection
  falls out of it:
  - anti-detect browsers change the UA but not the GPU;
  - VPN users show an IP geo that disagrees with the timezone;
  - 35% of intoli's traffic weight is internally inconsistent (v1 doc).
- **Fails:**
  - It is not an identity embedding.
  - A consistent spoof (a full profile copied from a real device) is invisible to it.
  - Corporate VPNs and travellers are legitimately inconsistent, so it needs per-population
    calibration.
- **Fits:** risk features and a spoof head. It is the same machinery as 4.3, restricted to
  structured masks.

### 4.7 Co-occurrence graphs (shared IP, /24, Wi-Fi, account, cookie)

- **Views:** devices that share an IP, /24, BSSID, account or cookie (bipartite device–key graph).
  Context is the noise; the neighbourhood is intrinsic.
- **Target:** DeepWalk/node2vec SGNS, GraphSAGE's unsupervised Eq. 1 (inductive, so new devices
  get embeddings from their features plus neighbours), or DGI/GraphCL.
- **Anti-collapse:** negative sampling or corrupted graphs.
- **Learns:** households, offices, device farms, proxy pools, account sharing, and "this device is
  near known-bad devices".
- **Fails:**
  - It does not learn identity. Two phones on one home Wi-Fi are neighbours, not the same device.
  - Hubs (carrier-grade NAT, mobile /24s, public Wi-Fi) connect everything. They need IDF-style
    down-weighting or pruning: drop keys with more than N devices.
  - It is transductive unless GraphSAGE-style.
- **Fits:** a separate network or farm factor, with v3's env grades (bssid > IP+city > subnet+city
  > city) as edge weights. **Leakage:** v3 splits by components over tmx, devId, osId and proxy,
  not over IP. A graph built on all rows passes test-device neighbourhoods into training, so build
  edges from training rows only, or evaluate on a later time window.

### 4.8 Session and event sequences

- **Views:** two crops or masks of one entity's event sequence (CL4SRec), or masked events
  (BERT4Rec), or prefix → future (CPC).
- **Target:** contrastive, Cloze or next-event.
- **Anti-collapse:** negatives or fixed targets.
- **Learns:** behaviour: login cadence, typical hours, navigation habits, and, for users, item and
  merchant preferences. This is the signal for user profiles and account takeover.
- **Fails:** static device identity (it adds little to fingerprints), and new entities with short
  histories.
- **Fits:** user profiles once event logs exist. v3's `device_profiles.pqt` drops per-session
  timestamps and paths (`DROP_COLUMNS`), so this is out of scope for the current data.

### 4.9 Clustering and prototypes (DeepCluster, SwAV, DINO)

- **Views:** two views (4.1 or 4.2) must agree on a soft assignment over K prototypes.
- **Target:** the swapped assignment, or the EMA teacher's sharpened distribution.
- **Anti-collapse:** equipartition (Sinkhorn-Knopp), centering plus sharpening.
- **Learns:** a discrete taxonomy: device-model cohorts, "same stack" groups, bot-tool families.
  It is useful for monitoring and as a categorical feature.
- **Fails:** it imposes balanced cluster sizes on a very skewed population (one iPhone model vs a
  long tail). Prototypes also cannot represent individual devices (K is far below the number of
  devices).
- **Fits:** the spec or pref tower ("what kind of device"), or anomaly cohorts. Not identity.

### 4.10 Pseudo-labels from heuristic linkers (weak supervision)

- **Views:** pairs that a heuristic linker scores as confident matches; confident non-matches are
  the negatives. Linkers include:
  - Fellegi-Sunter (Fellegi & Sunter 1969, JASA 64(328):1183-1210,
    [PDF](https://courses.cs.washington.edu/courses/cse590q/04au/papers/Felligi69.pdf));
  - naive Bayes;
  - tmx;
  - devId;
  - network keys.

  Combine the linkers' votes as in data programming (Snorkel; Ratner et al. 2017,
  [1711.10160](https://arxiv.org/abs/1711.10160)) instead of trusting any one of them.
- **Target:** SupCon on the pseudo-groups, or regression onto the linker's score (v3's spec and
  pref towers already do the latter).
- **Anti-collapse:** negatives.
- **Learns:** a smooth, indexable version of the linker, which generalises to partial matches the
  linker scores poorly.
- **Fails:** it is capped by the linker's blind spots: the model "agrees with FS" rather than
  "finds devices". Confirmation bias builds up if pseudo-labels are regenerated from the model's
  own output.
- **Fits:** this is v3's actual regime (tmx is a fuzzy linker). It works best when several
  independent linkers vote and the model is checked on a key none of them used. devId pairs are
  that key for v3, via `gold_recall`.

### Comparison

| # | views from | learns mainly | uses singletons | anti-collapse | spoof signal | fit for identity |
|---|---|---|---|---|---|---|
| 4.1 | real repeats | individual identity under drift | no | negatives | weak | **high** |
| 4.2 | marginal corruption | partial-drift robustness | yes | negatives | negative (hides it) | medium |
| 4.3 | masked fields | field joint distribution | yes | none needed | **yes (surprisal)** | low alone, good as auxiliary |
| 4.4 | field subsets | device class | yes | reconstruction | some | low |
| 4.5 | latent prediction | as 4.3, abstracted | yes | EMA (fragile) | some | low |
| 4.6 | group → group | consistency | yes | none needed | **high** | none (risk feature) |
| 4.7 | shared network or account | household/farm context | yes | negatives | farms | none (separate factor) |
| 4.8 | event sequences | behaviour | no | negatives | ATO | users, not devices |
| 4.9 | prototypes | cohorts | yes | equipartition | tool families | none |
| 4.10 | linker pseudo-labels | smoothed linker | partly | negatives | inherits | high (v3 now) |

## 5. Pitfalls and evaluating without labels

### Pitfalls

- **Shortcut features** (Geirhos et al. 2020, [2004.07780](https://arxiv.org/abs/2004.07780)):
  - If an input field is the reason two rows share a key, the model reads it back. Examples: an IP
    hash or cookie that defines the pair, or the fields tmx's own linker relies on.
  - The loss falls, the probe looks good, and the model fails once that field changes.
  - Test: retrain without each field group and compare retrieval on pairs *where that group
    differs*.
  - v3 already excludes `bssid`, `ssid`, `privateIp` and app IDs from inputs (`ID_COLUMNS`,
    `DROP_COLUMNS`). The env tower's labels are never inputs. `ip_subnet24` and `ip_geo_cell` are
    still inputs to both the id and env towers.
- **Rare-value memorisation vs washing out:**
  - A learned embedding cannot represent a value seen once. v3 caps the vocabulary at 4,096 per
    field with a minimum count of 3, so rare canvas hashes and subnets become one OOV token.
  - SSL objectives that reward predictability (4.3-4.5) push capacity toward common values and
    make this worse.
  - Conversely, contrastive training on tiny groups lets the token table memorise rare values as
    entity IDs.
  - v1's fix was frozen random codes per value: exact match, no memorisation, works for unseen
    values.
- **Collapse:**
  - Full collapse (constant output) shows up as all cosines near 1.
  - Dimensional collapse (Jing et al. 2021) is silent. v3's 64-dimensional id tower could use a
    rank of 10 and still rank pairs acceptably while failing at an ANN scale of millions.
  - Monitor RankMe; add VICReg variance or KoLeo if it drops.
- **Augmentations that destroy identity:**
  - Resampling canvas, GPU or font-hash fields makes a different device, so the "positive" is a
    false positive.
  - Augmentations that keep identity are the drift-like ones: UA version bump, IP change, window
    resize, battery. Even these should follow measured rates.
- **Leakage when views share identifiers:**
  - Positives and negatives must not be separable by a field shared only within the pair.
  - Splits must keep entities and graph neighbourhoods apart: v3's connected-component split does
    this for ID keys, but not for IP-graph edges (4.7).
- **Circular evaluation:**
  - v3 trains the id tower on tmx groups and also scores clustering and pairs against tmx. A model
    that copies tmx perfectly scores 1.0.
  - devId pairs are independent gold, but they exist only for app traffic.

### Label-free and cheap-label evaluation

| check | how | what it catches |
|---|---|---|
| held-out repeat retrieval | recall@k of a device's other observations, keyed by devId or a login not used in training | the identity objective itself; v3's `gold_recall` is this |
| linear probes on proxies | logistic regression from the embedding to OS, browser family, country, GPU vendor (cheap, near-deterministic labels) | whether semantics survived; v3's `relatedness` gpuVendor AUC is one |
| alignment / uniformity (Wang & Isola 2020) | E‖z−z⁺‖² over positives; log E exp(−2‖z−z'‖²) over all pairs | collapse (uniformity rises toward 0), loose positives |
| RankMe (Garrido et al. 2022, [2210.02885](https://arxiv.org/abs/2210.02885)) | exp of the entropy of normalised singular values of the embedding matrix | dimensional collapse; usable for label-free hyperparameter selection, with almost no loss against label-based selection |
| stability | k-NN overlap and cluster ARI across seeds and across retrains a week apart | features that depend on initialisation; drift in production |
| leave-one-group-out | retrieval on pairs where field group g differs, for each g | shortcuts |
| synthetic spoof injection | swap the UA group or geo/timezone on held-out rows; AUC of the surprisal score | the consistency head (4.3/4.6) |
| agreement-kernel fit | Spearman of tower cosine vs FS agreement (v3 already logs `spec_spearman`) | spec/pref towers |

## 6. Relation to devicefp v3 and recommendation

### What v3 is, in these terms

- **Four towers:** id, spec, env and pref. Each is a `FieldEncoder`: learned value embeddings
  plus a 2-layer transformer with a CLS token.
- **The full vector** concatenates √w_k-scaled unit sub-vectors. Fitted weights for the best run
  are id 0.80, spec 0.11, env 0.05, pref 0.04.
- **id tower:** SupCon on tmx groups for mobile and on an osId+GPU+screen proxy for web, with
  same-spec hard negatives. This is family **4.1/4.10**: real repeats, keyed by a third-party
  fuzzy linker.
- **spec and pref towers:** MSE between tower cosine and a Fellegi-Sunter agreement fraction over
  their fields. This is **kernel distillation**, close to 4.10. The m-probabilities come from
  devId pairs, which is the only label it touches.
- **env tower:** MSE onto graded network keys (bssid 1.0 > IP+city 0.5 > /24+city 0.15 > city
  0.05). The keys are never inputs. This is a graph-style co-occurrence target (4.7) without the
  graph.
- **Results** (local runs): the served v3 run (`factor_tmxweb_s1`) beats FS on mobile test PR AUC
  (0.825 vs 0.714) and pooled (0.543 vs 0.524) but loses on web (0.456 vs 0.650). The web loss matches v1's diagnosis: web identity relies
  on exact rare values (canvas, fonts hash, header order), which v3's capped, learned-only id
  tower cannot express.

### Ranked recommendation

1. **Masked field modelling as an auxiliary (then pretraining) objective on all rows, with a
   surprisal head.**
   - *Why:* it uses the 48% of training rows that the identity loss never sees. Rubachev et al. found it the most
     reliable tabular objective (contrastive "not superior"). It fits the existing per-field
     transformer with one linear head per field. It produces the consistency/spoof score the v1
     doc listed as a next step.
   - *How:* mask 15-50% of fields; predict the capped class (strings) or bin index (numerics,
     BinRecon). Exclude unique-ish fields from the targets but keep them as inputs. Weight the loss
     by inverse field entropy so common fields do not dominate.
   - *Risk:* it may wash out identity further. Keep it on a separate head and check web PR AUC.
2. **Exact-match identity channel, plus collapse monitoring.**
   - *Why:* this is not SSL, but every SSL addition makes the washing-out problem worse. v1 showed
     that frozen random per-value codes with learned field weights recover the naive-Bayes/FS
     behaviour, and FS is 0.23 PR AUC ahead on web.
   - *How:* add hashed frozen codes (2^18 buckets, as in v1) as a fifth sub-vector, initialised
     from FS weights log(m/u).
   - *Monitoring:* log RankMe and alignment/uniformity for each tower at every eval; add a VICReg
     variance or KoLeo term only if the effective rank of the id tower is well below its 64
     dimensions.
3. **Linker-ensemble pseudo-labels in place of tmx alone (4.10).**
   - *Why:* the id tower currently learns tmx's linking rules. Positives that need tmx and
     (devId or high FS) or (osId and network) agreement, and negatives where linkers disagree
     strongly, reduce label noise.
   - *Evaluation:* devId pairs that were not used to form positives give an independent check.
   - Optionally add SCARF-style instance views for singletons, with per-field corruption matched
     to measured change rates and identity-bearing fields never resampled. Gains here are uncertain:
     v1 found drift augmentation unnecessary when real repeats exist.
4. **Co-occurrence graph embedding as a separate network/farm factor (4.7).**
   - *How:* GraphSAGE-style unsupervised loss over a device–{bssid, IP+city, /24} bipartite
     graph from training rows only, with hub pruning.
   - *Use:* report it as its own similarity (households, farms, proxy pools), not mixed into
     identity. v3's `relatedness` farm-cohesion metric is the first readout.
   - It is valuable for risk scoring but should not raise identity metrics. If it does, check for
     leakage.
5. **Later or only if needed:**
   - T-JEPA between towers (predict the spec latent from pref+env) once 4.3 saturates;
   - SwAV/DINO prototypes on the spec tower for cohort labels;
   - sequence SSL (CL4SRec/BERT4Rec) once user event logs exist.

### Suggested experiments (no training run yet)

All on `data/devicefp/runs/v3`, the same splits and evaluation (`evaluate`), with the FS baseline
alongside. Report mobile and web PR AUC separately, devId gold recall, B-cubed F1, plus RankMe and
uniformity per tower.

| exp | change | success criterion |
|---|---|---|
| E1 | add masked field modelling loss (λ ∈ {0.1, 0.3, 1}) to `train`, mask rate {0.15, 0.3, 0.5}, all train rows | web and mobile PR AUC not worse than `factor_tmxweb`; surprisal AUC ≥ 0.9 on injected UA-group and geo/timezone swaps |
| E2 | E1 as pretraining only (N steps MFM, then current `train`) | as E1; also compare steps to the best validation PR AUC |
| E3 | add a frozen-code exact-match sub-vector (v1 identity channel), FS-initialised | web PR AUC closes most of the gap to FS (0.650) without losing mobile |
| E4 | positives from a linker vote (tmx ∧ (devId ∨ FS ≥ t)), negatives across linkers | devId gold recall up; B-cubed against tmx may fall, which is expected |
| E5 | leave-one-group-out: drop `ip_subnet24`/`ip_geo_cell` from id-tower inputs | measures how much id relies on network shortcuts; if PR AUC barely moves, drop them |
| E6 | label-free selection check: rank E1-E4 checkpoints by RankMe and uniformity, compare with the PR AUC ranking | if the two rankings agree (Spearman ≥ 0.7), RankMe can select models where no devId exists (web) |
| E7 | GraphSAGE unsupervised env factor from training-only edges | farm within-group cosine ≫ random; identity metrics unchanged |

## Claims not verified

- The Airbnb KDD 2018 CTR uplift (about 21%) appears only in secondary sources. The KDD page
  confirms the authors (Grbovic, Cheng) and the "99% of conversions" statement.
- STab has no arXiv version. The description comes from the workshop listing; its exact
  mechanism and numbers were not checked against the PDF.
- Method details marked "paper body" (DeepCluster empty-cluster handling, SAINT
  CutMix/mixup, Airbnb's booked-listing global context, TS2Vec's cropping) come from the papers'
  method sections as I know them. Only the GraphSAGE loss and the CL4SRec augmentations were
  re-read from the PDFs for this note.
- The v3 numbers come from local, uncommitted run outputs under `data/devicefp/runs/v3/`, not from
  a written report.
