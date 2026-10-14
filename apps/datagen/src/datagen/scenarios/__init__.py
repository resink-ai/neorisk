from collections.abc import Callable

from datagen.config import FraudConfig
from datagen.scenarios import fraud
from neorisk_simkit import Dataset

SCENARIOS: dict[str, Callable[[FraudConfig], Dataset]] = {"fraud": fraud.generate}
