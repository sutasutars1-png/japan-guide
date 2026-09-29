from .base import Strategy
from .more import DonchianBreakoutStrategy, MultiStrategy, RSIReversionStrategy
from .moving_average import SMACrossoverStrategy

STRATEGIES = {
    s.name: s for s in (SMACrossoverStrategy, DonchianBreakoutStrategy, RSIReversionStrategy, MultiStrategy)
}

__all__ = [
    "Strategy",
    "SMACrossoverStrategy",
    "DonchianBreakoutStrategy",
    "RSIReversionStrategy",
    "MultiStrategy",
    "STRATEGIES",
]
