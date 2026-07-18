"""
Signal stabilizer — turns a noisy per-day raw score into a stable, trustworthy
signal + confidence.

The old scorer flipped Buy↔Sell overnight because (a) the "confidence" number
measured indicator *agreement* rather than conviction, so it read high in BOTH
directions near a boundary, and (b) hard score thresholds with no memory meant a
one-point wiggle jumped a state line. This module fixes both:

  1. SMOOTHING — today's raw score is blended with the prior smoothed score
     (an EMA). A single-day spike can no longer move the headline number much,
     so flipping a signal now takes a *sustained* multi-day move, not one bar.

  2. HYSTERESIS — the signal only changes when the smoothed score crosses a
     boundary *decisively*. Each state has a dead-band: e.g. you enter BUY at
     ≥65 but don't leave it until <61. A stock parked on the fence stays put.

  3. HONEST CONFIDENCE — confidence is HIGH only when the smoothed score sits
     well *inside* a state (far from every boundary) AND recent scores have been
     consistent AND the indicators agree. A score sitting on a threshold reports
     LOW confidence, by construction. It can no longer read 90% on a coin-flip.

This module is pure: callers pass in the prior stored rows and get back the new
row to persist. No DB or network access here, so it is trivially testable.
"""

from __future__ import annotations

# Weight on *today's* raw score in the EMA; the rest carries yesterday's
# smoothed value. 0.5 → a genuine 2-day move is needed to shift the signal.
SMOOTHING_ALPHA = 0.5

# How many points a score must travel *past* a boundary before the signal is
# allowed to leave its current state. This is the hysteresis dead-band.
HYSTERESIS_BUFFER = 4.0

# How many prior days of smoothed scores feed the consistency term.
CONSISTENCY_LOOKBACK = 5

# Band tables: (lower_threshold, name), highest first. A score >= threshold and
# below the next-higher threshold falls in that band.
BANDS_4 = [(65.0, "buy"), (52.0, "watch"), (38.0, "hold"), (float("-inf"), "sell")]
BANDS_5 = [
    (78.0, "strong buy"),
    (65.0, "buy"),
    (52.0, "watch"),
    (38.0, "hold"),
    (float("-inf"), "sell"),
]


def _band_of(score: float, bands: list[tuple[float, str]]) -> int:
    """Index of the band a raw score falls into (no hysteresis)."""
    for i, (thresh, _name) in enumerate(bands):
        if score >= thresh:
            return i
    return len(bands) - 1


def _derive_signal(score: float, prev: str | None, bands: list[tuple[float, str]]) -> str:
    """
    Band the score falls into, made sticky by a hysteresis buffer so the signal
    does not leave its previous state unless the score moves decisively past the
    relevant boundary.
    """
    base_idx = _band_of(score, bands)
    names = [b[1] for b in bands]
    if prev not in names:
        return names[base_idx]
    prev_idx = names.index(prev)
    if base_idx == prev_idx:
        return prev

    if base_idx > prev_idx:
        # Score moved DOWN (more bearish). Stay in prev unless we drop clearly
        # below prev band's own lower threshold.
        lower_edge = bands[prev_idx][0]
        if score >= lower_edge - HYSTERESIS_BUFFER:
            return prev
    else:
        # Score moved UP (more bullish). Stay in prev unless we rise clearly
        # above prev band's upper edge (= the next-higher band's threshold).
        upper_edge = bands[prev_idx - 1][0]  # prev_idx >= 1 here since base_idx < prev_idx
        if score < upper_edge + HYSTERESIS_BUFFER:
            return prev
    return names[base_idx]


def _confidence(
    score: float,
    agreement: float,
    recent_smoothed: list[float],
    bands: list[tuple[float, str]],
) -> float:
    """
    Honest 0–100 confidence. High only when the score is safely inside a state,
    the recent trend is consistent, and the indicators agree on direction.
    """
    edges = [t for (t, _n) in bands if t != float("-inf")]
    dist_to_boundary = min((abs(score - e) for e in edges), default=abs(score - 50.0))
    # 1.0 once we're ≥12 pts clear of the nearest state line, else proportional.
    proximity = min(dist_to_boundary / 12.0, 1.0)

    agr = max(0.0, min(1.0, agreement))

    if len(recent_smoothed) >= 2:
        mean = sum(recent_smoothed) / len(recent_smoothed)
        std = (sum((x - mean) ** 2 for x in recent_smoothed) / len(recent_smoothed)) ** 0.5
        consistency = max(0.0, 1.0 - std / 12.0)  # jittery history → low
    else:
        consistency = 0.5  # no history yet — stay humble

    conf = 100.0 * (0.50 * proximity + 0.30 * agr + 0.20 * consistency)
    return round(max(10.0, min(95.0, conf)), 0)


def _smooth(raw: float | None, prev_smoothed: float | None) -> float | None:
    if raw is None:
        return prev_smoothed
    if prev_smoothed is None:
        return round(raw, 2)
    return round(SMOOTHING_ALPHA * raw + (1.0 - SMOOTHING_ALPHA) * prev_smoothed, 2)


def stabilize(
    prior_rows: list[dict],
    raw_scores: dict,
    agreements: dict | None = None,
) -> dict:
    """
    Produce a stabilized signal row from today's raw scores + stored history.

    prior_rows : prior daily rows for this ticker, MOST-RECENT-FIRST. Each row
                 carries '<kind>_smoothed' and '<kind>_signal' for kind in
                 {tech, st, lt}. Pass [] when no history exists.
    raw_scores : {'tech': float, 'st': float|None, 'lt': float|None}
    agreements : {'tech': 0..1, 'st': 0..1, 'lt': 0..1}; defaults to 0.5 each.

    Returns a dict of the new row's stabilized fields (no ticker/as_of), plus a
    '<kind>_changed' bool for each kind that flipped vs the last stored day.
    """
    agreements = agreements or {}
    prev = prior_rows[0] if prior_rows else {}
    out: dict = {}

    specs = {
        "tech": BANDS_4,
        "st": BANDS_5,
        "lt": BANDS_5,
    }

    for kind, bands in specs.items():
        raw = raw_scores.get(kind)
        out[f"{kind}_raw"] = round(raw, 2) if raw is not None else None

        if raw is None:
            out[f"{kind}_smoothed"] = prev.get(f"{kind}_smoothed")
            out[f"{kind}_signal"] = prev.get(f"{kind}_signal")
            out[f"{kind}_changed"] = False
            if kind == "tech":
                out["tech_confidence"] = prev.get("tech_confidence") or 10.0
            continue

        prev_smoothed = prev.get(f"{kind}_smoothed")
        smoothed = _smooth(raw, prev_smoothed)
        out[f"{kind}_smoothed"] = smoothed

        prev_signal = prev.get(f"{kind}_signal")
        signal = _derive_signal(smoothed, prev_signal, bands)
        out[f"{kind}_signal"] = signal
        out[f"{kind}_changed"] = bool(prev_signal and prev_signal != signal)

        if kind == "tech":
            recent = [
                r.get("tech_smoothed")
                for r in prior_rows[:CONSISTENCY_LOOKBACK]
                if r.get("tech_smoothed") is not None
            ]
            recent = [smoothed] + recent
            out["tech_confidence"] = _confidence(
                smoothed, agreements.get("tech", 0.5), recent, bands
            )

    return out
