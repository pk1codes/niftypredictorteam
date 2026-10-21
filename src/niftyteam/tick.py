from __future__ import annotations

import json
from datetime import datetime, timedelta
from uuid import uuid4

import httpx

from niftyteam.ahead import ahead_view, run_ahead
from niftyteam.evolve import run_evolve
from niftyteam.signoff import presented, write_public_forecast
from niftyteam.boss import agree_to_rescue, boss_sentence, crew_sentence, missed, wake, watch_line
from niftyteam.chart import render_page, write_prices
from niftyteam.config import (
    BOARD_AGENT,
    BOSS_AGENT,
    FEED_DOWN,
    IST,
    MISSED_LINES,
    NO_ANSWER,
    QUIET,
    ROSTER,
    SEARCH_FAILED,
    SHUT,
    STATUS_LINES,
    clip,
    find_root,
    impact_text,
    load_config,
    load_dotenv,
    now_ist,
)
from niftyteam.ensemble import (
    adjust_sigma,
    apply_score,
    attributed_points,
    book_std,
    build_ensemble,
    claim_weight,
    next_sigma_floor,
)
from niftyteam.estimate import (
    LEVEL_RULES,
    apply_family_bias,
    estimate_headline,
    fit_move,
    judge_headline,
    gift_gap_estimate,
    headline_kind,
    level_estimate,
    oi_change_estimate,
    pcr_estimate,
    promoted_miss,
)
from niftyteam.horizons import (
    day_open,
    forecast_move,
    last_cash_close,
    next_open,
    session_close,
    sessions_ahead,
    week_move,
)
from niftyteam.models import Claim, Ensemble, Source
from niftyteam.pcr import fetch_chain, fetch_flows, in_session, option_book, trailing_std
from niftyteam.scout import query_for, scout_sentence, search_all, search_web
from niftyteam.search import domain_of, fetch_feed, fetch_gift, fetch_level, fetch_price, fresh, hrefs, quote_is_live, quote_stamp

AHEAD_FEEDS = {"brent": "BZ=F", "usdinr": "INR=X", "es": "ES=F"}
OPTIONAL_FEEDS = {"gold": "GC=F", "indiavix": "^INDIAVIX"}
from niftyteam.store import Store


def tick(root=None) -> int:
    root = root or find_root()
    load_dotenv(root)
    config = load_config(root)
    store = Store(root / "data" / "niftyteam.sqlite")
    try:
        store.seed_sources(config["sources"])
        stamp = now_ist()
        restarted = wake(store)
        nifty, bars = _price(store, stamp)
        if nifty is None:
            nifty, bars = _price(store, stamp)
            restarted.append("Nifty")
        gift = _gift(store)
        if gift is None:
            gift = _gift(store)
            restarted.append("GIFT")
        gift_claims = _gift_gap(store, stamp, gift, last_cash_close(bars, stamp))
        soften = bool(gift_claims) or store.meta("gift_open_day") == next_open(stamp).date().isoformat()
        news_claims, news_worked, news_lines = _news(store, config, stamp, nifty, soften)
        pcr_claims, pcr_worked, chain_state = _pcr(store, config, stamp, nifty)
        fii_claims, fii_worked, fii_failed = _fii(store, stamp, nifty)
        level_claims = _levels(store, stamp, nifty)
        scout_claims, scout_failed, scout_line = _scout(store, stamp, nifty, soften)
        feed_lines = dict(news_lines)
        missed_feeds = {key for key, (sentence, _impact) in feed_lines.items() if sentence in MISSED_LINES}
        for claim in level_claims + gift_claims:
            beat = "global" if claim.horizon == "open" else claim.beat
            news_lines[beat] = _prefer(
                news_lines.get(beat, (NO_ANSWER, 0)),
                (clip(claim.headline), claim.midpoint),
            )
        news_claims, news_worked, feed_lines, restarted = _rescue_news(
            store, config, stamp, nifty, soften, news_claims, news_worked, feed_lines, restarted, missed_feeds,
        )
        _fold_feed(news_lines, feed_lines)
        if chain_state in {"failed", "down"}:
            wake(store)
            pcr_claims, pcr_worked, chain_state = _pcr(store, config, stamp, nifty)
            restarted.append("Options")
        if fii_failed:
            wake(store)
            fii_claims, fii_worked, fii_failed = _fii(store, stamp, nifty)
            restarted.append("Flows")
        if scout_failed:
            wake(store)
            scout_claims, scout_failed, scout_line = _scout(store, stamp, nifty, soften)
            restarted.append("Scout")
        boss = _boss_line(
            store, restarted, feed_lines, pcr_claims, chain_state,
            fii_claims, fii_worked, fii_failed, scout_line, nifty is None, gift is None,
        )
        voters = agree_to_rescue(boss, _outcomes(
            store, feed_lines, pcr_claims, chain_state, fii_claims, fii_worked, fii_failed, scout_line,
        ))
        if len(voters) >= 2:
            if nifty is None:
                nifty, bars = _price(store, stamp)
            if gift is None:
                gift = _gift(store)
                if gift is not None:
                    gift_claims = _gift_gap(store, stamp, gift, last_cash_close(bars, stamp))
            still_feeds = {key for key, (sentence, _impact) in feed_lines.items() if sentence in MISSED_LINES}
            news_claims, news_worked, feed_lines, restarted = _rescue_news(
                store, config, stamp, nifty, soften, news_claims, news_worked, feed_lines, restarted, still_feeds,
            )
            _fold_feed(news_lines, feed_lines)
            if chain_state in {"failed", "down"}:
                wake(store)
                pcr_claims, pcr_worked, chain_state = _pcr(store, config, stamp, nifty)
            if fii_failed:
                wake(store)
                fii_claims, fii_worked, fii_failed = _fii(store, stamp, nifty)
            if scout_failed:
                wake(store)
                scout_claims, scout_failed, scout_line = _scout(store, stamp, nifty, soften)
            boss = crew_sentence(voters, _still_names(
                store, feed_lines, pcr_claims, chain_state, fii_claims, fii_worked, fii_failed,
                scout_line, nifty is None, gift is None,
            ))
        else:
            boss = watch_line(boss, voters)
        claims = news_claims + pcr_claims + fii_claims + level_claims + scout_claims + gift_claims
        worked = news_worked | pcr_worked | fii_worked | {"scout"}
        if level_claims:
            worked.add("levels")
        open_call, ensemble = _publish(store, config, claims, stamp, nifty, worked, last_cash_close(bars, stamp))
        if ensemble is not None and ensemble.ts == stamp.isoformat():
            pending = _merged_ignored(store)
            if pending:
                store.set_meta(f"ignored:{ensemble.id}", pending)
        _log_roster(
            store,
            stamp,
            news_lines,
            pcr_claims,
            chain_state,
            fii_claims,
            fii_worked,
            fii_failed,
            ensemble,
            open_call,
            boss,
        )
        _score(store, config, stamp, bars)
        run_ahead(store, stamp, bars, _ahead_bundle(store), _ahead_stories)
        _report_limits(
            store,
            stamp,
            nifty=nifty,
            news_answered=bool(news_worked),
            news_claims=len(news_claims),
            scout_failed=scout_failed,
            chain_state=chain_state,
            fii_failed=fii_failed and store.meta("fii_net") is None,
            gift_missing=gift is None,
            scored=any(row.residual is not None for row in store.ensembles()),
        )
        try:
            run_evolve(store, stamp)
        except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError):
            pass
        forecast = presented(store, stamp)
        _write_chart(store, root, ensemble, nifty, gift, open_call, forecast)
        _print_board(store)
        return 0
    finally:
        store.close()


def _price(store: Store, stamp) -> tuple[float | None, list]:
    try:
        with httpx.Client(headers={"User-Agent": "niftyteam/0.1"}) as client:
            price, bars, traded = fetch_price(client)
        if price is not None:
            store.set_meta("nifty", f"{price:.2f}")
        if traded is not None:
            store.set_meta("nifty_asof", traded.isoformat())
        return price, bars
    except (httpx.HTTPError, KeyError, ValueError, IndexError):
        cached = store.meta("nifty")
        return (float(cached) if cached else None), []


def _fold_feed(display: dict, feed_lines: dict) -> None:
    for key, line in feed_lines.items():
        if line[0] in MISSED_LINES:
            display[key] = line
        else:
            display[key] = _prefer(display.get(key, (NO_ANSWER, 0)), line)


def _rescue_news(store, config, stamp, nifty, soften, claims, worked, lines, restarted, stuck: set[str] | None = None):
    if stuck is None:
        stuck = {key for key, (sentence, _impact) in lines.items() if sentence in MISSED_LINES}
    if not stuck:
        return claims, worked, lines, restarted
    wake(store)
    extra_claims, extra_worked, extra_lines = _news(store, config, stamp, nifty, soften, only=stuck)
    claims = claims + extra_claims
    worked = worked | extra_worked
    for key, line in extra_lines.items():
        lines[key] = _prefer(lines.get(key, (NO_ANSWER, 0)), line)
    names = {key: name for key, name in ROSTER}
    for key in stuck:
        restarted.append(names[key])
    return claims, worked, lines, restarted


def _boss_line(store, restarted, feed_lines, pcr_claims, chain_state, fii_claims, fii_worked, fii_failed, scout_line, price_missing, gift_missing) -> str:
    still = _still_names(
        store, feed_lines, pcr_claims, chain_state, fii_claims, fii_worked, fii_failed,
        scout_line, price_missing, gift_missing,
    )
    return boss_sentence(restarted, still)


def _outcomes(store, feed_lines, pcr_claims, chain_state, fii_claims, fii_worked, fii_failed, scout_line) -> dict[str, str]:
    lines = _roster_lines(store, feed_lines, pcr_claims, chain_state, fii_claims, fii_worked, fii_failed)
    names = {key: name for key, name in ROSTER}
    outcomes = {names[key]: lines.get(key, (NO_ANSWER, 0))[0] for key, _name in ROSTER if key != "scout"}
    outcomes["Scout"] = scout_line
    return outcomes


def _still_names(store, feed_lines, pcr_claims, chain_state, fii_claims, fii_worked, fii_failed, scout_line, price_missing, gift_missing) -> list[str]:
    lines = _roster_lines(store, feed_lines, pcr_claims, chain_state, fii_claims, fii_worked, fii_failed)
    names = {key: name for key, name in ROSTER}
    still = [names[key] for key, (sentence, _impact) in lines.items() if missed(sentence)]
    if missed(scout_line):
        still.append("Scout")
    if price_missing:
        still.append("Nifty")
    if gift_missing:
        still.append("GIFT")
    return still


def _roster_lines(store, feed_lines, pcr_claims, chain_state, fii_claims, fii_worked, fii_failed) -> dict:
    lines = dict(feed_lines)
    fii = _fii_line(store, fii_claims, fii_worked, fii_failed)
    if fii[0] in MISSED_LINES:
        lines["flows"] = fii
    else:
        lines["flows"] = _prefer(lines.get("flows", (NO_ANSWER, 0)), fii)
    lines["pcr"] = _pcr_line(pcr_claims, chain_state)
    return lines


def important_view(store: Store) -> list[dict]:
    raw = store.meta("important_feeds") or ""
    if not raw:
        return []
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [row for row in rows if isinstance(row, dict) and row.get("label")]


def _feed_row(source_id: str, label: str, state: str, detail: str, lines: list[str] | None = None) -> dict:
    row = {"id": source_id, "label": label, "state": state, "detail": detail}
    if lines:
        row["lines"] = lines
    return row


def _reading(title: str, note: str) -> str:
    return f"{clip(title, 72)} — {note}"


def _save_kept(store: Store, titles: list[str], reset: bool) -> None:
    prior: list[str] = []
    if not reset:
        prior = _saved_titles(store, "pending_watch")
    merged = prior + [title for title in titles if title not in prior]
    store.set_meta("pending_watch", json.dumps(merged))


def _merged_ignored(store: Store) -> str:
    titles = _saved_titles(store, "pending_ignored")
    for title in _saved_titles(store, "pending_watch"):
        if title not in titles:
            titles.append(title)
    return json.dumps(titles) if titles else ""


def _saved_titles(store: Store, key: str) -> list[str]:
    raw = store.meta(key) or ""
    if not raw:
        return []
    try:
        found = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [title for title in found if isinstance(title, str)]


def _feed_detail(stories: int, headline: str) -> str:
    if headline:
        return f"Checked · {clip(headline, 64)}"
    if stories == 1:
        return "Checked · 1 story"
    if stories:
        return f"Checked · {stories} stories"
    return "Checked · nothing new"


def items_for_feed(items: list[dict], since: datetime, important: bool) -> list[dict]:
    """Important feeds keep every story. Others keep only what arrived since the last check."""
    if important:
        return sorted(items, key=lambda item: item.get("published") or since, reverse=True)
    return fresh(items, since)


def _save_feed_notes(store: Store, config: dict, notes: dict, reset: bool) -> None:
    prior: dict[str, dict] = {}
    if not reset:
        for row in important_view(store):
            if row.get("id"):
                prior[str(row["id"])] = row
    prior.update(notes)
    ordered = []
    for row in config.get("sources") or []:
        if not row.get("important"):
            continue
        found = prior.get(row["id"])
        if found is None:
            found = _feed_row(row["id"], row.get("label") or row["id"], "wait", "Not checked")
        ordered.append(found)
    store.set_meta("important_feeds", json.dumps(ordered))


def _news(store: Store, config: dict, stamp, nifty: float | None, soften: bool = False, only: set[str] | None = None) -> tuple[list[Claim], set[str], dict[str, tuple[str, float]]]:
    hour = stamp.hour
    quiet = hour in set(config.get("quiet_hours") or [])
    last = store.meta("last_tick")
    if last:
        since = datetime.fromisoformat(last) - timedelta(minutes=10)
    else:
        since = stamp - timedelta(hours=int(config.get("first_window_hours") or 36))
    claims: list[Claim] = []
    worked: set[str] = set()
    best: dict[str, Claim] = {}
    answered: set[str] = set()
    down: set[str] = set()
    sources = [row for row in store.sources({"rss"}) if row.status in {"active", "probation", "down"}]
    if only is not None:
        sources = [row for row in sources if row.beat in only]
    live = [row for row in sources if row.status != "down"]
    watch = {
        row["id"]: row.get("label") or row["id"]
        for row in config.get("sources") or []
        if row.get("important")
    }
    notes: dict[str, dict] = {}
    kept_titles: list[str] = []
    for source in sources:
        if source.status == "down":
            down.add(source.beat)
            if source.id in watch:
                notes[source.id] = _feed_row(source.id, watch[source.id], "down", "Down")
    with httpx.Client(headers={"User-Agent": "Mozilla/5.0 niftyteam/0.1"}, follow_redirects=True) as client:
        for source in live:
            try:
                fetched = fetch_feed(client, source.url)
                items = items_for_feed(fetched, since, source.id in watch)
                source.fail_streak = 0
                if source.status == "down":
                    source.status = "active"
                    source.weight = max(source.weight, 0.4)
                store.save_source(source)
                worked.add(source.beat)
                answered.add(source.beat)
            except (httpx.HTTPError, ValueError):
                _fail(store, source, stamp)
                if source.status == "down":
                    down.add(source.beat)
                if source.id in watch:
                    notes[source.id] = _feed_row(source.id, watch[source.id], "miss", "No answer")
                continue
            used = ""
            used_abs = -1.0
            readings: list[str] = []
            important = source.id in watch
            for item in items:
                _note_links(store, config, item["summary"], source.beat)
                if important:
                    judged = judge_headline(item["title"])
                    if judged["verdict"] == "discard":
                        readings.append(_reading(item["title"], judged["reason"]))
                        continue
                    guess = judged["guess"]
                    if guess is None:
                        readings.append(_reading(item["title"], "Kept. No clear up or down, so no points."))
                        kept_titles.append(item["title"])
                        continue
                    if judged["verdict"] == "keep":
                        kept_note = f"Kept, {impact_text(guess['midpoint'])}. It may still move Nifty."
                    else:
                        kept_note = ""
                else:
                    if quiet and item["published"] and item["published"] < stamp - timedelta(hours=2):
                        continue
                    guess = estimate_headline(item["title"])
                    if guess is None:
                        continue
                    if quiet and abs(guess["midpoint"]) < 40:
                        continue
                if soften:
                    guess["confidence"] *= 0.5
                claim = _make_claim(source, guess, item["url"], stamp, nifty, store)
                if store.add_claim(claim):
                    claims.append(claim)
                    prior = best.get(guess["beat"])
                    if prior is None or abs(claim.midpoint) > abs(prior.midpoint):
                        best[guess["beat"]] = claim
                    if important and abs(claim.midpoint) > used_abs:
                        used = claim.headline
                        used_abs = abs(claim.midpoint)
                if important:
                    note = kept_note or f"In the prediction {impact_text(guess['midpoint'])}."
                    readings.append(_reading(item["title"], note))
            if source.id in watch:
                detail = _feed_detail(len(items), "") if readings else _feed_detail(len(items), used)
                notes[source.id] = _feed_row(source.id, watch[source.id], "read", detail, readings)
    _save_kept(store, kept_titles, reset=only is None)
    _save_feed_notes(store, config, notes, reset=only is None)
    lines: dict[str, tuple[str, float]] = {}
    for key, _name in ROSTER:
        if key in {"pcr", "scout"}:
            continue
        if only is not None and key not in only:
            continue
        if key in best:
            lines[key] = (clip(best[key].headline), best[key].midpoint)
        elif key in answered:
            lines[key] = (QUIET, 0)
        elif key in down:
            lines[key] = (FEED_DOWN, 0)
        else:
            lines[key] = (NO_ANSWER, 0)
    return claims, worked, lines


def _pcr(store: Store, config: dict, stamp, nifty: float | None) -> tuple[list[Claim], set[str], str]:
    session = config.get("session") or {}
    if not in_session(stamp, session.get("start", "09:15"), session.get("end", "15:30")):
        return [], set(), "shut"
    source = store.source("nse-pcr")
    if source is None or source.status in {"retired", "down"}:
        return [], set(), "down"
    try:
        with httpx.Client(timeout=8) as client:
            payload = fetch_chain(client)
        book = option_book(payload or {}, stamp.date().isoformat())
        if book is None:
            raise ValueError("empty chain")
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        _fail(store, source, stamp)
        return [], set(), "failed"
    source.fail_streak = 0
    store.save_source(source)
    worked = {"pcr"}
    learned = _learned_pcr_sign(source)
    claims: list[Claim] = []
    claims.extend(_pcr_leg(store, source, stamp, nifty, "week", book["week"], learned, "Weekly put-call ratio", "pcr:week"))
    if not book["same_expiry"]:
        claims.extend(_pcr_leg(store, source, stamp, nifty, "month", book["month"], learned, "Monthly put-call ratio", "pcr:month"))
    else:
        store.add_pcr(
            stamp.isoformat(),
            book["month"]["expiry"],
            book["month"]["oi_pcr"],
            0,
            stamp.date().isoformat(),
            "month",
            book["month"]["oi_change"],
        )
    claims.extend(_oi_leg(store, source, stamp, nifty, book["week"], learned))
    return claims, worked, "ok"


def _pcr_leg(store, source, stamp, nifty, bucket, leg, learned, label, shock) -> list[Claim]:
    previous = store.recent_pcr(30, bucket)
    store.add_pcr(stamp.isoformat(), leg["expiry"], leg["oi_pcr"], 0, stamp.date().isoformat(), bucket, leg["oi_change"])
    if not previous:
        return []
    delta = leg["oi_pcr"] - float(previous[0]["oi_pcr"])
    history = [float(row["oi_pcr"]) for row in previous]
    diffs = [history[i] - history[i + 1] for i in range(len(history) - 1)]
    guess = pcr_estimate(delta, trailing_std(diffs), learned, label, shock)
    return _keep_pcr_claim(store, source, stamp, nifty, guess, f"pcr:{bucket}:{stamp.isoformat()}")


def _oi_leg(store, source, stamp, nifty, leg, learned) -> list[Claim]:
    previous = [row for row in store.recent_pcr(30, "week") if row["ts"] != stamp.isoformat()]
    history = [float(row["oi_change"] or 0) for row in previous]
    spread = trailing_std(history) if len(history) >= 4 else 0
    guess = oi_change_estimate(leg["oi_change"], spread, learned)
    return _keep_pcr_claim(store, source, stamp, nifty, guess, f"pcr:oi:{stamp.isoformat()}")


def _keep_pcr_claim(store, source, stamp, nifty, guess, url) -> list[Claim]:
    if guess is None:
        return []
    claim = _make_claim(source, guess, url, stamp, nifty, store)
    if not store.add_claim(claim):
        return []
    return [claim]


def _fii(store: Store, stamp, nifty: float | None) -> tuple[list[Claim], set[str], bool]:
    source = store.source("fii-dii")
    if source is None or source.status in {"retired", "down"}:
        return [], set(), source is not None and source.status == "down"
    flows = _read_flows(store)
    net = flows.get("fii")
    failed = net is None and store.meta("fii_net") is None
    day = stamp.date().isoformat()
    if store.meta("fii_day") == day or net is None:
        return [], {"flows"} if net is not None else set(), failed
    store.set_meta("fii_day", day)
    source.fail_streak = 0
    store.save_source(source)
    worked = {"flows"}
    claims = []
    claims.extend(_flow_claim(store, source, stamp, nifty, net, day, "FII", "fii"))
    dii = flows.get("dii")
    if dii is not None:
        claims.extend(_flow_claim(store, source, stamp, nifty, dii, day, "DII", "dii"))
    return claims, worked, False


def _flow_claim(store, source, stamp, nifty, net: float, day: str, label: str, key: str) -> list[Claim]:
    if abs(net) < 500:
        return []
    direction = "down" if net < 0 else "up"
    if key == "dii":
        direction = "up" if net > 0 else "down"
    magnitude = min(70, max(20, abs(net) / 1000 * 8))
    signed = (1 if direction == "up" else -1) * (magnitude * 0.8)
    guess = {
        "beat": "flows",
        "direction": direction,
        "points_low": magnitude * 0.6,
        "points_high": magnitude,
        "midpoint": signed,
        "confidence": 0.35,
        "headline": f"{label} net {net:,.0f} crore today.",
        "shock_key": f"{key}:{direction}",
        "body": f"{label} net {net:,.0f} crore today.",
        "horizon": "session",
        "driver": net,
    }
    claim = _make_claim(source, guess, f"{key}:{day}", stamp, nifty, store)
    if not store.add_claim(claim):
        return []
    return [claim]


def _read_flows(store: Store) -> dict[str, float]:
    source = store.source("fii-dii")
    try:
        with httpx.Client(timeout=8) as client:
            flows = fetch_flows(client)
        if "fii" not in flows:
            raise ValueError("no fii row")
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        cached = store.meta("fii_net")
        found = {}
        if cached:
            found["fii"] = float(cached)
        dii = store.meta("dii_net")
        if dii:
            found["dii"] = float(dii)
        if not found and source is not None:
            _fail(store, source, datetime.now(IST))
        return found
    store.set_meta("fii_net", f"{flows['fii']:.2f}")
    if "dii" in flows:
        store.set_meta("dii_net", f"{flows['dii']:.2f}")
    if source is not None:
        source.fail_streak = 0
        store.save_source(source)
    return flows


def _gift(store: Store) -> dict | None:
    try:
        with httpx.Client(timeout=12) as client:
            quote = fetch_gift(client)
        if quote is None:
            raise ValueError("no gift row")
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        price = store.meta("gift_nifty")
        if not price:
            return None
        return {"price": float(price), "change": float(store.meta("gift_change") or 0), "live": False}
    quote["live"] = quote_is_live(quote_stamp(quote.get("asof")), now_ist())
    store.set_meta("gift_nifty", f"{quote['price']:.2f}")
    store.set_meta("gift_change", f"{quote['change']:.2f}")
    store.set_meta("gift_asof", str(quote.get("asof") or ""))
    return quote


def _gift_gap(store: Store, stamp, quote: dict | None, last_close: float | None) -> list[Claim]:
    _ensure_source(store, "gift", "global", "https://www.nseix.com/api/market-rate?type=derivatives")
    source = store.source("gift")
    if source is None or quote is None or last_close is None:
        return []
    if source.n_scored == 0 and source.weight <= 0.4:
        source.weight = 1.2
        store.save_source(source)
    guess = gift_gap_estimate(quote["price"] - last_close)
    if guess is None:
        return []
    when = next_open(stamp)
    store.set_meta("gift_open_day", when.date().isoformat())
    url = f"gift:{when.date().isoformat()}"
    claim = _make_claim(source, guess, url, stamp, last_close, store)
    if not store.add_claim(claim):
        return []
    return [claim]


LEVEL_FEEDS = {
    "brent": "BZ=F",
    "usdinr": "INR=X",
    "gold": "GC=F",
    "es": "ES=F",
    "indiavix": "^INDIAVIX",
}


def _levels(store: Store, stamp, nifty: float | None) -> list[Claim]:
    day = stamp.date().isoformat()
    claims: list[Claim] = []
    prints: dict[str, float | None] = {}
    for _attempt in range(2):
        try:
            with httpx.Client(timeout=12) as client:
                prints = {name: fetch_level(client, symbol) for name, symbol in LEVEL_FEEDS.items()}
            break
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            prints = {}
    for name in LEVEL_RULES:
        value = prints.get(name)
        if value is None:
            continue
        previous = store.previous_level(name, day)
        store.save_level(day, name, value)
        if previous is None:
            continue
        _ensure_source(store, name, "global", f"https://query1.finance.yahoo.com/v8/finance/chart/{LEVEL_FEEDS[name]}")
        source = store.source(name)
        if source is None:
            continue
        guess = level_estimate(name, value - previous, store.level_pairs(name))
        if guess is None:
            continue
        claim = _make_claim(source, guess, f"level:{name}:{day}", stamp, nifty, store)
        if store.add_claim(claim):
            claims.append(claim)
    return claims


def _ensure_source(store: Store, source_id: str, beat: str, url: str) -> None:
    store.seed_sources([{"id": source_id, "beat": beat, "kind": "level", "url": url}])


def _scout(store: Store, stamp, nifty: float | None, soften: bool = False) -> tuple[list[Claim], bool, str]:
    store.seed_sources([
        {"id": "scout", "beat": "scout", "kind": "scout", "url": "https://html.duckduckgo.com/html/"},
    ])
    stories = 0
    new_sources = 0
    claims: list[Claim] = []
    ignored: list[str] = []
    failed = False
    try:
        with httpx.Client(follow_redirects=True) as client:
            results = search_web(client, query_for(stamp.hour))
    except (httpx.HTTPError, ValueError):
        results = []
        failed = True
    known = store.known_domains()
    for item in results:
        guess = estimate_headline(item["title"])
        if guess is None:
            title = item.get("title") or ""
            guess = promoted_miss(title, store.miss_history()) if title else None
            if guess is None:
                if title:
                    ignored.append(title)
                continue
        guess = dict(guess)
        guess["confidence"] = min(0.2, guess["confidence"] * 0.5)
        if soften:
            guess["confidence"] *= 0.5
        domain = item["domain"]
        source = _source_for_domain(store, domain)
        if source is None and domain not in known:
            if store.add_probation_source(domain, item["url"], guess["beat"], kind="web"):
                new_sources += 1
                known.add(domain)
            source = _source_for_domain(store, domain)
        if source is None:
            source = store.source("scout")
        if source is None:
            continue
        claim = _make_claim(source, guess, item["url"], stamp, nifty, store)
        if store.add_claim(claim):
            stories += 1
            claims.append(claim)
    if failed:
        line = SEARCH_FAILED
    elif stories or new_sources:
        line = scout_sentence(stories, new_sources)
    else:
        line = QUIET
    store.set_meta("pending_ignored", json.dumps(ignored[:8]))
    store.add_event(stamp.isoformat(), line, 0, agent="scout")
    return claims, failed, line


def _source_for_domain(store: Store, domain: str) -> Source | None:
    for row in store.sources():
        if row.domain in {domain, f"www.{domain}"} and row.status in {"active", "probation"}:
            return row
    return None


def accuracy_notes(
    *,
    nifty: float | None,
    news_answered: bool,
    news_claims: int,
    scout_failed: bool,
    chain_state: str,
    fii_failed: bool,
    gift_missing: bool = False,
    down_ids: list[str],
    scored: bool,
) -> list[str]:
    notes = []
    if nifty is None:
        notes.append("Boss: Nifty price is missing. This hour’s predictions cannot be checked.")
    if gift_missing:
        notes.append("Boss: GIFT Nifty value is missing.")
    if not news_answered:
        notes.append("News agents: no feed answered. Headlines are missing from the mean.")
    elif news_claims == 0:
        notes.append("News agents: no story was strong enough to score.")
    if scout_failed:
        notes.append("Scout: the web search did not answer. New sources were not checked.")
    if chain_state == "shut":
        notes.append("Boss: the market is shut. Weekly and monthly put-call changes, and the Nifty option change, were not read.")
    elif chain_state == "failed":
        notes.append("Options agent: the chain did not answer. Put-call and option changes are missing.")
    elif chain_state == "down":
        notes.append("Options agent: the chain feed is off after repeated failures.")
    if fii_failed:
        notes.append("Flows agent: FII flow did not answer.")
    if down_ids:
        shown = ", ".join(down_ids[:6])
        notes.append(f"Boss: {len(down_ids)} feeds are down and out of the mean. {shown}.")
    if not scored:
        notes.append("Boss: no prediction has been checked yet, so trust weights are still the starting values.")
    return notes


def _report_limits(store: Store, stamp, **flags) -> None:
    down_ids = [row.id for row in store.sources() if row.status == "down"]
    notes = accuracy_notes(down_ids=down_ids, **flags)
    store.set_meta("issues", json.dumps(notes))


def _publish(store, config, claims: list[Claim], stamp, nifty: float | None, worked: set[str], last_close: float | None = None):
    store.set_meta("last_tick", stamp.isoformat())
    store.set_meta("agents", str(max(1, len(worked))))
    opened = _one_call(store, config, [row for row in claims if row.horizon == "open"], stamp, last_close, "open")
    session = _one_call(
        store, config, [row for row in claims if row.horizon not in {"open", "week"}], stamp, nifty, "session",
    )
    return opened or store.latest_ensemble("open"), session or store.latest_ensemble("session")


def _one_call(store, config, claims: list[Claim], stamp, anchor: float | None, horizon: str) -> Ensemble | None:
    if not claims:
        return None
    sources = {row.id: row for row in store.sources()}
    floor = float(store.meta("sigma_floor", str(config.get("sigma_floor") or 30)))
    built = build_ensemble(claims, sources, floor)
    if built is None:
        return None
    seen: set[str] = set()
    records = []
    for claim in claims:
        if claim.shock_key in seen:
            continue
        seen.add(claim.shock_key)
        inside, outside = store.family_coverage(claim.shock_key)
        if inside or outside:
            records.append((inside, outside))
    built["sigma"] = adjust_sigma(built["sigma"], floor, records)
    item = Ensemble(
        id=uuid4().hex[:12],
        ts=stamp.isoformat(),
        mu=built["mu"],
        sigma=built["sigma"],
        n_shocks=built["n_shocks"],
        nifty_level=anchor,
        horizon=horizon,
    )
    store.add_ensemble(item)
    store.attach_ensemble(built["ids"], item.id)
    return item


def _score(store: Store, config: dict, stamp, bars: list[tuple[str, float]]) -> None:
    due = store.due_claims(stamp.isoformat())
    if not due or not bars:
        return
    residuals = [row.residual for row in store.ensembles() if row.residual is not None]
    book = book_std(residuals)
    by_ensemble: dict[str, list[Claim]] = {}
    for claim in due:
        if not claim.ensemble_id and claim.horizon != "week":
            continue
        if claim.horizon == "open" and claim.nifty_level is None:
            continue
        score_day = claim.score_after[:10]
        if claim.horizon == "open":
            opened = day_open(bars, score_day)
            if opened is None or claim.nifty_level is None:
                continue
            actual = opened - claim.nifty_level
        elif claim.horizon == "week":
            actual = week_move(bars, score_day, claim.nifty_level)
            if actual is None:
                continue
        else:
            actual = forecast_move(bars, score_day, claim.nifty_level)
            if actual is None:
                continue
        claim.actual_move = actual
        claim.residual = actual - claim.midpoint
        claim.status = "scored"
        store.save_claim(claim)
        source = store.source(claim.source_id)
        if claim.horizon != "week":
            store.add_family_residual(claim.shock_key, claim.residual)
            if claim.driver is not None and not claim.shock_key.startswith("level:"):
                store.add_family_pair(claim.shock_key, claim.driver, actual, clean=True)
            if source is not None:
                apply_score(source, claim.residual, book)
                store.save_source(source)
            if claim.driver is not None and source is not None and source.kind == "level":
                store.add_level_pair(claim.source_id, claim.driver, actual)
        word = "fell" if actual < 0 else "rose" if actual > 0 else "was flat"
        inside = ""
        ensemble = _ensemble_by_id(store, claim.ensemble_id) if claim.ensemble_id else None
        if ensemble is not None and abs(actual - ensemble.mu) <= ensemble.sigma:
            inside = " Inside the expected range."
        miss = abs(claim.residual)
        label = {"open": "open", "week": "week"}.get(claim.horizon, "close")
        store.add_event(
            stamp.isoformat(),
            f"Checked the {label} prediction. Nifty {word} {abs(actual):.0f}. Off by {miss:.0f}.{inside}",
            actual,
            agent="score",
        )
        if claim.ensemble_id:
            by_ensemble.setdefault(claim.ensemble_id, []).append(claim)
    for ensemble_id, group in by_ensemble.items():
        ensemble = _ensemble_by_id(store, ensemble_id)
        if ensemble is None:
            continue
        if group[0].horizon == "open" and ensemble.nifty_level is None:
            continue
        score_day = group[0].score_after[:10]
        if group[0].horizon == "open":
            opened = day_open(bars, score_day)
            if opened is None or ensemble.nifty_level is None:
                continue
            ensemble.actual = opened - ensemble.nifty_level
        else:
            move = forecast_move(bars, score_day, ensemble.nifty_level)
            if move is None:
                continue
            ensemble.actual = move
        ensemble.residual = ensemble.actual - ensemble.mu
        store.save_ensemble(ensemble)
        _attribute(store, ensemble, group)
        if ensemble.horizon != "week":
            sign = -1 if ensemble.residual < 0 else 1 if ensemble.residual > 0 else 0
            titles = miss_titles(ensemble.residual, ensemble.sigma, _ignored_titles(store, ensemble.id))
            if titles:
                store.add_misses(
                    stamp.isoformat(),
                    [(title, headline_kind(title), sign) for title in titles],
                )
                store.add_event(stamp.isoformat(), f"Kept {len(titles)} missed stories.", ensemble.residual, agent="score")
    _retune_floor(store, config)


def _log_roster(store, stamp, news_lines, pcr_claims, chain_state, fii_claims, fii_worked, fii_failed, ensemble, open_call=None, boss="Watching. Every agent is working.") -> None:
    lines = dict(news_lines)
    lines["flows"] = _prefer(lines.get("flows", (NO_ANSWER, 0)), _fii_line(store, fii_claims, fii_worked, fii_failed))
    lines["pcr"] = _pcr_line(pcr_claims, chain_state)
    if ensemble is not None and ensemble.ts == stamp.isoformat():
        board = (f"Range {ensemble.sigma:.0f}", ensemble.mu)
    elif open_call is not None and open_call.ts == stamp.isoformat():
        board = (f"Open {impact_text(open_call.mu)}", open_call.mu)
    else:
        board = (QUIET, 0.0)
    if open_call is not None and ensemble is not None and open_call.ts == stamp.isoformat() and ensemble.ts == stamp.isoformat():
        board = (f"Open {impact_text(open_call.mu)}. Range {ensemble.sigma:.0f}.", ensemble.mu)
    have = {row.agent for row in store.events(20) if row.ts == stamp.isoformat() and row.agent}
    for key, _name in ROSTER:
        if key in have:
            continue
        sentence, impact = lines.get(key, (NO_ANSWER, 0))
        store.add_event(stamp.isoformat(), sentence, impact, agent=key)
    if BOARD_AGENT not in have:
        store.add_event(stamp.isoformat(), board[0], board[1], agent=BOARD_AGENT)
    if BOSS_AGENT not in have:
        store.add_event(stamp.isoformat(), boss, 0, agent=BOSS_AGENT)


def _prefer(left: tuple[str, float], right: tuple[str, float]) -> tuple[str, float]:
    def call(item: tuple[str, float]) -> bool:
        return item[0] not in STATUS_LINES

    if call(left) and call(right):
        return left if abs(left[1]) >= abs(right[1]) else right
    if call(left):
        return left
    if call(right):
        return right
    if left[0] in {QUIET, SHUT}:
        return left
    if right[0] in {QUIET, SHUT}:
        return right
    if left[0] == FEED_DOWN or right[0] == FEED_DOWN:
        return (FEED_DOWN, 0)
    return left


def _fii_line(store, claims, worked, failed) -> tuple[str, float]:
    if claims:
        best = max(claims, key=lambda claim: abs(claim.midpoint))
        return clip(best.headline), best.midpoint
    if worked:
        return QUIET, 0
    source = store.source("fii-dii")
    if failed and source is not None and source.status == "down":
        return FEED_DOWN, 0
    if failed:
        return NO_ANSWER, 0
    return QUIET, 0


def _pcr_line(claims, state: str) -> tuple[str, float]:
    if claims:
        best = max(claims, key=lambda claim: abs(claim.midpoint))
        return clip(best.body or best.headline), best.midpoint
    if state == "shut":
        return SHUT, 0
    if state == "down":
        return FEED_DOWN, 0
    if state == "failed":
        return NO_ANSWER, 0
    return QUIET, 0


def _retune_floor(store: Store, config: dict) -> None:
    rows = [row for row in store.ensembles() if row.actual is not None and row.sigma]
    flags = [abs(row.actual - row.mu) <= row.sigma for row in rows[-30:]]
    floor = float(store.meta("sigma_floor", str(config.get("sigma_floor") or 30)))
    store.set_meta("sigma_floor", str(next_sigma_floor(floor, flags)))


def _write_chart(store: Store, root, ensemble, nifty: float | None, gift: dict | None = None, open_call: Ensemble | None = None, forecast: dict | None = None) -> None:
    latest = ensemble or store.latest_ensemble("session")
    if open_call is None:
        open_call = store.latest_ensemble("open")
    rows = store.ensembles()
    residuals = [(row.residual, row.sigma) for row in rows if row.residual is not None]
    scored = len(residuals)
    cached = store.meta("nifty")
    level = nifty if nifty is not None else (float(cached) if cached else None)
    spot_live = quote_is_live(quote_stamp(store.meta("nifty_asof")), now_ist())
    raw_fii = store.meta("fii_net")
    raw_agents = store.meta("agents")
    html = render_page(
        latest,
        residuals,
        store.events(80),
        level,
        scored,
        store.meta("last_tick"),
        gift,
        float(raw_fii) if raw_fii else None,
        _saved_notes(store),
        int(raw_agents) if raw_agents else None,
        rows,
        open_call,
        store.scored_claims(),
        ahead_view(store),
        important_view(store),
        store.families(),
        forecast,
        spot_live=spot_live,
    )
    path = root / "data" / "chart.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html)
    write_prices(
        path.parent / "prices.json",
        None if level is None else {"price": level, "live": spot_live},
        gift,
    )
    write_public_forecast(path.parent / "forecast.json", forecast)


def _saved_notes(store: Store) -> list[str]:
    raw = store.meta("issues")
    if not raw:
        return []
    try:
        notes = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [note for note in notes if isinstance(note, str)]


def _ahead_bundle(store: Store):
    def fetch() -> dict[str, float] | None:
        prices = _ahead_prices()
        if prices is None:
            return None
        prices.update(_optional_prices())
        gift = store.meta("gift_nifty")
        if gift:
            prices["gift"] = float(gift)
        return prices

    return fetch


def _ahead_stories() -> list[str]:
    try:
        with httpx.Client(follow_redirects=True, headers={"User-Agent": "niftyteam/0.1"}) as client:
            return search_all(client)
    except (httpx.HTTPError, ValueError):
        return []


def _optional_prices() -> dict[str, float]:
    found = {}
    try:
        with httpx.Client(timeout=12, headers={"User-Agent": "niftyteam/0.1"}) as client:
            for name, symbol in OPTIONAL_FEEDS.items():
                try:
                    value = fetch_level(client, symbol)
                except (httpx.HTTPError, KeyError, ValueError, TypeError, IndexError):
                    continue
                if value is not None:
                    found[name] = float(value)
    except (httpx.HTTPError, KeyError, ValueError, TypeError, IndexError):
        return found
    return found


def _ahead_prices() -> dict[str, float] | None:
    found = {}
    try:
        with httpx.Client(timeout=12, headers={"User-Agent": "niftyteam/0.1"}) as client:
            for name, symbol in AHEAD_FEEDS.items():
                value = fetch_level(client, symbol)
                if value is None:
                    return None
                found[name] = float(value)
    except (httpx.HTTPError, KeyError, ValueError, TypeError, IndexError):
        return None
    return found


def _print_board(store: Store) -> None:
    opened = store.latest_ensemble("open")
    latest = store.latest_ensemble("session")
    view = ahead_view(store)
    if view is not None:
        print(f"Next close {view['move']:+.0f}  due {view['due']}")
        if view.get("note"):
            print(view["note"])
    if opened:
        print(f"Open {opened.mu:+.0f}  spread {opened.sigma:.0f}")
    if latest:
        print(f"Session {latest.mu:+.0f}  spread {latest.sigma:.0f}  shocks {latest.n_shocks}")
    elif opened is None:
        print("No forecast yet.")
    for event in store.events(12):
        print(f"{event.ts[11:16]}  {event.sentence}  {event.impact:+.0f}")


def _attribute(store: Store, ensemble: Ensemble, group: list[Claim]) -> None:
    if ensemble.actual is None:
        return
    weighted = []
    for claim in group:
        source = store.source(claim.source_id)
        if source is None:
            continue
        weight = claim_weight(claim, source)
        if weight <= 0:
            continue
        weighted.append((claim, weight))
    if not weighted:
        return
    points = attributed_points([(claim.midpoint, weight) for claim, weight in weighted], ensemble.mu, ensemble.actual)
    claim_errors = [ensemble.actual - claim.midpoint for claim, _weight in weighted]
    disagree = min(claim_errors) < 0 < max(claim_errors)
    inside = abs(ensemble.actual - ensemble.mu) <= ensemble.sigma and not disagree
    for (claim, _weight), point in zip(weighted, points):
        store.add_family_points(claim.shock_key, point)
        store.add_family_coverage(claim.shock_key, inside)


def miss_titles(residual: float, sigma: float, titles: list[str]) -> list[str]:
    if sigma <= 0 or abs(residual) <= 1.5 * sigma:
        return []
    return [title for title in titles if title][:8]


def _ignored_titles(store: Store, ensemble_id: str) -> list[str]:
    raw = store.meta(f"ignored:{ensemble_id}")
    if not raw:
        return []
    try:
        found = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [title for title in found if isinstance(title, str)]


def _make_claim(source: Source, guess: dict, url: str, stamp, nifty: float | None, store: Store | None = None) -> Claim:
    guess = dict(guess)
    key = guess["shock_key"]
    if store is not None and not key.startswith("level:"):
        count, total = store.family_stats(key)
        driver = guess.get("driver")
        pairs = store.family_pairs(key, clean_only=True) if driver is not None else []
        if driver is not None and len(pairs) >= 30:
            fitted = fit_move(pairs, float(driver), float(guess["midpoint"]))
            guess["midpoint"] = round(max(-150.0, min(150.0, fitted)), 1)
        elif count > 0:
            guess = apply_family_bias(guess, count, total)
    horizon = guess.get("horizon") or "session"
    if horizon == "open":
        when = next_open(stamp)
    elif horizon == "week":
        when = sessions_ahead(stamp)
    else:
        when = session_close(stamp)
    return Claim(
        id=uuid4().hex[:12],
        beat=guess["beat"],
        source_id=source.id,
        ts=stamp.isoformat(),
        headline=guess["headline"],
        url=url,
        shock_key=guess["shock_key"],
        direction=guess["direction"],
        points_low=guess["points_low"],
        points_high=guess["points_high"],
        midpoint=guess["midpoint"],
        confidence=guess["confidence"],
        nifty_level=nifty,
        score_after=when.isoformat(),
        status="open",
        body=guess.get("body") or guess["headline"],
        horizon=horizon,
        driver=guess.get("driver"),
    )


def _fail(store: Store, source: Source, stamp) -> None:
    source.fail_streak += 1
    if source.fail_streak >= 3 and source.status not in {"retired", "down"}:
        source.status = "down"
        source.weight = 0
    store.save_source(source)


def _note_links(store: Store, config: dict, summary: str, beat: str) -> None:
    allow = {item.lower() for item in config.get("allowlist") or []}
    known = store.known_domains()
    for url in hrefs(summary):
        domain = domain_of(url)
        if not domain or domain in known:
            continue
        if domain in allow:
            if store.add_probation_source(domain, url, beat):
                known.add(domain)
        else:
            store.remember_link(domain, url, "proposal")


def _learned_pcr_sign(source: Source) -> float:
    if source.n_scored < 20 or source.n_scored == 0:
        return 0.0
    return source.residual_sum / source.n_scored


def _close_on_or_after(bars, day: str) -> float | None:
    for bar_day, close in bars:
        if bar_day >= day:
            return close
    return None


def _ensemble_by_id(store: Store, ensemble_id: str):
    for item in store.ensembles():
        if item.id == ensemble_id:
            return item
    return None

