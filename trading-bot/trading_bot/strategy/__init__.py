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

STRATEGIES = {
    s.name: s
    for s in (
        SMACrossoverStrategy, DonchianBreakoutStrategy, RSIReversionStrategy, MultiStrategy,
        SMACrossoverLongShort, DonchianBreakoutLongShort, RSIReversionLongShort, MultiLongShort,
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
