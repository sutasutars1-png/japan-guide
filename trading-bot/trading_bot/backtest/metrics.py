"""Performance metrics computed from a backtest's equity curve and trade log."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def total_return(equity: pd.Series) -> float:
    if len(equity) < 2 or equity.iloc[0] == 0:
        return 0.0
    return float(equity.iloc[-1] / equity.iloc[0] - 1.0)


def cagr(equity: pd.Series, periods_per_year: float) -> float:
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return 0.0
    n_periods = len(equity) - 1
    years = n_periods / periods_per_year
    if years <= 0:
        return 0.0
    total = equity.iloc[-1] / equity.iloc[0]
    if total <= 0:
        return -1.0
    return float(total ** (1.0 / years) - 1.0)


def sharpe_ratio(returns: pd.Series, periods_per_year: float, risk_free: float = 0.0) -> float:
    excess = returns - risk_free / periods_per_year
    std = excess.std()
    if std == 0 or math.isnan(std):
        return 0.0
    return float(excess.mean() / std * math.sqrt(periods_per_year))


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    return float(drawdown.min())


def win_rate(trades: list[dict]) -> float:
    closed = [t for t in trades if t.get("pnl") is not None]
    if not closed:
        return 0.0
    wins = sum(1 for t in closed if t["pnl"] > 0)
    return wins / len(closed)


def summarize(equity: pd.Series, returns: pd.Series, trades: list[dict], periods_per_year: float) -> dict:
    return {
        "total_return": total_return(equity),
        "cagr": cagr(equity, periods_per_year),
        "sharpe": sharpe_ratio(returns, periods_per_year),
        "ann_return": float(returns.mean() * periods_per_year) if len(returns) else 0.0,
        "max_drawdown": max_drawdown(equity),
        "win_rate": win_rate(trades),
        "num_trades": len([t for t in trades if t.get("pnl") is not None]),
        "final_equity": float(equity.iloc[-1]) if len(equity) else 0.0,
    }
