from __future__ import annotations

import math
from datetime import datetime

import httpx

UA = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/option-chain",
}


def in_session(now: datetime, start: str, end: str) -> bool:
    if now.weekday() >= 5:
        return False
    clock = now.strftime("%H:%M")
    return start <= clock <= end


def fetch_chain(client: httpx.Client) -> dict | None:
    client.get("https://www.nseindia.com", headers=UA, timeout=8, follow_redirects=True)
    response = client.get(
        "https://www.nseindia.com/api/option-chain-indices",
        params={"symbol": "NIFTY"},
        headers=UA,
        timeout=8,
    )
    response.raise_for_status()
    return response.json()


def option_book(payload: dict, today: str) -> dict | None:
    records = payload.get("records") or {}
    upcoming = []
    for label in records.get("expiryDates") or []:
        iso = _expiry_iso(label)
        if iso and iso >= today:
            upcoming.append((iso, label))
    if not upcoming:
        return None
    week = _totals(records, upcoming[0][1])
    if week is None:
        return None
    month_prefix = today[:7]
    this_month = [(iso, label) for iso, label in upcoming if iso[:7] == month_prefix]
    if this_month:
        month_label = this_month[-1][1]
    else:
        next_prefix = upcoming[0][0][:7]
        month_label = [label for iso, label in upcoming if iso[:7] == next_prefix][-1]
    month = week if month_label == week["expiry"] else _totals(records, month_label)
    if month is None:
        month = week
    return {"week": week, "month": month, "same_expiry": week["expiry"] == month["expiry"]}


def _totals(records: dict, expiry: str) -> dict | None:
    puts = calls = put_change = call_change = 0.0
    for row in records.get("data") or []:
        if row.get("expiryDate") != expiry:
            continue
        pe = row.get("PE") or {}
        ce = row.get("CE") or {}
        puts += float(pe.get("openInterest") or 0)
        calls += float(ce.get("openInterest") or 0)
        put_change += float(pe.get("changeinOpenInterest") or 0)
        call_change += float(ce.get("changeinOpenInterest") or 0)
    if calls <= 0:
        return None
    return {
        "expiry": expiry,
        "oi_pcr": puts / calls,
        "oi_change": put_change - call_change,
    }


def trailing_std(values: list[float]) -> float:
    if len(values) < 4:
        return 0.05
    mean = sum(values) / len(values)
    var = sum((item - mean) ** 2 for item in values) / len(values)
    return math.sqrt(var) or 0.05


def fetch_fii(client: httpx.Client) -> float | None:
    return fetch_flows(client).get("fii")


def fetch_flows(client: httpx.Client) -> dict[str, float]:
    client.get("https://www.nseindia.com", headers=UA, timeout=8, follow_redirects=True)
    response = client.get("https://www.nseindia.com/api/fiidiiTradeReact", headers=UA, timeout=8)
    response.raise_for_status()
    return parse_flows(response.json())


def parse_flows(payload) -> dict[str, float]:
    rows = payload if isinstance(payload, list) else payload.get("data") or []
    found: dict[str, float] = {}
    for row in rows:
        name = str(row.get("category") or row.get("type") or "").upper()
        raw = row.get("netValue") or row.get("net") or row.get("buyValue")
        if raw is None:
            continue
        value = float(str(raw).replace(",", ""))
        if "DII" in name:
            found["dii"] = value
        elif "FII" in name or "FPI" in name:
            found["fii"] = value
    return found


def _expiry_iso(label: str) -> str | None:
    for fmt in ("%d-%b-%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(label, fmt).date().isoformat()
        except ValueError:
            continue
    return None
