import pytest

from datagen.cli import main


@pytest.mark.parametrize("argv", [
    ["generate"],
    ["generate", "--scenario", "fraud", "--n-events", "3000", "--seed", "3", "--out", "x"],
    ["generate", "--help"],
])
def test_generate_points_to_the_replacement(argv, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(argv) == 2
    cap = capsys.readouterr()
    assert cap.out == ""
    assert cap.err.strip() == (
        "datagen generate was replaced (M3): datagen run examples/ecommerce --profile legacy && "
        "datagen export <run dir> --legacy-fraud --out <dir>")
    assert "datagen run examples/ecommerce --profile legacy" in cap.err
    assert "datagen export <run dir> --legacy-fraud" in cap.err
    assert not any(tmp_path.iterdir())                    # nothing written


def test_export_needs_legacy_fraud(tmp_path, capsys):
    out = tmp_path / "o"
    assert main(["export", str(tmp_path), "--out", str(out)]) == 2
    assert "only --legacy-fraud exists in M3" in capsys.readouterr().err
    assert main(["export", str(tmp_path), "--legacy-fraud"]) == 2      # --out is required
    assert "--out DIR is required" in capsys.readouterr().err
    assert not out.exists()
