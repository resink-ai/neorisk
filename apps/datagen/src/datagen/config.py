from dataclasses import dataclass


@dataclass(frozen=True)
class FraudConfig:
    n_events: int = 100_000
    seed: int = 0
    span_days: int = 90
    target_bad_rate: float = 0.02
    invite_frac: float = 0.15  # share of users that were invited by someone
    hunter_prob: float = 0.4  # chance an invite comes from a bounty hunter
    users_per_event: float = 0.05

    @property
    def n_users(self) -> int:
        return max(50, int(self.n_events * self.users_per_event))

    @property
    def n_devices(self) -> int:
        return max(10, int(self.n_users * 0.8))

    @property
    def n_products(self) -> int:
        return 200

    @property
    def n_hunters(self) -> int:
        return max(3, self.n_users // 100)

    def validate(self) -> None:
        if self.n_events < 100:
            raise ValueError("n_events must be >= 100")
        if self.span_days < 1:
            raise ValueError("span_days must be >= 1")
        if not 0 < self.target_bad_rate < 1:
            raise ValueError("target_bad_rate must be in (0, 1)")
        if not 0 <= self.invite_frac <= 1 or not 0 <= self.hunter_prob <= 1:
            raise ValueError("invite_frac and hunter_prob must be in [0, 1]")
        if self.users_per_event <= 0:
            raise ValueError("users_per_event must be > 0")
