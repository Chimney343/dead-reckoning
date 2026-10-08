"""The extractor return contract (plan section 4)."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class Extract:
    losses: pd.DataFrame
    events: pd.DataFrame
