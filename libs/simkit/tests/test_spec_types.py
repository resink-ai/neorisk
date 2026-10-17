import numpy as np
import pyarrow as pa
import pytest

from neorisk_simkit.spec import dist
from neorisk_simkit.spec.types import (
    COMMON_COLUMNS,
    amount,
    arrow_type,
    boolean,
    cat,
    cat_code,
    f64,
    i16,
    i32,
    i64,
    opt,
    ref,
    storage_dtype,
    text,
    ts,
)


def test_storage_dtypes():
    assert storage_dtype(i16()) == np.int16
    assert storage_dtype(i32()) == np.int32
    assert storage_dtype(i64()) == np.int64
    assert storage_dtype(f64()) == np.float64
    assert storage_dtype(cat("a", "b")) == np.int16
    assert storage_dtype(ref("user")) == np.int64
    assert storage_dtype(amount(asset="USD")) == np.int64
    assert storage_dtype(ts()) == np.int64
    assert storage_dtype(boolean()) == np.uint8


def test_arrow_types():
    assert arrow_type(ts()) == pa.timestamp("us", tz="UTC")
    assert arrow_type(cat("web", "app")) == pa.dictionary(pa.int16(), pa.string())
    assert arrow_type(amount(asset="USD")) == pa.int64()
    assert arrow_type(opt(text())) == pa.string()
    assert arrow_type(boolean()) == pa.bool_()
    assert arrow_type(i16()) == pa.int16()


def test_opt_marks_nullable_and_keeps_kind():
    t = opt(ref("sku"))
    assert t.nullable and t.kind == "ref" and t.target == "sku"
    assert not ref("sku").nullable
    with pytest.raises(ValueError, match="already optional"):
        opt(t)


def test_cat_codes_and_errors():
    c = cat("web", "app", "api")
    assert cat_code(c, "web") == 0 and cat_code(c, "app") == 1
    with pytest.raises(ValueError, match="not a category"):
        cat_code(c, "tv")
    with pytest.raises(ValueError, match="duplicate"):
        cat("a", "a")
    with pytest.raises(ValueError, match="at least one"):
        cat()


def test_constraints_recorded():
    assert i32(min=1).minimum == 1
    a = amount(asset="USD")
    assert a.asset == "USD" and a.quantum == 1


def test_common_columns_order_and_types():
    names = [n for n, _ in COMMON_COLUMNS]
    assert names == ["event_id", "event_type", "event_time", "lamport", "partition_id", "seq",
                     "cause_id", "action_id"]
    d = dict(COMMON_COLUMNS)
    assert d["cause_id"].nullable and not d["event_id"].nullable
    assert d["seq"].kind == "i32" and d["action_id"].kind == "i16"
    assert d["event_time"].kind == "ts"


def test_dist_encode_and_min_latency():
    d = dist.shifted_lognormal(min_ms=150, median_ms=240)
    code, _, _, _ = dist.encode(d)
    assert code == dist.SHIFTED_LOGNORMAL
    assert dist.min_us(d) == 150_000
    assert dist.min_us(dist.constant(ms=300)) == 300_000
    assert dist.min_us(dist.exp(mean_s=5)) == 0
    assert dist.encode(dist.constant(s=2)) == (dist.CONST, 2_000_000.0, 0.0, 0.0)


def test_dist_validation():
    with pytest.raises(ValueError):
        dist.lognormal(median_s=-1)
    with pytest.raises(ValueError, match="sum to 1"):
        dist.categorical({"a": 0.5, "b": 0.6})
    with pytest.raises(ValueError):
        dist.shifted_lognormal(min_ms=300, median_ms=200)
    c = dist.categorical({"x": 0.25, "y": 0.75})
    assert c.labels == ("x", "y") and c.weights == (0.25, 0.75)


NAN, INF = float("nan"), float("inf")


@pytest.mark.parametrize("make", [
    lambda: dist.constant(ms=NAN), lambda: dist.constant(s=INF),
    lambda: dist.normal(mean_h=NAN), lambda: dist.normal(mean_h=INF),
    lambda: dist.normal(sd_h=NAN), lambda: dist.normal(sd_h=INF),
    lambda: dist.categorical({"a": NAN, "b": 1.0}), lambda: dist.categorical({"a": NAN}),
    lambda: dist.categorical({"a": INF, "b": 0.0}),
    lambda: dist.exp(mean_s=INF), lambda: dist.lognormal(median_s=1, sigma=INF),
    lambda: dist.shifted_lognormal(min_ms=NAN, median_ms=200),
    lambda: dist.shifted_lognormal(min_ms=0, median_ms=INF),
    lambda: dist.gamma(mean_days=1, max_days=INF), lambda: dist.pareto(alpha=INF, min_h=1),
    lambda: dist.geometric(mean=INF), lambda: dist.negbinom(mean=1, disp=INF),
    lambda: dist.uniform_int(lo=NAN, hi=3), lambda: dist.zipf(s=INF),
    lambda: dist.poisson_daily(weekly=(1, 1, 1, NAN, 1, 1, 1)),
    lambda: dist.poisson_daily(trend=NAN), lambda: dist.lognormal_minor(median=NAN, sigma=1),
    lambda: dist.geometric(2, max=NAN), lambda: dist.geometric(2, max=INF),
    lambda: dist.lognormal_minor(100, 1, min=NAN), lambda: dist.lognormal_minor(100, 1, max=INF),
    lambda: dist.uniform_int(lo=0, hi=INF),
], ids=lambda f: "")
def test_dist_rejects_non_finite_parameters(make):
    """A NaN (or meaningless infinite) parameter is refused, never sampled into garbage."""
    with pytest.raises(ValueError, match="finite|> 0|>= 1"):
        make()


@pytest.mark.parametrize("make", [
    lambda: dist.geometric(2, max=2.5), lambda: dist.geometric(2, max=-1),
    lambda: dist.geometric(2, max=2**63),
    lambda: dist.lognormal_minor(100, 1, min=1.5), lambda: dist.lognormal_minor(100, 1, min=-1),
    lambda: dist.lognormal_minor(100, 1, max=2**63), lambda: dist.uniform_int(lo=0.5, hi=3),
    lambda: dist.uniform_int(lo=0, hi=2**63), lambda: dist.uniform_int(lo=-(2**63), hi=0),
], ids=lambda f: "")
def test_dist_rejects_bounds_outside_the_integer_range(make):
    """Optional bounds are integers that sampling can hold (Codex CX4)."""
    with pytest.raises(ValueError, match="integer|2\\*\\*62"):
        make()


def test_dist_integer_bounds_in_range_are_kept():
    assert dist.geometric(2, max=5).params[1] == 5.0
    assert dist.lognormal_minor(100, 1, min=0, max=2**62).weights == (0.0, float(2**62))
    assert dist.uniform_int(-3, 3).params[:2] == (-3.0, 3.0)
