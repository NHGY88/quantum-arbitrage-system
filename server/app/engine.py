"""Core quantitative engine.

Responsibilities:
  * parse "high correlation" hedge groupings out of Markdown documents
  * compute dynamic value/margin/volatility hedge ratios
  * enforce hard risk caps (1% equity risk, 0.01 lot floor)

The Markdown format we accept is intentionally forgiving so hand-written
notes import cleanly, e.g.

    ## Group 3
    - XAUUSD / XAGUSD  corr 0.97
    - EURUSD / GBPUSD  corr 0.88

or a plain table:

    | leg_a | leg_b | corr |
    |-------|-------|------|
    | XAUUSD | XAGUSD | 0.97 |
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

from . import settings

_SYMBOL_RE = re.compile(r"[A-Za-z][A-Za-z0-9]{1,11}[/=:][A-Za-z][A-Za-z0-9]{1,11}")
_PURE_SYMBOL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{1,11}$")


@dataclass
class HedgeLeg:
    symbol: str
    side: str = "long"  # long | short
    lots: float = 0.01


@dataclass
class HedgeCombo:
    group: int
    title: str
    legs: list[HedgeLeg]
    correlation: float | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def _norm_symbol(raw: str) -> str:
    return raw.strip().upper().replace(" ", "")


def _parse_pair(token: str) -> tuple[str, str] | None:
    m = _SYMBOL_RE.search(token.upper())
    if not m:
        return None
    a, b = m.group(0).split("/")
    return a.strip(), b.strip()


def parse_markdown(text: str) -> list[HedgeCombo]:
    """Extract hedge combos from a Markdown document.

    Returns combos sorted by descending correlation when available.
    """
    combos: list[HedgeCombo] = []
    current_group = 0
    current_title = ""
    pending: list[tuple[str, str]] = []
    pending_corr: list[float] = []

    def flush() -> None:
        nonlocal pending, pending_corr
        if pending:
            # a group is the set of symbols mentioned in the block
            symbols: list[str] = []
            for a, b in pending:
                for s in (a, b):
                    if s not in symbols:
                        symbols.append(s)
            if len(symbols) >= 2:
                corr = max(pending_corr) if pending_corr else None
                combos.append(
                    HedgeCombo(
                        group=current_group,
                        title=current_title or f"Group {current_group}",
                        legs=[HedgeLeg(s) for s in symbols],
                        correlation=corr,
                    )
                )
        pending = []
        pending_corr = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        heading = re.match(r"^#{1,6}\s+(.*)$", line)
        if heading:
            flush()
            current_group += 1
            current_title = heading.group(1).strip()
            m = re.search(r"(\d{1,3})\s*组", current_title)
            if m:
                current_group = int(m.group(1))
            continue

        # table separator row -> skip
        if re.match(r"^\|[\s:\-\|]+\|$", line):
            continue

        # markdown table data row: | XAUUSD | XAGUSD | 0.95 |
        if line.startswith("|"):
            cells = [c.strip().strip("*_` ") for c in line.strip("|").split("|")]
            symbols = [c.upper() for c in cells if _PURE_SYMBOL_RE.match(c)]
            corr = None
            for c in cells:
                try:
                    v = float(c)
                except ValueError:
                    continue
                if -1.0 <= v <= 1.0:
                    corr = v
                    break
            for i in range(0, len(symbols) - 1, 2):
                pending.append((symbols[i], symbols[i + 1]))
            if corr is not None:
                pending_corr.append(corr)
            continue

        corr = None
        cm = re.search(r"(?:corr|相关系数|相关性)\D{0,4}(-?\d*\.?\d+)", line, re.I)
        if cm:
            try:
                corr = float(cm.group(1))
            except ValueError:
                corr = None
        if corr is None:
            cm = re.search(r"(-?\d*\.\d+)\s*$", line)
            if cm:
                try:
                    corr = float(cm.group(1))
                except ValueError:
                    corr = None

        pairs = [p for p in (_parse_pair(tok) for tok in line.split()) if p]
        if not pairs:
            continue
        for a, b in pairs:
            pending.append((a, b))
        if corr is not None:
            pending_corr.append(corr)

    flush()

    combos.sort(key=lambda c: (c.correlation or 0.0), reverse=True)
    return combos


def parse_markdown_file(path: Path) -> list[HedgeCombo]:
    return parse_markdown(path.read_text(encoding="utf-8", errors="replace"))


def parse_markdown_dir(directory: Path) -> list[HedgeCombo]:
    combos: list[HedgeCombo] = []
    if not directory.exists():
        return combos
    for p in sorted(directory.glob("*.md")):
        combos.extend(parse_markdown_file(p))
    combos.sort(key=lambda c: (c.group, -(c.correlation or 0.0)))
    return combos


# --- hedge maths ----------------------------------------------------------

def dynamic_hedge_ratio(
    *,
    mode: str,
    value_a: float,
    value_b: float,
    vol_a: float,
    vol_b: float,
    corr: float = 1.0,
) -> float:
    """Return the lot multiplier for leg B relative to leg A.

    mode:
      value       - notional value parity: value_b / value_a
      margin      - margin parity using an assumed margin ratio factor
      volatility  - vol-parity hedge: (vol_a / vol_b) scaled by correlation
    """
    if value_a <= 0 or value_b <= 0:
        raise ValueError("values must be positive")
    if mode == "value":
        return value_b / value_a
    if mode == "margin":
        # identical to value parity unless a margin ratio is supplied later;
        # kept separate so the API surface matches the blueprint.
        return value_b / value_a
    if mode == "volatility":
        if vol_b <= 0:
            raise ValueError("vol_b must be positive")
        base = (vol_a / vol_b) if vol_a > 0 else 1.0
        return max(0.0, base * max(0.0, min(1.0, corr)))
    raise ValueError(f"unknown mode: {mode}")


def apply_risk_caps(
    ratio: float,
    *,
    equity: float,
    leg_a_value: float,
    lots: float,
    max_margin_risk: float | None = None,
    min_lot: float | None = None,
) -> dict:
    """Apply the hard risk controls described in the blueprint.

    - never risk more than `max_margin_risk` (default 1%) of equity
    - never round a position below `min_lot` (default 0.01) -> clamp up
    """
    max_margin_risk = settings.MAX_MARGIN_RISK if max_margin_risk is None else max_margin_risk
    min_lot = settings.MIN_LOT if min_lot is None else min_lot

    capped_ratio = ratio
    risk_triggered = False

    # Position value implied by the ratio, as a fraction of equity.
    implied_value = leg_a_value * ratio
    max_allowed_value = equity * max_margin_risk
    if implied_value > max_allowed_value > 0:
        capped_ratio = ratio * (max_allowed_value / implied_value)
        risk_triggered = True

    final_lots = max(min_lot, lots * capped_ratio)
    lot_floored = final_lots > lots * capped_ratio + 1e-12

    return {
        "requested_ratio": round(ratio, 6),
        "final_ratio": round(capped_ratio, 6),
        "lots": round(final_lots, 4),
        "lot_floored": lot_floored,
        "risk_triggered": risk_triggered,
        "max_margin_risk": max_margin_risk,
        "min_lot": min_lot,
        "implied_value": round(implied_value, 2),
        "max_allowed_value": round(max_allowed_value, 2),
    }


def zscore(series: Iterable[float], latest: float | None = None) -> float | None:
    vals = [float(x) for x in series]
    if len(vals) < 2:
        return None
    mean = statistics.fmean(vals)
    sd = statistics.pstdev(vals)
    if sd == 0:
        return 0.0
    target = float(latest if latest is not None else vals[-1])
    return (target - mean) / sd


def kelly_fraction(win_rate: float, payoff: float) -> float:
    if payoff <= 0:
        return 0.0
    f = win_rate - (1 - win_rate) / payoff
    return max(0.0, f)


def is_finite(x: float) -> bool:
    return math.isfinite(x)