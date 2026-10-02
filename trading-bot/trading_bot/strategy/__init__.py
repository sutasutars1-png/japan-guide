from .base import Strategy
from .more import (
    DonchianBreakoutLongShort,
    DonchianBreakoutStrategy,
    MultiLongShort,
    MultiStrategy,
    RSIReversionLongShort,
    RSIReversionStrategy,
    SMACrossoverLongShort,
)
from .moving_average import SMACrossoverStrategy
from .signals import MomentumLongShort, ShockReversionLongShort, TrendStrengthLongShort

STRATEGIES = {
    s.name: s
    for s in (
        SMACrossoverStrategy, DonchianBreakoutStrategy, RSIReversionStrategy, MultiStrategy,
        SMACrossoverLongShort, DonchianBreakoutLongShort, RSIReversionLongShort, MultiLongShort,
        MomentumLongShort, TrendStrengthLongShort, ShockReversionLongShort,
    )
}

__all__ = [
    "Strategy",
    "SMACrossoverStrategy",
    "DonchianBreakoutStrategy",
    "RSIReversionStrategy",
    "MultiStrategy",
    "STRATEGIES",
]
