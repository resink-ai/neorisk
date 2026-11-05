#!/bin/sh
# Origin evidence: the Kaggle dataset metadata (title, creator, licence, description) and Spider2's resource listing.
curl -sfL "https://www.kaggle.com/api/v1/datasets/view/alexgude/california-traffic-collision-data-from-switrs" \
 | python3 -I -c "import json,sys; d=json.load(sys.stdin); [print(k, '=', repr(d.get(k))[:3000]) for k in ('titleNullable','creatorNameNullable','licenseNameNullable','totalBytesNullable','lastUpdatedNullable','descriptionNullable')]"
echo "--- Spider2 resource dir"
curl -sf "https://api.github.com/repos/xlang-ai/Spider2/contents/spider2-lite/resource/databases/sqlite/California_Traffic_Collision" | python3 -I -c "import json,sys; [print(x['name'], x['size']) for x in json.load(sys.stdin)]"
echo "--- Spider2 collisions.json (head)"
curl -sf "https://raw.githubusercontent.com/xlang-ai/Spider2/main/spider2-lite/resource/databases/sqlite/California_Traffic_Collision/case_ids.json" | head -c 1500
