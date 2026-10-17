import numpy as np
import pytest

from neorisk_simkit.engine import identity as ident
from neorisk_simkit.engine import rng
from neorisk_simkit.spec import dist


def test_key_uniform_deterministic_and_sensitive_to_every_key_part():
    base = rng.key_uniform(42, 7, 1, 3, 5, 0)
    assert 0.0 <= base < 1.0 and base == rng.key_uniform(42, 7, 1, 3, 5, 0)
    others = [rng.key_uniform(43, 7, 1, 3, 5, 0), rng.key_uniform(42, 8, 1, 3, 5, 0),
              rng.key_uniform(42, 7, 2, 3, 5, 0), rng.key_uniform(42, 7, 1, 4, 5, 0),
              rng.key_uniform(42, 7, 1, 3, 6, 0), rng.key_uniform(42, 7, 1, 3, 5, 1)]
    assert len(set(others + [base])) == 7


def test_key_uniform_is_roughly_uniform():
    u = np.array([rng.key_uniform(1, 2, 3, 4, 5, k) for k in range(100_000)])
    assert abs(u.mean() - 0.5) < 0.005 and u.min() >= 0 and u.max() < 1


def test_python_and_compiled_agree():
    assert rng.key_uniform.py_func(42, 7, 1, 3, 5, 9) == rng.key_uniform(42, 7, 1, 3, 5, 9)
    assert ident.feistel63.py_func(123, ident.feistel_key(1, "user")) == ident.feistel63(
        123, ident.feistel_key(1, "user"))


def test_negative_and_high_bit_keys_work_uncompiled():
    # instance keys live in int64 arrays, so half of them are negative; the uncompiled leg
    # (NUMBA_DISABLE_JIT=1) must accept them and agree bit for bit with the compiled code
    for name in ("user", "order", "device", "sku", "session", "payment", "item", "note"):
        assert 0 <= rng.name_key(name) < 2**64
        keys = ident.feistel_key(7, name)
        assert keys.dtype == np.uint64 and len(keys) == 4
    u_py = rng.key_uniform.py_func(42, -12345, 1, 3, 5, 0)
    assert u_py == rng.key_uniform(42, -12345, 1, 3, 5, 0) and 0.0 <= u_py < 1.0
    assert int(rng.mix64.py_func(-1)) == int(rng.mix64(-1))
    assert int(rng.mix64.py_func(2**64 - 1)) == int(rng.mix64(-1))


def test_next_k_counts_per_site():
    kc = np.zeros(33, np.int64)
    assert [rng.next_k(kc, 5), rng.next_k(kc, 5), rng.next_k(kc, 9), rng.next_k(kc, 5)] == [
        0, 1, 0, 2]
    kc[0] = 0                                    # reset per invocation
    assert rng.next_k(kc, 5) == 0


def test_duration_samplers():
    c, a, b, d = dist.encode(dist.constant(ms=300))
    assert rng.sample_us(c, a, b, d, 0.3, 0.7) == 300_000
    c, a, b, d = dist.encode(dist.shifted_lognormal(min_ms=150, median_ms=240))
    xs = [rng.sample_us(c, a, b, d, rng.key_uniform(1, 1, 1, 1, 1, k),
                        rng.key_uniform(1, 1, 1, 1, 2, k)) for k in range(2000)]
    assert min(xs) >= 150_000 and 200_000 < float(np.median(xs)) < 280_000
    c, a, b, d = dist.encode(dist.exp(mean_s=10))
    xs = [rng.sample_us(c, a, b, d, rng.key_uniform(2, 1, 1, 1, 1, k), 0.5) for k in range(20000)]
    assert 9.5e6 < np.mean(xs) < 10.5e6


def test_feistel_is_a_positive_bijection_per_table():
    keys = ident.feistel_key(7, "order")
    dense = np.arange(200_000, dtype=np.int64)
    out = ident.feistel63_array(dense, keys)
    assert len(np.unique(out)) == len(out) and out.min() >= 1
    other = ident.feistel63_array(dense, ident.feistel_key(7, "user"))
    assert (out != other).mean() > 0.999
    assert not np.array_equal(out, ident.feistel63_array(dense, ident.feistel_key(8, "order")))


def test_handles_roundtrip_and_flag():
    h = ident.make_handle(5, 1_000_000, 77)
    assert ident.is_provisional(h) and not ident.is_provisional(12345)
    assert (ident.handle_ns(h), ident.handle_slot(h), ident.handle_ordinal(h)) == (5, 1_000_000, 77)
    assert 0 < h < 2**63


def test_assign_dense_orders_by_pid_then_ordinal():
    pids = np.array([30, 10, 10, 20], np.int64)
    ords = np.array([0, 1, 0, 0], np.int64)
    assert ident.assign_dense(pids, ords, 100).tolist() == [103, 101, 100, 102]


def test_remap_inplace():
    h1, h2 = ident.make_handle(0, 1, 0), ident.make_handle(0, 2, 0)
    src = np.sort(np.array([h1, h2], np.int64))
    dst = np.array([10, 11], np.int64) if src[0] == h1 else np.array([11, 10], np.int64)
    vals = np.array([h2, 5, h1, -(2**63)], np.int64)
    missing = ident.remap_inplace(vals, src, dst)
    assert missing == 0 and vals.tolist() == [11, 5, 10, -(2**63)]
    vals2 = np.array([ident.make_handle(0, 9, 9)], np.int64)
    assert ident.remap_inplace(vals2, src, dst) == 1


def test_generated_source_is_keyed_and_bounded(fixture_project):
    from neorisk_simkit.spec.project import load_project, resolve_run
    run = resolve_run(load_project(fixture_project("mini")), "sample", [])
    item = run.plan.table("item")
    cols = item.source.generate(40, item, seed=run.seed, stream=1)
    again = item.source.generate(40, item, seed=run.seed, stream=1)
    assert set(cols) == {"bin", "price"} and np.array_equal(cols["bin"], again["bin"])
    assert cols["bin"].min() >= 0 and cols["bin"].max() <= 3
    with pytest.raises(ValueError, match="row count"):
        item.source.generate(41, item, seed=run.seed, stream=1)


def test_negbinom_large_mean_and_no_truncation():
    d = dist.negbinom(mean=1e5, disp=2000)
    u = rng.uniforms(3, 4, 20_000)
    x = dist.sample_np(d, u, rng.uniforms(3, 5, 20_000))
    assert abs(x.mean() - 1e5) < 1e3 and x.std() > 1000
    d = dist.negbinom(mean=500, disp=0.5)
    x = dist.sample_np(d, rng.uniforms(3, 6, 200_000), u[:1].repeat(200_000))
    assert abs(x.mean() - 500) < 25
    with pytest.raises(ValueError, match="too large"):
        dist.sample_np(dist.negbinom(mean=1e12, disp=1), u[:5], u[:5])


def test_sample_us_is_finite_for_heavy_tails():
    c, a, b, d = dist.encode(dist.pareto(alpha=0.3, min_h=1))
    u = np.nextafter(1.0, 0.0)
    for f in (rng.sample_us, getattr(rng.sample_us, "py_func", rng.sample_us)):
        v = f(c, a, b, d, u, 0.5)
        assert 0 <= v <= 2**62
    with pytest.raises(ValueError, match="duration"):
        rng.sample_us(dist.UNIFORM_INT, 0.0, 3.0, 0.0, 0.5, 0.5)


def test_mix_is_variadic_and_order_sensitive():
    assert rng.mix(5) == int(rng.mix64(5))
    assert rng.mix(1, 2) == int(rng.mix64(int(rng.mix64(1)) ^ 2))
    assert rng.mix(1, 2) != rng.mix(2, 1) and rng.mix(1, 2, 3) != rng.mix(1, 2)
    assert 0 <= rng.mix(-1, 2**64 - 1, 7) < 2**64


def test_feistel_rejects_out_of_domain():
    keys = ident.feistel_key(1, "user")
    for bad in (-1, 2**63 - 1):
        with pytest.raises(ValueError, match="domain"):
            ident.feistel63(bad, keys)
        with pytest.raises(ValueError, match="domain"):
            getattr(ident.feistel63, "py_func", ident.feistel63)(bad, keys)
    with pytest.raises(ValueError, match="domain"):
        ident.feistel63_array(np.array([0, -5], np.int64), keys)


@pytest.mark.parametrize("mean,disp", [(1000, 0.01), (50, 0.05)])
def test_negbinom_small_disp_is_not_clamped(mean, disp):
    n = 200_000
    u = rng.uniforms(9, 1, n)
    x = dist.sample_np(dist.negbinom(mean=mean, disp=disp), u, u)
    assert x.max() < 5_000_000 and (x == x.max()).sum() <= 2
    assert abs(x.mean() - mean) < 0.1 * mean


def test_negbinom_tail_beyond_cap_raises():
    u = rng.uniforms(9, 2, 1000)
    with pytest.raises(ValueError, match="too large"):
        dist.sample_np(dist.negbinom(mean=1e4, disp=0.001), u, u)


def test_sample_us_nan_is_zero():
    c, _a, b, d = dist.encode(dist.normal(mean_h=1, sd_h=1))
    for f in (rng.sample_us, getattr(rng.sample_us, "py_func", rng.sample_us)):
        assert f(c, float("nan"), b, d, 0.3, 0.7) == 0


def test_geometric_sample_np_matches_the_kernel_draw():
    u = rng.uniforms(3, 7, 50_000)
    x = dist.sample_np(dist.geometric(mean=12.0), u, u)
    assert x.min() >= 1 and abs(x.mean() - 12.0) < 0.3
    want = [rng.geometric.py_func(12.0, float(v)) for v in u[:200]]
    assert x[:200].tolist() == want
    assert dist.sample_np(dist.geometric(mean=12.0, max=5), u, u).max() == 5
    assert (dist.sample_np(dist.geometric(mean=1.0), u[:9], u[:9]) == 1).all()
