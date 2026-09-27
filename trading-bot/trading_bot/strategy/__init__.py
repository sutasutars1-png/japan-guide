from .base import Strategy
from .moving_average import SMACrossoverStrategy

STRATEGIES = {
    "sma_crossover": SMACrossoverStrategy,
}

__all__ = ["Strategy", "SMACrossoverStrategy", "STRATEGIES"]
