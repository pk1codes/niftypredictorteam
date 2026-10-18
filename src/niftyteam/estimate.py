from __future__ import annotations

import html
import re

SKIP_BITS = (
    "penny",
    " ipo",
    "ipo ",
    "preview",
    "where should",
    "can nifty",
    "factors to",
    "picks",
    "are watching",
    "exposure to",
    "stocks with",
    "retail investors",
    "ex-record",
    "dividend",
    "stock split",
    "bonus issue",
    "says it",
    "says it’s",
    "says it's",
)

HEAVY_PATTERNS = (
    (r"\breliance\b", "Reliance"),
    (r"\bhdfc bank\b", "HDFC Bank"),
    (r"\bicici\b", "ICICI Bank"),
    (r"\binfosys\b", "Infosys"),
    (r"\btcs\b", "TCS"),
    (r"\bbharti\b|\bairtel\b", "Bharti Airtel"),
    (r"\bitc\b", "ITC"),
    (r"\bl&t\b|\blarsen\b", "L&T"),
    (r"\bhindustan unilever\b|\bhul\b", "Hindustan Unilever"),
    (r"\bsbi\b|\bstate bank of india\b", "SBI"),
)


def estimate_headline(title: str) -> dict | None:
    raw = html.unescape(title).strip()
    text = " " + raw.lower() + " "
    if "?" in raw or any(bit in text for bit in SKIP_BITS):
        return None

    oil = bool(re.search(r"\b(crude|oil|brent|wti)\b", text))
    if oil and re.search(r"\b(jump|jumps|surge|surges|rise|rises|spike|spikes)\b", text):
        return _band("crude", "down", 40, 80, 0.4, raw, "crude:down")
    if oil and re.search(r"\b(fall|falls|slip|slips|drop|drops|ease|eases)\b", text):
        return _band("crude", "up", 25, 55, 0.35, raw, "crude:up")

    if re.search(r"\b(fpi|fii|foreign investors|foreign funds)\b", text) and re.search(
        r"\b(sell|selling|sold|pull out|pulls out|outflow|exodus|exit)\b", text
    ):
        return _band("flows", "down", 30, 70, 0.4, raw, "flows:down")
    if re.search(r"\b(fpi|fii|foreign investors|foreign funds)\b", text) and re.search(
        r"\b(buy|buying|bought|inflow|inflows)\b", text
    ):
        return _band("flows", "up", 20, 50, 0.35, raw, "flows:up")

    name = _heavyweight(text)
    if name and re.search(r"\b(profit|pat|earnings|nii)\b", text):
        jumped = re.search(r"\b(jump|jumps|spurt|spurts|surge|beat)\b", text)
        rose = re.search(r"\b(rise|rises|rose|up|shines)\b", text)
        fell = re.search(r"\b(slide|slides|fall|falls|drop|drops|miss)\b", text)
        if jumped or (rose and not fell):
            wide = 35 if jumped else 18
            return _band("weights", "up", 8, wide, 0.3, raw, f"weights:{name}:up")
        if fell:
            return _band("weights", "down", 15, 40, 0.3, raw, f"weights:{name}:down")

    if re.search(r"\b(rbi|repo rate|monetary policy)\b", text):
        if re.search(r"\b(hike|hikes|tightens)\b", text):
            return _band("policy", "down", 30, 70, 0.4, raw, "policy:down")
        if re.search(r"\b(cut|cuts|eases|pause|holds)\b", text):
            return _band("policy", "up", 15, 40, 0.3, raw, "policy:up")

    if re.search(r"\b(rupee|usd\/inr|dollar index)\b", text):
        if re.search(r"\b(fall|falls|slip|slips|low|weaker)\b", text):
            return _band("fx", "down", 10, 30, 0.25, raw, "fx:down")
        if re.search(r"\b(gain|gains|rise|rises|stronger)\b", text):
            return _band("fx", "up", 10, 25, 0.25, raw, "fx:up")

    if re.search(r"\b(s&p|dow|nasdaq|wall street|nikkei|hang seng|vix)\b", text):
        if re.search(r"\b(fall|falls|slide|slump|selloff|sink|fear)\b", text):
            return _band("global", "down", 20, 50, 0.3, raw, "global:down")
        if re.search(r"\b(rally|gain|gains|rise|record)\b", text):
            return _band("global", "up", 15, 40, 0.28, raw, "global:up")

    return None


def pcr_estimate(delta: float, trailing_std: float, learned_sign: float, label: str = "Put-call ratio", shock: str = "pcr") -> dict | None:
    std = trailing_std if trailing_std > 0.01 else 0.05
    if abs(delta) < max(0.04, std):
        return None
    sign = 1 if delta > 0 else -1
    if learned_sign != 0:
        sign = 1 if learned_sign > 0 else -1
        if delta < 0:
            sign *= -1
    magnitude = min(40, abs(delta) / std * 15)
    low = max(8, magnitude * 0.6)
    high = max(low + 5, magnitude * 1.4)
    word = "rose" if delta > 0 else "fell"
    sentence = f"{label} {word} {abs(delta):.2f}. Still learning."
    return {
        "beat": "pcr",
        "direction": "up" if sign > 0 else "down",
        "points_low": round(low, 1),
        "points_high": round(high, 1),
        "midpoint": round(sign * (low + high) / 2, 1),
        "confidence": 0.2,
        "headline": sentence,
        "shock_key": f"{shock}:up" if sign > 0 else f"{shock}:down",
        "body": sentence,
    }


def oi_change_estimate(net: float, trailing_std: float, learned_sign: float) -> dict | None:
    std = trailing_std if trailing_std > 1000 else 50000
    if abs(net) < max(20000, std):
        return None
    sign = 1 if net > 0 else -1
    if learned_sign != 0:
        sign = 1 if learned_sign > 0 else -1
        if net < 0:
            sign *= -1
    magnitude = min(40, abs(net) / std * 15)
    low = max(8, magnitude * 0.6)
    high = max(low + 5, magnitude * 1.4)
    side = "puts" if net > 0 else "calls"
    sentence = f"Nifty options added more {side} than the other side. Still learning."
    return {
        "beat": "pcr",
        "direction": "up" if sign > 0 else "down",
        "points_low": round(low, 1),
        "points_high": round(high, 1),
        "midpoint": round(sign * (low + high) / 2, 1),
        "confidence": 0.2,
        "headline": sentence,
        "shock_key": "pcr:oi:up" if sign > 0 else "pcr:oi:down",
        "body": sentence,
    }


def gift_gap_estimate(gap: float) -> dict | None:
    if abs(gap) < 8:
        return None
    mid = max(-150.0, min(150.0, gap))
    half = max(10.0, abs(mid) * 0.2)
    return {
        "beat": "global",
        "direction": "up" if mid > 0 else "down",
        "points_low": max(0.0, abs(mid) - half),
        "points_high": abs(mid) + half,
        "midpoint": mid,
        "confidence": 0.7,
        "headline": f"GIFT Nifty is {mid:+.0f} points versus the last close.",
        "shock_key": "gift:gap",
        "body": f"GIFT Nifty is {mid:+.0f} points versus the last close.",
        "horizon": "open",
    }


LEVEL_RULES = {
    "brent": {"scale": -8.0, "threshold": 0.4},
    "usdinr": {"scale": -40.0, "threshold": 0.08},
    "gold": {"scale": -0.12, "threshold": 8.0},
    "es": {"scale": 0.35, "threshold": 8.0},
    "indiavix": {"scale": -10.0, "threshold": 0.3},
}

LEVEL_NAMES = {
    "brent": "Brent",
    "usdinr": "USD/INR",
    "gold": "Gold",
    "es": "US futures",
    "indiavix": "India VIX",
}


def level_estimate(name: str, change: float, pairs: list[tuple[float, float]]) -> dict | None:
    rule = LEVEL_RULES[name]
    if abs(change) < rule["threshold"]:
        return None
    fallback = rule["scale"] * change
    mid = fitted_move(pairs, change, fallback)
    mid = max(-80.0, min(80.0, mid))
    if abs(mid) < 4:
        return None
    half = max(8.0, abs(mid) * 0.35)
    label = LEVEL_NAMES[name]
    word = "rose" if change > 0 else "fell"
    sentence = f"{label} {word} {abs(change):.2f} since the last print."
    return {
        "beat": "crude" if name == "brent" else "fx" if name == "usdinr" else "global",
        "direction": "up" if mid > 0 else "down",
        "points_low": max(0.0, abs(mid) - half),
        "points_high": abs(mid) + half,
        "midpoint": mid,
        "confidence": 0.45 if len(pairs) >= 30 else 0.3,
        "headline": sentence,
        "shock_key": f"level:{name}",
        "body": sentence,
        "horizon": "session",
        "driver": change,
    }


def fitted_move(pairs: list[tuple[float, float]], change: float, fallback: float) -> float:
    if len(pairs) < 30:
        return fallback
    denom = sum(item[0] * item[0] for item in pairs)
    if denom <= 0:
        return fallback
    slope = sum(item[1] * item[0] for item in pairs) / denom
    return slope * change


def _heavyweight(text: str) -> str | None:
    for pattern, name in HEAVY_PATTERNS:
        if re.search(pattern, text):
            return name
    return None


def _band(beat: str, direction: str, low: float, high: float, confidence: float, headline: str, shock: str) -> dict:
    sign = 1 if direction == "up" else -1
    return {
        "beat": beat,
        "direction": direction,
        "points_low": low,
        "points_high": high,
        "midpoint": sign * (low + high) / 2,
        "confidence": confidence,
        "headline": headline,
        "shock_key": shock,
        "body": headline,
    }
