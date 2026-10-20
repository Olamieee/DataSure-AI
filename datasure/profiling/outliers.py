"""Statistical outlier detection helpers.

Two complementary, well-understood methods are used:
- IQR (Tukey) method: works with skewed/non-normal data.
- Z-score method: assumes roughly normal distributions.
Neither method "confirms" an outlier; both are standard heuristics, and their
results are presented with the method used and the parameters applied.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def iqr_bounds(series: pd.Series, factor: float = 1.5) -> tuple[float, float] | None:
    clean = series.dropna()
    if clean.empty or len(clean) < 4:
        return None
    q1, q3 = clean.quantile(0.25), clean.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return (float(q1), float(q3))  # degenerate range
    return (float(q1 - factor * iqr), float(q3 + factor * iqr))


def iqr_outliers(series: pd.Series, factor: float = 1.5) -> int:
    bounds = iqr_bounds(series, factor)
    if bounds is None:
        return 0
    lo, hi = bounds
    clean = series.dropna()
    return int(((clean < lo) | (clean > hi)).sum())


def zscore_outliers(series: pd.Series, threshold: float = 3.0) -> int:
    clean = series.dropna()
    if len(clean) < 8:
        return 0
    std = float(clean.std(ddof=1))
    if not np.isfinite(std) or std == 0:
        return 0
    z = (clean - clean.mean()).abs() / std
    return int((z > threshold).sum())
