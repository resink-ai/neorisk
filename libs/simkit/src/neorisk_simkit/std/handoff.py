"""Cross-device handoff tokens (e.g. a KYC QR code shown on a desktop, scanned on a phone).

A flow issues one token that expires at `expires_at`. Redemption is decided by `redeem`; a scan
at exactly the expiry instant counts as expired (§06: the expiry command runs first because
`PRIO_EXPIRY < PRIO_TIMER`, and `redeem` itself treats `t >= expires_at` as expired).
"""

from numba import njit

# token status
NONE = 0
OPEN = 1
REDEEMED = 2
EXPIRED = 3
DONE = 4

# redemption outcome
OK = 0
REJ_EXPIRED = 1
REJ_ALREADY = 2
REJ_UNKNOWN = 3


@njit(cache=True)
def redeem(status, expires_at, t, token, presented):
    """Outcome of presenting `presented` at time `t` to a flow whose token is `token`."""
    if presented != token:
        return REJ_UNKNOWN
    if status == REDEEMED or status == DONE:
        return REJ_ALREADY
    if status == EXPIRED or t >= expires_at:
        return REJ_EXPIRED
    if status == OPEN:
        return OK
    return REJ_UNKNOWN                                     # no flow was ever opened


@njit(cache=True)
def expire(status):
    """Status after the expiry instant: only an open token expires."""
    if status == OPEN:
        return EXPIRED
    return status
