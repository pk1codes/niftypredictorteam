from __future__ import annotations

import math
from html import escape

from datetime import datetime, timedelta

from niftyteam.config import BEAT_LABELS, BOARD_AGENT, BOSS_AGENT, MISSED_LINES, ROSTER, SCORE_AGENT, STATUS_LINES, impact_class, impact_text
from niftyteam.learn import agent_misses, shift_trail
from niftyteam.models import Claim, Ensemble, Event, parse_ts


def render_page(
    ensemble: Ensemble | None,
    residuals: list[tuple[float, float]],
    events: list[Event],
    nifty: float | None,
    scored: int,
    last_run: str | None = None,
    gift: dict | None = None,
    fii_net: float | None = None,
    notes: list[str] | None = None,
    agents: int | None = None,
    history: list[Ensemble] | None = None,
    open_call: Ensemble | None = None,
    claims: list[Claim] | None = None,
) -> str:
    gift_price = None if gift is None else gift.get("price")
    current = _current_chart(ensemble, nifty, gift_price, history, last_run)
    errors = _error_chart(residuals)
    log = _activity(events)
    learning = _learning(claims or [], history or [])
    level = f"Nifty {nifty:,.0f}" if nifty else "Nifty price pending"
    early = ""
    if scored < 30:
        early = f"<p class='note'>Early curve. {scored} scored forecasts. The error bell settles after a few dozen checks.</p>"
    status = _status(last_run)
    gift_tile = _quote_tile("GIFT Nifty", None if gift is None else gift["price"], None if gift is None else gift["change"], points=True)
    fii_tile = _quote_tile("FII net", fii_net, fii_net, suffix=" cr")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="60">
<title>Nifty board</title>
<style>
  body {{ margin: 0; background: #f6f4ef; color: #1c1915; font: 16px/1.45 Georgia, "Iowan Old Style", serif; }}
  main {{ max-width: 880px; margin: 0 auto; padding: 28px 20px 64px; }}
  h1 {{ font-size: 28px; font-weight: 600; margin: 0 0 4px; }}
  .sub {{ color: #5e584f; margin: 0 0 10px; }}
  .status {{ display: flex; gap: 16px; align-items: center; flex-wrap: wrap; margin: 0 0 16px; font: 14px/1.3 ui-sans-serif, sans-serif; color: #5e584f; }}
  .light {{ width: 12px; height: 12px; border-radius: 50%; background: #b9b2a6; display: inline-block; flex: none; }}
  .light.on {{ background: #0c7a3a; animation: pulse 1.6s infinite; }}
  @keyframes pulse {{
    0% {{ box-shadow: 0 0 0 0 rgba(12, 122, 58, .45); }}
    70% {{ box-shadow: 0 0 0 8px rgba(12, 122, 58, 0); }}
    100% {{ box-shadow: 0 0 0 0 rgba(12, 122, 58, 0); }}
  }}
  .state {{ color: #1c1915; }}
  .stats {{ display: flex; gap: 18px; flex-wrap: wrap; margin-bottom: 8px; }}
  .stats div {{ background: #fff; border: 1px solid #e4ddd2; border-radius: 10px; padding: 10px 14px; min-width: 120px; }}
  .stats span {{ display: block; color: #746c62; font: 12px/1.2 ui-sans-serif, sans-serif; letter-spacing: .04em; text-transform: uppercase; }}
  .note {{ color: #746c62; font-size: 14px; }}
  .top {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; margin-bottom: 16px; }}
  figure {{ background: #fff; border: 1px solid #e4ddd2; border-radius: 12px; margin: 0 0 16px; padding: 8px 8px 0; }}
  .top figure {{ margin: 0; }}
  figcaption {{ font: 13px/1.3 ui-sans-serif, sans-serif; color: #5e584f; padding: 4px 8px 10px; }}
  .mark-spot {{ color: #0c7a3a; }}
  .mark-gift {{ color: #b86e00; }}
  .mark-next {{ color: #1d4e89; }}
  .mark-mean {{ color: #6b3fa0; }}
  svg {{ width: 100%; height: auto; display: block; }}
  .roster {{ margin-top: 18px; background: #fff; border: 1px solid #e4ddd2; border-radius: 12px; }}
  .roster-head {{ display: flex; justify-content: space-between; padding: 12px 14px 4px; font: 600 12px/1.2 ui-sans-serif, sans-serif; letter-spacing: .04em; text-transform: uppercase; color: #746c62; }}
  .matters {{ display: grid; gap: 10px; margin: 0 0 16px; }}
  .matters section {{ background: #fff; border: 1px solid #e4ddd2; border-radius: 12px; padding: 10px 14px 6px; }}
  .matters h2 {{ margin: 0 0 6px; display: flex; justify-content: space-between; align-items: baseline; font: 600 12px/1.2 ui-sans-serif, sans-serif; letter-spacing: .04em; text-transform: uppercase; color: #746c62; }}
  .matters h2 .impact {{ letter-spacing: 0; }}
  .matter {{ display: flex; gap: 10px; align-items: baseline; padding: 7px 0; border-top: 1px solid #f0ebe3; }}
  .matter.bad .line {{ color: #8a1c1c; }}
  .matter.idle .line {{ color: #8a5a00; }}
  .agent {{ display: flex; gap: 10px; align-items: baseline; padding: 8px 14px; border-top: 1px solid #f0ebe3; }}
  .agent.idle {{ background: #fff6e8; }}
  .agent.bad {{ background: #fdecea; }}
  .dot {{ width: 8px; height: 8px; border-radius: 50%; background: #b9b2a6; flex: none; }}
  .dot.ok {{ background: #0c7a3a; }}
  .dot.bad {{ background: #c47b00; }}
  .name {{ width: 72px; flex: none; font: 13px/1.3 ui-sans-serif, sans-serif; color: #5e584f; }}
  .line {{ flex: 1; }}
  .trail, .score {{ margin: 0; padding: 8px 14px; border-top: 1px solid #f0ebe3; color: #746c62; font: 13px/1.3 ui-sans-serif, sans-serif; }}
  .score {{ color: #1c1915; }}
  .impact {{ flex: none; min-width: 52px; text-align: right; font: 600 16px/1 ui-sans-serif, sans-serif; }}
  .plus {{ color: #0c7a3a; }}
  .minus {{ color: #c62828; }}
  .flat {{ color: #1c1915; }}
  .empty {{ padding: 16px; color: #746c62; }}
  .learn {{ margin-top: 12px; background: #fff; border: 1px solid #e4ddd2; border-radius: 12px; }}
  .learn .agent .line {{ color: #746c62; }}
  .learn .up {{ color: #0c7a3a; }}
  .learn .down {{ color: #c62828; }}
  .spark {{ width: 72px; height: 16px; flex: none; }}
  @media (max-width: 720px) {{ .top {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<main>
  <div class="top">
    <div>
      <h1>Nifty board</h1>
      <p class="sub">{escape(level)}</p>
      {status}
      <div class="stats">
        {gift_tile}
        {fii_tile}
      </div>
      {early}
    </div>
    <figure>{current}<figcaption>Curve is ±3 spreads around the <span class="mark-mean">200-day mean</span>. Faint curves are the previous three bells.</figcaption></figure>
  </div>
  {_matters(events)}
  <figure>{errors}<figcaption>Actual minus mean, once scores exist.</figcaption></figure>
  {log}
  {learning}
</main>
<script>
const lastRaw = document.getElementById("status").dataset.last;
const freshMs = 75 * 60 * 1000;
const istShift = 5.5 * 60 * 60 * 1000;
function paint() {{
  const light = document.getElementById("light");
  const state = document.getElementById("state");
  const next = document.getElementById("next-run");
  const now = Date.now();
  const last = lastRaw ? Date.parse(lastRaw) : NaN;
  const alive = !Number.isNaN(last) && (now - last) < freshMs;
  light.className = alive ? "light on" : "light";
  state.textContent = alive ? "Running" : "Idle";
  const ist = new Date(now + istShift);
  const boundary = Date.UTC(ist.getUTCFullYear(), ist.getUTCMonth(), ist.getUTCDate(), ist.getUTCHours() + 1);
  const remain = Math.max(0, boundary - istShift - now);
  const mins = Math.floor(remain / 60000);
  next.textContent = mins >= 1 ? ("Next update in " + mins + " min") : ("Next update in " + Math.ceil(remain / 1000) + " sec");
}}
paint();
setInterval(paint, 1000);
</script>
</body>
</html>
"""


def _status(last_run: str | None) -> str:
    if not last_run:
        label = "—"
        fresh = False
        stamp = ""
    else:
        parsed = parse_ts(last_run)
        label = parsed.strftime("%d %b %H:%M")
        age = datetime.now(parsed.tzinfo) - parsed
        fresh = age.total_seconds() < 75 * 60
        stamp = escape(last_run)
    light = "light on" if fresh else "light"
    word = "Running" if fresh else "Idle"
    return (
        f"<div class='status' id='status' data-last='{stamp}'>"
        f"<span class='{light}' id='light'></span>"
        f"<span class='state' id='state'>{word}</span>"
        f"<span id='last-run'>Last run {escape(label)}</span>"
        f"<span id='next-run'>Next update</span>"
        f"</div>"
    )


def _quote_tile(label: str, value: float | None, tint: float | None, suffix: str = "", points: bool = False) -> str:
    if value is None:
        shown = "—"
        kind = "flat"
    else:
        if points:
            shown = f"{value:,.0f}"
            if tint is not None:
                change = int(tint) if float(tint).is_integer() else tint
                extra = impact_text(change) if isinstance(change, int) else f"{change:+.1f}"
                shown = f"{shown} {extra}"
        else:
            number = int(round(value))
            shown = f"{number:+,}{suffix}"
        kind = impact_class(0 if tint is None else tint)
    return f"<div><span>{escape(label)}</span><strong class='{kind}'>{escape(shown)}</strong></div>"


def _matters(events: list[Event]) -> str:
    grouped: dict[str, list[Event]] = {}
    order: list[str] = []
    for event in events:
        if event.ts not in grouped:
            order.append(event.ts)
            grouped[event.ts] = []
        grouped[event.ts].append(event)
    if not order:
        return ""
    found = _by_agent(grouped[order[0]])
    moving = []
    watching = []
    for key, name in ROSTER:
        event = found.get(key)
        sentence = event.sentence if event else "No check"
        impact = event.impact if event else 0
        if sentence in MISSED_LINES or sentence == "No check":
            watching.append((name, sentence, "bad", impact))
        elif sentence in STATUS_LINES:
            watching.append((name, sentence, "idle", impact))
        else:
            moving.append((name, sentence, "ok", impact))
    moving.sort(key=lambda row: abs(row[3]), reverse=True)
    boss = found.get(BOSS_AGENT)
    if boss is not None:
        watching.append(("Boss", boss.sentence, _row_kind(boss.sentence), 0))
    score = found.get(SCORE_AGENT)
    if score is not None and ("Missed" in score.sentence or "Kept" in score.sentence):
        moving.insert(0, ("Score", score.sentence, "bad", score.impact))
    move_html = _matter_rows(moving) or "<p class='matter'><span class='line'>No strong event this hour.</span></p>"
    watch_html = _matter_rows(watching) or "<p class='matter'><span class='line'>Every agent answered.</span></p>"
    return (
        "<div class='matters'>"
        f"<section><h2>Moving the forecast{_mover_total(moving)}</h2>{move_html}</section>"
        f"<section><h2>Quiet or stuck</h2>{watch_html}</section>"
        "</div>"
    )


def _mover_total(rows: list[tuple[str, str, str, float]]) -> str:
    shown = [int(round(impact)) for _name, sentence, kind, impact in rows if _shows_impact(kind, sentence)]
    if not shown:
        return ""
    total = sum(shown)
    return f"<span class='impact {impact_class(total)}'>{impact_text(total)}</span>"


def _shows_impact(kind: str, sentence: str) -> bool:
    return kind == "ok" and not sentence.startswith("Restarted")


def _matter_rows(rows: list[tuple[str, str, str, float]]) -> str:
    html = []
    for name, sentence, kind, impact in rows:
        points = ""
        if _shows_impact(kind, sentence):
            points = f"<span class='impact {impact_class(impact)}'>{impact_text(impact)}</span>"
        html.append(
            f"<div class='matter {kind}'><span class='name'>{escape(name)}</span>"
            f"<span class='line'>{escape(sentence)}</span>{points}</div>"
        )
    return "\n".join(html)


def _activity(events: list[Event]) -> str:
    grouped: dict[str, list[Event]] = {}
    order: list[str] = []
    for event in events:
        if event.ts not in grouped:
            order.append(event.ts)
            grouped[event.ts] = []
        grouped[event.ts].append(event)
    if not order:
        return "<p class='empty'>No checks yet.</p>"
    latest = grouped[order[0]]
    score = next((event for event in latest if event.agent == SCORE_AGENT), None)
    score_html = f"<p class='score'>{escape(score.sentence)}</p>" if score else ""
    trail = "\n".join(_trail_line(stamp, grouped[stamp]) for stamp in order[1:7])
    return (
        "<section class='roster'>"
        f"<div class='roster-head'><span>Agents</span><span>{_checked(latest)} of 8</span></div>"
        f"{_roster_rows(latest)}{score_html}{trail}"
        "</section>"
    )


def _learning(claims: list[Claim], ensembles: list[Ensemble]) -> str:
    series = agent_misses(claims, ensembles)
    names = list(ROSTER) + [(BOARD_AGENT, "Board")]
    rows = "\n".join(_learn_row(name, series.get(key) or []) for key, name in names)
    return f"<section class='learn'><div class='roster-head'><span>Learning</span></div>{rows}</section>"


def _learn_row(name: str, misses: list[float]) -> str:
    trail = shift_trail(misses)
    if not trail:
        return (
            f"<div class='agent'><span class='name'>{escape(name)}</span>"
            f"<span class='line'>Not enough scores</span></div>"
        )
    shift = trail[-1]
    kind = "up" if shift > 0.5 else "down" if shift < -0.5 else ""
    return (
        f"<div class='agent'><span class='name'>{escape(name)}</span>"
        f"{_spark(trail)}<span class='line {kind}'>{impact_text(shift)}</span></div>"
    )


def _spark(scores: list[float]) -> str:
    width, height = 72, 16
    pts = []
    last = max(len(scores) - 1, 1)
    for index, score in enumerate(scores):
        x = 2 + (width - 4) * index / last
        y = 2 + (height - 4) * (1 - (score + 30) / 60)
        pts.append(f"{x:.1f},{y:.1f}")
    return (
        f"<svg class='spark' viewBox='0 0 {width} {height}' aria-hidden='true'>"
        f"<polyline fill='none' stroke='currentColor' stroke-width='1.5' points='{' '.join(pts)}'/>"
        f"</svg>"
    )


def _roster_rows(events: list[Event]) -> str:
    found = _by_agent(events)
    names = list(ROSTER) + [(BOARD_AGENT, "Board")]
    rows = [_agent_row(name, found.get(key)) for key, name in names]
    boss = found.get(BOSS_AGENT)
    if boss is not None:
        rows.insert(0, _agent_row("Boss", boss))
    return "\n".join(rows)


def _row_kind(sentence: str) -> str:
    if sentence.startswith("Watching"):
        return "idle"
    if "still stuck" in sentence.lower():
        return "bad"
    if sentence in MISSED_LINES or sentence == "No check":
        return "bad"
    if sentence in STATUS_LINES:
        return "idle"
    return "ok"


def _agent_row(name: str, event: Event | None) -> str:
    sentence = event.sentence if event else "No check"
    impact = event.impact if event else 0
    kind = _row_kind(sentence)
    points = ""
    boss = sentence.startswith("Watching") or sentence.startswith("Restarted")
    if not boss and sentence not in STATUS_LINES and sentence != "No check":
        points = f"<span class='impact {impact_class(impact)}'>{impact_text(impact)}</span>"
    return (
        f"<div class='agent {kind}'><span class='dot {kind}'></span>"
        f"<span class='name'>{escape(name)}</span>"
        f"<span class='line'>{escape(sentence)}</span>{points}</div>"
    )


def _trail_line(stamp: str, events: list[Event]) -> str:
    when = parse_ts(stamp).strftime("%H:%M")
    board = _by_agent(events).get(BOARD_AGENT)
    mean = "—"
    if board is not None and board.sentence not in STATUS_LINES:
        mean = impact_text(board.impact)
    return f"<p class='trail'>{escape(when)} · {_checked(events)} of 8 · mean {escape(mean)}</p>"


def _checked(events: list[Event]) -> int:
    found = _by_agent(events)
    count = 0
    for key, _name in ROSTER:
        event = found.get(key)
        if event is not None and event.sentence not in MISSED_LINES:
            count += 1
    return count


def _by_agent(events: list[Event]) -> dict[str, Event]:
    found: dict[str, Event] = {}
    for event in events:
        agent = _agent_of(event)
        if agent and agent not in found:
            found[agent] = event
    return found


def _agent_of(event: Event) -> str:
    if event.agent:
        return event.agent
    text = event.sentence
    if text.startswith("Scored"):
        return SCORE_AGENT
    if text.startswith("Board ready") or text.startswith("Spread "):
        return BOARD_AGENT
    if text.startswith("Scout"):
        return "scout"
    if text.startswith("FII") or text.startswith("Flows:"):
        return "flows"
    lowered = text.lower()
    if "put-call" in lowered or text.startswith("Weekly put-call") or text.startswith("Monthly put-call"):
        return "pcr"
    for key, label in BEAT_LABELS.items():
        if text.startswith(f"{label}:"):
            return key
    return ""


def _current_chart(
    ensemble: Ensemble | None,
    nifty: float | None,
    gift: float | None,
    history: list[Ensemble] | None,
    last_run: str | None,
) -> str:
    rows = history if history is not None else ([ensemble] if ensemble is not None else [])
    as_of = parse_ts(last_run) if last_run else None
    book_mean, book_sigma = _prediction_book(rows, as_of)
    nxt = _next_level(ensemble, nifty)
    if nxt is None and book_mean is None and nifty is None and gift is None:
        return _empty_chart("No forecast this hour.")
    impact = None if ensemble is None else ensemble.mu
    return _forecast_svg(nifty, gift, nxt, impact, book_mean, book_sigma, _ghost_books(rows))


def _next_level(ensemble: Ensemble | None, nifty: float | None) -> float | None:
    if ensemble is None:
        return None
    anchor = ensemble.nifty_level if ensemble.nifty_level is not None else nifty
    if anchor is None:
        return None
    return anchor + ensemble.mu


def _prediction_book(rows: list[Ensemble], as_of: datetime | None) -> tuple[float | None, float | None]:
    cutoff = None if as_of is None else as_of - timedelta(days=200)
    levels: list[float] = []
    for row in rows:
        if row.nifty_level is None:
            continue
        if cutoff is not None and _stamp(row.ts, cutoff) < cutoff:
            continue
        levels.append(row.nifty_level + row.mu)
    if not levels:
        return None, None
    mean = sum(levels) / len(levels)
    if len(levels) < 2:
        return mean, None
    var = sum((item - mean) ** 2 for item in levels) / len(levels)
    return mean, math.sqrt(var)


def _stamp(value: str, other: datetime) -> datetime:
    stamp = parse_ts(value)
    if stamp.tzinfo is None and other.tzinfo is not None:
        return stamp.replace(tzinfo=other.tzinfo)
    if stamp.tzinfo is not None and other.tzinfo is None:
        return stamp.replace(tzinfo=None)
    return stamp


def _empty_chart(message: str) -> str:
    return f"<svg viewBox='0 0 400 220'><text x='20' y='110' fill='#746c62'>{escape(message)}</text></svg>"


def _level_text(value: float) -> str:
    return f"{value:,.0f}"


def _marker_text(name: str, value: float, impact: float | None) -> str:
    if name == "Next" and impact is not None:
        return f"Next {impact_text(impact)}"
    return f"{name} {_level_text(value)}"


def _ghost_books(rows: list[Ensemble]) -> list[tuple[float, float, float]]:
    stamps = sorted({row.ts for row in rows})
    if len(stamps) < 2:
        return []
    chosen = stamps[:-1][-3:]
    fades = (0.18, 0.35, 0.55)[-len(chosen):]
    found = []
    for stamp, fade in zip(chosen, fades):
        subset = [row for row in rows if row.ts <= stamp]
        mean, sigma = _prediction_book(subset, parse_ts(stamp))
        if mean is None or sigma is None or sigma <= 0:
            continue
        found.append((mean, sigma, fade))
    return found


def _forecast_svg(
    spot: float | None,
    gift: float | None,
    nxt: float | None,
    impact: float | None,
    book_mean: float | None,
    book_sigma: float | None,
    ghosts: list[tuple[float, float, float]] | None = None,
) -> str:
    width, pad = 400, 28
    sigma = book_sigma if book_sigma and book_sigma > 0 else None
    ghosts = ghosts or []
    marks: list[float] = []
    if sigma is not None and book_mean is not None:
        marks.extend((book_mean - 3 * sigma, book_mean + 3 * sigma))
    for mean, spread, _fade in ghosts:
        marks.extend((mean - 3 * spread, mean + 3 * spread))
    for value in (spot, gift, nxt, book_mean):
        if value is not None:
            marks.append(value)
    lo, hi = min(marks), max(marks)
    cushion = max((hi - lo) * 0.06, (sigma or 1) * 0.2, 1)
    lo -= cushion
    hi += cushion
    span = hi - lo or 1
    plot_top, baseline = 16, 150
    legend_rows = max(1, (sum(value is not None for value in (spot, gift, nxt, book_mean)) + 1) // 2)
    height = 188 + legend_rows * 18

    def sx(x: float) -> float:
        return pad + (x - lo) / span * (width - 2 * pad)

    markers: list[tuple[str, float, str]] = []
    if spot is not None:
        markers.append(("Spot", spot, "#0c7a3a"))
    if gift is not None:
        markers.append(("GIFT", gift, "#b86e00"))
    if nxt is not None:
        markers.append(("Next", nxt, "#1d4e89"))
    if book_mean is not None:
        markers.append(("Mean", book_mean, "#6b3fa0"))

    parts = [
        f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='Forecast' "
        "style='font-family:ui-sans-serif,sans-serif'>"
    ]
    for step in range(1, 4):
        y = plot_top + (baseline - plot_top) * step / 4
        parts.append(f"<line x1='{pad}' y1='{y:.1f}' x2='{width - pad}' y2='{y:.1f}' stroke='#f3efe8'/>")
    parts.append(f"<line x1='{pad}' y1='{baseline}' x2='{width - pad}' y2='{baseline}' stroke='#e4ddd2'/>")

    def curve(mean: float, spread: float) -> list[str]:
        peak = 1 / (spread * math.sqrt(2 * math.pi))
        band_lo, band_hi = mean - 3 * spread, mean + 3 * spread

        def sy(y: float) -> float:
            return plot_top + (1 - y / peak) * (baseline - plot_top)

        pts = []
        for i in range(97):
            x = band_lo + (band_hi - band_lo) * i / 96
            y = math.exp(-0.5 * ((x - mean) / spread) ** 2) / (spread * math.sqrt(2 * math.pi))
            pts.append(f"{sx(x):.1f},{sy(y):.1f}")
        return pts

    def bell(mean: float, spread: float, opacity: float | None) -> None:
        pts = curve(mean, spread)
        if opacity is None:
            edge = f"{sx(mean - 3 * spread):.1f},{baseline} "
            close = f" {sx(mean + 3 * spread):.1f},{baseline}"
            parts.append(
                f"<polygon points='{edge}{' '.join(pts)}{close}' fill='#6b3fa0' fill-opacity='0.12' stroke='none'/>"
            )
            parts.append(f"<polyline fill='none' stroke='#6b3fa0' stroke-width='2' points='{' '.join(pts)}'/>")
            return
        parts.append(
            f"<polyline fill='none' stroke='#6b3fa0' stroke-width='1.5' stroke-opacity='{opacity}' points='{' '.join(pts)}'/>"
        )

    if sigma is not None and book_mean is not None:
        for mean, spread, fade in ghosts:
            bell(mean, spread, fade)
        bell(book_mean, sigma, None)
    elif ghosts:
        for mean, spread, fade in ghosts:
            bell(mean, spread, fade)
    else:
        parts.append(
            f"<text x='{pad}' y='{baseline - 16}' fill='#746c62' font-size='12'>Bell starts after two predictions.</text>"
        )
    for name, value, color in markers:
        x = sx(value)
        dash = " stroke-dasharray='3 3'" if name == "Mean" else ""
        parts.append(
            f"<line x1='{x:.1f}' y1='{baseline - 8}' x2='{x:.1f}' y2='{baseline + 5}' stroke='{color}' stroke-width='2'{dash}/>"
        )
    _axis_labels(parts, lo, hi, sx, baseline + 18, width)
    for index, (name, value, color) in enumerate(markers):
        column, row = divmod(index, legend_rows)
        x = pad + column * 190
        y = baseline + 42 + row * 18
        parts.append(f"<circle cx='{x + 4}' cy='{y - 3}' r='3.5' fill='{color}'/>")
        parts.append(
            f"<text x='{x + 14}' y='{y}' font-size='12' fill='#1c1915'>{escape(_marker_text(name, value, impact))}</text>"
        )
    parts.append("</svg>")
    return "".join(parts)


def _axis_labels(parts: list[str], lo: float, hi: float, sx, y: float, width: int) -> None:
    placed = -1e9
    for step in range(5):
        value = lo + (hi - lo) * step / 4
        x = sx(value)
        if x - placed < 52:
            continue
        anchor = "start" if step == 0 else "end" if step == 4 else "middle"
        lx = max(8, min(width - 8, x))
        parts.append(
            f"<text x='{lx:.1f}' y='{y:.1f}' text-anchor='{anchor}' font-size='10' fill='#746c62'>{_level_text(value)}</text>"
        )
        placed = x


def _error_chart(residuals: list[tuple[float, float]]) -> str:
    if len(residuals) < 2:
        return "<svg viewBox='0 0 400 220'><text x='20' y='110' fill='#746c62'>No error curve yet.</text></svg>"
    errors = [item[0] for item in residuals]
    mean = sum(errors) / len(errors)
    var = sum((item - mean) ** 2 for item in errors) / len(errors)
    sigma = math.sqrt(var) or 1
    return _bell_svg(mean, sigma, None, "Errors", bars=errors)


def _bell_svg(mu: float, sigma: float, actual: float | None, label: str, bars: list[float] | None = None) -> str:
    width, height, pad = 400, 220, 28
    lo, hi = mu - 3.2 * sigma, mu + 3.2 * sigma
    span = hi - lo or 1
    peak = 1 / (sigma * math.sqrt(2 * math.pi))

    def sx(x: float) -> float:
        return pad + (x - lo) / span * (width - 2 * pad)

    def sy(y: float) -> float:
        return 16 + (1 - y / peak) * (height - 56)

    pts = []
    for i in range(81):
        x = lo + span * i / 80
        y = math.exp(-0.5 * ((x - mu) / sigma) ** 2) / (sigma * math.sqrt(2 * math.pi))
        pts.append(f"{sx(x):.1f},{sy(y):.1f}")
    parts = [f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='{escape(label)}'>"]
    parts.append("<line x1='28' y1='188' x2='372' y2='188' stroke='#e4ddd2'/>")
    if bars:
        for value in bars:
            if lo <= value <= hi:
                parts.append(
                    f"<line x1='{sx(value):.1f}' y1='150' x2='{sx(value):.1f}' y2='188' stroke='#c4b8a8' stroke-width='3'/>"
                )
    parts.append(f"<polyline fill='none' stroke='#1c1915' stroke-width='2' points='{' '.join(pts)}'/>")
    parts.append(f"<line x1='{sx(mu):.1f}' y1='24' x2='{sx(mu):.1f}' y2='188' stroke='#1c1915' stroke-dasharray='3 3'/>")
    parts.append(f"<text x='{sx(mu):.1f}' y='16' text-anchor='middle' font-size='11' fill='#5e584f'>{impact_text(mu)}</text>")
    if actual is not None and lo <= actual <= hi:
        color = "#0c7a3a" if actual > 0 else "#c62828" if actual < 0 else "#1c1915"
        parts.append(f"<line x1='{sx(actual):.1f}' y1='24' x2='{sx(actual):.1f}' y2='188' stroke='{color}' stroke-width='2'/>")
    parts.append("</svg>")
    return "".join(parts)
