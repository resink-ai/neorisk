import numba

from neorisk_simkit.std import handoff as h


def test_redeem_outcomes():
    assert h.redeem(h.OPEN, 1_000, 999, 7, 7) == h.OK
    assert h.redeem(h.OPEN, 1_000, 1_000, 7, 7) == h.REJ_EXPIRED       # exactly at expiry
    assert h.redeem(h.EXPIRED, 1_000, 10, 7, 7) == h.REJ_EXPIRED
    assert h.redeem(h.REDEEMED, 1_000, 10, 7, 7) == h.REJ_ALREADY
    assert h.redeem(h.DONE, 1_000, 10, 7, 7) == h.REJ_ALREADY
    assert h.redeem(h.OPEN, 1_000, 10, 7, 8) == h.REJ_UNKNOWN          # token bound to the flow


def test_expire_only_from_open():
    assert h.expire(h.OPEN) == h.EXPIRED
    assert h.expire(h.REDEEMED) == h.REDEEMED and h.expire(h.NONE) == h.NONE


def test_compiled_matches_python():
    f = numba.njit(lambda s, e, t: h.redeem(s, e, t, 1, 1))
    for args in [(h.OPEN, 5, 4), (h.OPEN, 5, 5), (h.REDEEMED, 5, 1)]:
        assert f(*args) == h.redeem.py_func(*args, 1, 1)
