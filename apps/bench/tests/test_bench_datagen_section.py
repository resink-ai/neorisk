from bench.datagen_section import render_datagen


def _run():
    return {
        "dataset_meta": {
            "scenario": "ecommerce+bounty_hunters", "seed": 42, "n_events": 500000,
            "bad_rate": 0.02,
            "source": {"pack": "ecommerce", "revision": "3b782a2",
                       "overlays": {"bounty_hunters": {"size": 12, "share_device": 0.7}},
                       "run": "legacy-s42+bounty_hunters"},
            "observed": {"n_users": 24000, "n_bad": 9991},
        }
    }


def test_datagen_section_zh_and_en_show_config_and_pipeline():
    zh = render_datagen(_run(), "zh")
    en = render_datagen(_run(), "en")
    assert "生成流程" in zh and "Generation pipeline" in en
    assert "500,000" in zh and "24,000" in en
    assert "invr_bonus_{count,sum,mean,max}_{7,14,30}d" in en
    for page in (zh, en):
        assert "legacy-s42+bounty_hunters" in page and "3b782a2" in page
        assert "bounty_hunters.size" in page and "bounty_hunters.share_device" in page
    assert "bounty_hunters" in en and "Pool draining" in en and "Shared devices" in en
    assert "fraud scenario" not in en


def test_datagen_section_without_meta_still_renders():
    assert "<table" in render_datagen({}, "en")
