from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlparse

import feedparser
import httpx

from niftyteam.config import IST

UA = "niftyteam/0.1 (local research; +https://localhost)"


def fetch_feed(client: httpx.Client, url: str) -> list[dict]:
    response = client.get(url, timeout=12, follow_redirects=True)
    response.raise_for_status()
    return feed_items(response.content)


def feed_items(raw: bytes) -> list[dict]:
    parsed = feedparser.parse(raw)
    items = []
    for entry in parsed.entries:
        link = entry.get("link") or ""
        title = entry.get("title") or ""
        if not link or not title:
            continue
        items.append(
            {
                "title": title,
                "url": link,
                "published": _published(entry),
                "summary": entry.get("summary") or "",
            }
        )
    if items:
        return items
    return _listing(raw)


def _listing(raw: bytes) -> list[dict]:
    text = raw.decode("utf-8", "replace")
    items = []
    for blob in re.findall(r'<script type="application/ld\+json">(.*?)</script>', text, re.S | re.I):
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        for row in data.get("itemListElement") or []:
            title = str(row.get("name") or "").strip()
            link = str(row.get("url") or "").strip()
            if not title or not link:
                continue
            items.append({"title": title, "url": link, "published": None, "summary": ""})
    return items


def fetch_price(client: httpx.Client) -> tuple[float | None, list[tuple[str, float]]]:
    response = client.get(
        "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI",
        params={"interval": "1d", "range": "1mo"},
        timeout=12,
    )
    response.raise_for_status()
    result = response.json()["chart"]["result"][0]
    price = result.get("meta", {}).get("regularMarketPrice")
    stamps = result.get("timestamp") or []
    quote = result.get("indicators", {}).get("quote", [{}])[0]
    closes = quote.get("close") or []
    opens = list(quote.get("open") or [])
    if len(opens) < len(closes):
        opens.extend([None] * (len(closes) - len(opens)))
    bars = []
    for stamp, close, opened in zip(stamps, closes, opens):
        if close is None:
            continue
        day = datetime.fromtimestamp(stamp, tz=timezone.utc).astimezone(IST).date().isoformat()
        bars.append((day, float(close), None if opened is None else float(opened)))
    return (float(price) if price is not None else None), bars


def fetch_level(client: httpx.Client, symbol: str) -> float | None:
    response = client.get(
        "https://query1.finance.yahoo.com/v8/finance/chart/" + quote(symbol, safe=""),
        params={"interval": "1d", "range": "5d"},
        timeout=12,
        headers={"User-Agent": "niftyteam/0.1"},
    )
    response.raise_for_status()
    meta = response.json()["chart"]["result"][0].get("meta") or {}
    price = meta.get("regularMarketPrice")
    return None if price is None else float(price)


def fetch_gift(client: httpx.Client) -> dict | None:
    response = client.get(
        "https://www.nseix.com/api/market-rate?type=derivatives",
        timeout=12,
        headers={"User-Agent": "Mozilla/5.0 niftyteam/0.1", "Accept": "application/json"},
    )
    response.raise_for_status()
    return parse_gift(response.json())


def parse_gift(payload: dict) -> dict | None:
    rows = payload.get("data") or []
    seen = set()
    futures = []
    for row in rows:
        if row.get("SYMBOL") != "NIFTY" or row.get("INSTRUMENTTYPE") != "FUTIDX":
            continue
        expiry = row.get("EXPIRYDATE")
        if not expiry or expiry in seen:
            continue
        seen.add(expiry)
        futures.append(row)
    if not futures:
        return None
    near = futures[0]
    price = float(str(near["LASTPRICE"]).replace(",", ""))
    raw_change = near.get("DAYCHANGE_1")
    if raw_change is None:
        raw_change = str(near.get("DAYCHANGE") or "0").replace(",", "")
    return {
        "price": price,
        "change": float(raw_change),
        "expiry": near["EXPIRYDATE"],
    }


def close_on_or_after(bars: list, day: str) -> float | None:
    for bar in bars:
        if bar[0] >= day:
            return float(bar[1])
    return None


def _published(entry) -> datetime | None:
    for key in ("published", "updated"):
        raw = entry.get(key)
        if not raw:
            continue
        try:
            stamp = parsedate_to_datetime(raw)
        except (TypeError, ValueError, IndexError):
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(IST)
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc).astimezone(IST)


def fresh(items: list[dict], since: datetime) -> list[dict]:
    kept = []
    for item in items:
        if item["published"] is None or item["published"] >= since:
            kept.append(item)
    kept.sort(key=lambda item: item["published"] or since, reverse=True)
    return kept[:8]


def domain_of(url: str) -> str:
    return urlparse(url).netloc.lower().split(":")[0]


def hrefs(summary: str) -> list[str]:
    import re

    return re.findall(r"https?://[^\"'\s<]+", summary or "")

