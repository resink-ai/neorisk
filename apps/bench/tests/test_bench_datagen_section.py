from bench.datagen_section import render_datagen


def _run():
    return {
        "dataset_meta": {
            "config": {"n_events": 500000, "seed": 42, "target_bad_rate": 0.02},
            "observed": {"n_users": 24000, "n_bad": 9991},
        }
    }


def test_datagen_section_zh_and_en_show_config_and_pipeline():
    zh = render_datagen(_run(), "zh")
    en = render_datagen(_run(), "en")
    assert "生成流程" in zh and "Generation pipeline" in en
    assert "500,000" in zh and "24,000" in en
    assert "inv_zombie_mean_30d" in en


def test_datagen_section_without_meta_still_renders():
    assert "<table" in render_datagen({}, "en")
