from __future__ import annotations

import math
from html import escape

from datetime import datetime, timedelta

from niftyteam.config import BEAT_LABELS, BOARD_AGENT, BOSS_AGENT, MISSED_LINES, ROSTER, SCORE_AGENT, STATUS_LINES, impact_class, impact_text
from niftyteam.estimate import news_shifts
from niftyteam.horizons import next_open, session_close
from niftyteam.learn import agent_misses, learning_score, learning_trail, shift_trail
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
    ahead: dict | None = None,
    feeds: list[dict] | None = None,
    families: list[tuple[str, int, float]] | None = None,
) -> str:
    gift_price = None if gift is None else gift.get("price")
    current = _current_chart(ensemble, nifty, gift_price, history, last_run)
    errors = _error_chart(residuals, history or [])
    log = _activity(events, feeds)
    learning = _learning(claims or [], history or [])
    news = _news(families or [])
    level = f"Nifty {nifty:,.0f}" if nifty else "Nifty price pending"
    early = ""
    if scored < 30:
        early = f"<p class='note'>Early days. {scored} predictions checked. The line settles after a few dozen checks, so treat it as a first look.</p>"
    status = _status(last_run)
    gift_tile = _quote_tile("GIFT Nifty", None if gift is None else gift["price"], None if gift is None else gift["change"], points=True, hint="Traded outside India. A plus means the next open may be higher.")
    fii_tile = _quote_tile("FII net", fii_net, fii_net, suffix=" cr", hint="Foreign money, in crore. Plus is buying.")
    called = _compare_html(ensemble, history or [], nifty)
    topline = _topline(history or [], gift, open_call)
    outlook = _ahead_html(ahead)
    split = f"<div class='split'>{called}{outlook}</div>" if called or outlook else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>Nifty board</title>
<style>
  body {{ margin: 0; background: #efeae3; color: #1c1915; font: 16px/1.45 ui-sans-serif, system-ui, sans-serif; }}
  main {{ max-width: 1040px; margin: 0 auto; padding: 20px 16px 80px; }}
  .mast {{ display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; margin-bottom: 8px; }}
  h1 {{ margin: 0; font: 600 12px/1.2 ui-sans-serif, sans-serif; letter-spacing: .14em; text-transform: uppercase; color: #746c62; }}
  .sub {{ margin: 4px 0 0; color: #1c1915; font: 600 36px/1.05 ui-sans-serif, sans-serif; letter-spacing: -.03em; font-variant-numeric: tabular-nums; }}
  .lead {{ margin: 0 0 16px; color: #5e584f; font: 15px/1.4 ui-sans-serif, sans-serif; }}
  .status {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin: 0; padding: 7px 12px 7px 10px; background: #fff; border: 1px solid #e4ddd2; border-radius: 999px; font: 13px/1.3 ui-sans-serif, sans-serif; color: #5e584f; }}
  .light {{ width: 10px; height: 10px; border-radius: 50%; background: #b9b2a6; display: inline-block; flex: none; }}
  .light.on {{ background: #0c7a3a; animation: pulse 1.6s infinite; }}
  @keyframes pulse {{
    0% {{ box-shadow: 0 0 0 0 rgba(12, 122, 58, .45); }}
    70% {{ box-shadow: 0 0 0 8px rgba(12, 122, 58, 0); }}
    100% {{ box-shadow: 0 0 0 0 rgba(12, 122, 58, 0); }}
  }}
  .state {{ color: #1c1915; font-weight: 650; }}
  .topline {{ background: #fff; border: 1px solid #e4ddd2; border-radius: 16px; margin: 0 0 16px; padding: 12px 14px 4px; box-shadow: inset 0 3px 0 #1d4e89; }}
  .top-grid {{ display: grid; grid-template-columns: 1.5fr .9fr .9fr; gap: 12px; }}
  .top-card span {{ display: block; color: #746c62; font: 600 11px/1.2 ui-sans-serif, sans-serif; letter-spacing: .06em; text-transform: uppercase; }}
  .top-pair {{ display: flex; flex-wrap: wrap; gap: 14px; align-items: flex-end; margin-top: 6px; }}
  .top-pair b {{ display: block; color: #1c1915; font: 600 26px/1 ui-sans-serif, sans-serif; letter-spacing: -.03em; font-variant-numeric: tabular-nums; }}
  .top-pair small {{ display: block; margin-top: 4px; color: #746c62; font: 600 13px/1.2 ui-sans-serif, sans-serif; font-variant-numeric: tabular-nums; }}
  .top-pair small.plus {{ color: #0c7a3a; }}
  .top-pair small.minus {{ color: #c62828; }}
  .top-pair .plus b {{ color: #0c7a3a; }}
  .top-pair .minus b {{ color: #c62828; }}
  .topline .call-plot {{ margin-top: 4px; }}
  .stats {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 0 0 16px; }}
  .stats .tile {{ background: #fff; border: 1px solid #e4ddd2; border-radius: 16px; padding: 14px 16px; min-width: 0; }}
  .stats .tile.plus {{ background: #f3faf6; border-color: #d5eadc; }}
  .stats .tile.minus {{ background: #fdf6f5; border-color: #f0d6d3; }}
  .stats span {{ display: block; color: #746c62; font: 600 11px/1.2 ui-sans-serif, sans-serif; letter-spacing: .06em; text-transform: uppercase; }}
  .stats strong {{ display: block; margin-top: 4px; font: 600 22px/1.2 ui-sans-serif, sans-serif; font-variant-numeric: tabular-nums; }}
  .stats em {{ display: block; margin-top: 6px; color: #5e584f; font: 13px/1.35 ui-sans-serif, sans-serif; font-style: normal; }}
  .note {{ margin: 0 0 16px; padding: 10px 12px; background: #f7f3fb; border: 1px solid #e4d8f2; border-radius: 10px; color: #5c4d73; font: 14px/1.4 ui-sans-serif, sans-serif; }}
  figure {{ background: #fff; border: 1px solid #e4ddd2; border-radius: 16px; margin: 0 0 16px; padding: 8px 8px 0; box-shadow: inset 0 3px 0 #6b3fa0; }}
  figure.errors {{ box-shadow: inset 0 3px 0 #c4b8a8; }}
  figure.errors svg {{ max-height: 420px; }}
  .error-read {{ margin: 8px 10px 0; color: #1c1915; font: 600 15px/1.35 ui-sans-serif, sans-serif; }}
  .error-note {{ margin: 2px 10px 0; color: #746c62; font: 13px/1.35 ui-sans-serif, sans-serif; }}
  figcaption {{ font: 13px/1.45 ui-sans-serif, sans-serif; color: #5e584f; padding: 6px 8px 12px; }}
  .mark-spot {{ color: #0c7a3a; font-weight: 650; }}
  .mark-gift {{ color: #b86e00; font-weight: 650; }}
  .mark-next {{ color: #1d4e89; font-weight: 650; }}
  .mark-mean {{ color: #6b3fa0; font-weight: 650; }}
  svg {{ width: 100%; height: auto; display: block; }}
  .split, .desk {{ display: grid; grid-template-columns: 1.15fr .85fr; gap: 16px; align-items: start; margin: 0 0 16px; }}
  .split > :only-child {{ grid-column: 1 / -1; }}
  .roster, .learn {{ margin: 0; background: #fff; border: 1px solid #e4ddd2; border-radius: 16px; overflow: hidden; }}
  .roster {{ box-shadow: inset 3px 0 0 #9a9186; }}
  .learn {{ box-shadow: inset 3px 0 0 #6b3fa0; }}
  .roster-head {{ display: flex; justify-content: space-between; align-items: baseline; padding: 12px 14px 2px; font: 600 12px/1.2 ui-sans-serif, sans-serif; letter-spacing: .06em; text-transform: uppercase; color: #4a453e; }}
  .count {{ color: #0c7a3a; letter-spacing: 0; }}
  .count.short {{ color: #8a5a00; }}
  .deck {{ margin: 0 0 8px; color: #746c62; font: 13px/1.35 ui-sans-serif, sans-serif; }}
  .roster .deck, .learn .deck {{ padding: 0 14px 8px; }}
  .matters {{ display: grid; grid-template-columns: 1.15fr .85fr; gap: 16px; align-items: start; margin: 0 0 16px; }}
  .matters section {{ background: #fff; border: 1px solid #e4ddd2; border-radius: 16px; padding: 14px 16px 12px; }}
  .matters section:first-child {{ box-shadow: inset 3px 0 0 #1d4e89; }}
  .matters section:last-child {{ box-shadow: inset 3px 0 0 #c4a574; }}
  .matters h2, .ahead h2, .compare h2 {{ margin: 0 0 4px; display: flex; justify-content: space-between; align-items: baseline; gap: 12px; font: 600 12px/1.2 ui-sans-serif, sans-serif; letter-spacing: .06em; text-transform: uppercase; color: #4a453e; }}
  .matters h2 .impact, .ahead h2 .impact {{ letter-spacing: 0; font-size: 22px; }}
  .matter {{ display: flex; gap: 10px; align-items: baseline; padding: 8px; margin-top: 6px; border-radius: 8px; }}
  .matter.ok {{ background: #f7f8f6; }}
  .matter.idle {{ background: #fbf6ee; }}
  .matter.bad {{ background: #fdf4f3; }}
  .matter.bad .line {{ color: #8a1c1c; }}
  .matter.idle .line {{ color: #8a5a00; }}
  .agent {{ display: flex; gap: 10px; align-items: baseline; padding: 8px 14px; border-top: 1px solid #f0ebe3; }}
  .agent.ok {{ box-shadow: inset 3px 0 0 #cfe8d8; }}
  .agent.idle {{ background: #fbf6ee; box-shadow: inset 3px 0 0 #e4c48a; }}
  .agent.bad {{ background: #fdf4f3; box-shadow: inset 3px 0 0 #e7b4ae; }}
  .dot {{ width: 8px; height: 8px; border-radius: 50%; background: #b9b2a6; flex: none; align-self: center; }}
  .dot.ok {{ background: #0c7a3a; }}
  .dot.idle {{ background: #b86e00; }}
  .dot.bad {{ background: #c62828; }}
  .name {{ width: 84px; flex: none; font: 600 13px/1.3 ui-sans-serif, sans-serif; color: #3f3a34; }}
  .line {{ flex: 1; min-width: 0; }}
  .trail, .score {{ margin: 0; padding: 8px 14px; border-top: 1px solid #f0ebe3; color: #746c62; font: 13px/1.35 ui-sans-serif, sans-serif; font-variant-numeric: tabular-nums; }}
  .score, .how {{ color: #1c1915; background: #f7f3fb; }}
  .how {{ font: 15px/1.45 ui-sans-serif, sans-serif; }}
  .impact {{ flex: none; min-width: 52px; text-align: right; font: 600 16px/1 ui-sans-serif, sans-serif; font-variant-numeric: tabular-nums; }}
  .matter .impact, .agent .impact, .off .impact {{ padding: 2px 8px; border-radius: 999px; background: #f4f1ea; }}
  .plus {{ color: #0c7a3a; }}
  .minus {{ color: #c62828; }}
  .flat {{ color: #5e584f; }}
  .matter .plus, .agent .plus, .off .plus {{ background: #e7f5ec; }}
  .matter .minus, .agent .minus, .off .minus {{ background: #fdeceb; }}
  .empty {{ margin: 0; padding: 16px; color: #746c62; background: #fff; border: 1px solid #e4ddd2; border-radius: 12px; }}
  .learn-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; padding: 0 14px 8px; }}
  .learn-card {{ display: grid; grid-template-columns: 1fr auto auto; align-items: baseline; gap: 2px 8px; border: 1px solid #efeae2; border-radius: 10px; padding: 8px 10px 6px; }}
  .learn-plot, .gain-plot {{ grid-column: 1 / -1; width: 100%; height: auto; }}
  .gain-banner {{ padding: 0 14px 10px; }}
  .gain-read {{ margin: 0 0 2px; color: #3f3a34; font: 600 15px/1 ui-sans-serif, sans-serif; }}
  .gain-read strong {{ font-size: 28px; margin-right: 6px; letter-spacing: 0; }}
  .gain {{ font-weight: 650; font-variant-numeric: tabular-nums; }}
  .gain.up {{ color: #0c7a3a; }}
  .gain.down {{ color: #c62828; }}
  .gain.flat {{ color: #5e584f; }}
  .learn .line.up {{ color: #0c7a3a; font-weight: 650; }}
  .learn .line.down {{ color: #c62828; font-weight: 650; }}
  .learn .wait {{ padding: 2px 14px 14px; margin: 0; }}
  .ahead, .compare {{ background: #fff; border: 1px solid #e4ddd2; border-radius: 16px; margin: 0; padding: 14px 16px 12px; box-shadow: inset 0 3px 0 #1d4e89; }}
  .ahead .name {{ width: auto; flex: 1; }}
  .ahead .matter {{ margin-top: 0; padding: 8px 0; border-radius: 0; background: transparent; border-top: 1px solid #f0ebe3; }}
  .ahead .due {{ margin: 0 0 4px; color: #746c62; font: 13px/1.35 ui-sans-serif, sans-serif; }}
  .compare .story {{ margin: 8px 0 0; color: #1c1915; font: 16px/1.5 ui-sans-serif, sans-serif; }}
  .compare .story strong {{ font-variant-numeric: tabular-nums; }}
  .compare .call-plot {{ margin: 2px 0 8px; }}
  .learn, .news {{ margin-top: 16px; }}
  .news {{ background: #fff; border: 1px solid #e4ddd2; border-radius: 16px; overflow: hidden; box-shadow: inset 3px 0 0 #1d4e89; }}
  .news-cols {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 0 14px 14px; }}
  .news h2 {{ margin: 0 0 4px; font: 600 12px/1.2 ui-sans-serif, sans-serif; letter-spacing: .06em; text-transform: uppercase; color: #746c62; }}
  .news-row {{ display: flex; justify-content: space-between; align-items: baseline; gap: 8px; padding: 6px 0; border-top: 1px solid #f0ebe3; }}
  .news-row .name {{ width: auto; flex: 1; }}
  .news .pts {{ flex: none; font: 600 16px/1 ui-sans-serif, sans-serif; font-variant-numeric: tabular-nums; color: #1c1915; }}
  .news-col.lighter .pts {{ color: #8a5a00; }}
  .news .quiet {{ margin: 0; color: #746c62; font: 14px/1.4 ui-sans-serif, sans-serif; }}
  .feeds {{ background: #fff; border: 1px solid #e4ddd2; border-radius: 16px; margin: 0 0 16px; padding: 14px 16px 16px; box-shadow: inset 3px 0 0 #1d4e89; }}
  .feeds h2 {{ margin: 0 0 8px; font: 600 12px/1.2 ui-sans-serif, sans-serif; letter-spacing: .06em; text-transform: uppercase; color: #4a453e; }}
  .feed-read {{ margin: 0 0 12px; color: #1c1915; font: 600 15px/1.35 ui-sans-serif, sans-serif; }}
  .feed-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; align-items: start; }}
  .feed {{ display: block; padding: 10px 12px 12px; border-radius: 12px; background: #faf8f5; border: 1px solid #efeae2; }}
  .feed.bad {{ background: #fdf4f3; border-color: #f0d6d3; }}
  .feed.idle {{ background: #fbf6ee; border-color: #f0e4cc; }}
  .feed-head {{ display: flex; justify-content: space-between; gap: 8px; align-items: baseline; }}
  .feed .name {{ width: auto; font-size: 15px; }}
  .feed .line {{ color: #746c62; font: 13px/1.3 ui-sans-serif, sans-serif; }}
  .feed-empty {{ margin: 8px 0 0; color: #8a1c1c; font: 14px/1.35 ui-sans-serif, sans-serif; }}
  .feed.idle .feed-empty {{ color: #8a5a00; }}
  .fate-bar {{ display: flex; height: 14px; margin: 10px 0 6px; border-radius: 999px; overflow: hidden; background: #f4f1ea; }}
  .fate-bar span {{ min-width: 8px; }}
  .fate-bar .up {{ background: #0c7a3a; }}
  .fate-bar .down {{ background: #c62828; }}
  .fate-bar .flat {{ background: #1d4e89; }}
  .fate-bar .watch {{ background: #e4c48a; }}
  .fate-bar .aside {{ background: #c4b8a8; }}
  .fate-key {{ display: flex; flex-wrap: wrap; gap: 6px 14px; margin: 0; color: #3f3a34; font: 13px/1.3 ui-sans-serif, sans-serif; }}
  .fate-key strong {{ font-variant-numeric: tabular-nums; }}
  .swatch {{ width: 8px; height: 8px; margin-right: 4px; border-radius: 2px; display: inline-block; vertical-align: 1px; }}
  .swatch.up {{ background: #0c7a3a; }}
  .swatch.down {{ background: #c62828; }}
  .swatch.flat {{ background: #1d4e89; }}
  .swatch.none {{ background: transparent; border: 1px solid #c4b8a8; box-sizing: border-box; }}
  .swatch.watch {{ background: #e4c48a; }}
  .swatch.aside {{ background: #c4b8a8; }}
  .fate-group {{ margin-top: 12px; }}
  .fate-group h3 {{ margin: 0; font: 600 11px/1.2 ui-sans-serif, sans-serif; letter-spacing: .06em; text-transform: uppercase; color: #746c62; }}
  .fate-deck, .fate-group .quiet {{ margin: 3px 0 0; color: #746c62; font: 12px/1.35 ui-sans-serif, sans-serif; }}
  .story {{ display: flex; gap: 8px; align-items: baseline; padding: 6px 0; border-top: 1px solid #f0ebe3; }}
  .story .title {{ flex: 1; min-width: 0; color: #1c1915; font: 13px/1.35 ui-sans-serif, sans-serif; }}
  .story .why {{ display: block; margin-top: 1px; color: #746c62; font: 12px/1.3 ui-sans-serif, sans-serif; }}
  .story .impact {{ min-width: 0; padding: 2px 8px; border-radius: 999px; background: #f4f1ea; }}
  .story .plus {{ background: #e7f5ec; }}
  .story .minus {{ background: #fdeceb; }}
  .story.aside .title {{ color: #5e584f; }}
  .watch-pile {{ margin-top: 12px; }}
  .watch-pile summary {{ cursor: pointer; color: #5e584f; font: 600 13px/1.3 ui-sans-serif, sans-serif; }}
  .watch-pile summary::-webkit-details-marker {{ display: none; }}
  .watch-pile summary::before {{ content: "▸ "; color: #746c62; }}
  .watch-pile[open] summary::before {{ content: "▾ "; }}
  .story.watch {{ display: block; padding: 4px 0; }}
  .story.watch .title {{ color: #5e584f; }}
  @media (max-width: 800px) {{
    .mast {{ flex-direction: column; align-items: flex-start; }}
    .sub {{ font-size: 30px; }}
    .split, .matters, .desk, .stats, .feed-row, .learn-grid, .news-cols, .top-grid {{ grid-template-columns: 1fr; }}
    .compare .story {{ font-size: 15px; }}
  }}
</style>
</head>
<body>
<main>
  <header class="mast">
    <div>
      <h1>Nifty board</h1>
      <p class="sub">{escape(level)}</p>
    </div>
    {status}
  </header>
  <p class="lead">One prediction for the 15:30 close. Green is up. Red is down.</p>
  {topline}
  <div class="stats">
    {gift_tile}
    {fii_tile}
  </div>
  {early}
  {_feeds_html(feeds)}
  <figure class="forecast">{current}<figcaption><span class="mark-spot">Spot</span> is the live index. <span class="mark-gift">GIFT</span> is the price outside India. <span class="mark-next">Next</span> is this hour’s prediction. The shaded band is the usual range around the <span class="mark-mean">200-day average</span>. Faint lines are the previous three.</figcaption></figure>
  {split}
  {_matters(events)}
  <figure class="errors">{errors}<figcaption>Each dot is one past prediction, oldest on the left. Below zero, the prediction was too high. Above zero, it was too low. The dashed line is the average miss. The curve is the recent path of the close predictions.</figcaption></figure>
  {log}
  {news}
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


def _feeds_html(feeds: list[dict] | None) -> str:
    if not feeds:
        return ""
    cards = []
    totals = {"used": 0, "watch": 0, "aside": 0, "points": 0}
    for row in feeds:
        card, counts = _feed_card(row)
        cards.append(card)
        for key in totals:
            totals[key] += counts[key]
    summary = _feeds_summary(totals)
    summary_html = f"<p class='feed-read'>{summary}</p>" if summary else ""
    return (
        "<section class='feeds' aria-label='Important feeds'>"
        "<h2>Important feeds</h2>"
        "<p class='deck'>A story is set aside only when it cannot move Nifty. The rest stay on watch. Points are added only when the story clearly says up or down.</p>"
        f"{summary_html}"
        f"<div class='feed-row'>{''.join(cards)}</div></section>"
    )


def _feeds_summary(totals: dict[str, int]) -> str:
    total = totals["used"] + totals["watch"] + totals["aside"]
    if total == 0:
        return ""
    if totals["used"]:
        lead = (
            f"{totals['used']} of {total} went into the prediction, adding "
            f"<strong class='{impact_class(totals['points'])}'>{impact_text(totals['points'])}</strong>."
        )
    else:
        lead = f"None of {total} stories went into the prediction."
    rest = []
    if totals["watch"]:
        rest.append(f"{totals['watch']} stayed on watch. No clear up or down.")
    if totals["aside"]:
        rest.append(f"{totals['aside']} were set aside.")
    return lead + (" " + " ".join(rest) if rest else "")


def _feed_card(row: dict) -> tuple[str, dict[str, int]]:
    state = str(row.get("state") or "wait")
    kind = "ok" if state == "read" else "bad" if state in {"miss", "down"} else "idle"
    label = escape(str(row.get("label") or ""))
    detail = str(row.get("detail") or "")
    stories = [_story_fate(str(line)) for line in row.get("lines") or [] if str(line)]
    empty = {"used": 0, "watch": 0, "aside": 0, "points": 0}
    head = f"<div class='feed-head'><span class='name'>{label}</span>"
    if not stories:
        note = f"<p class='feed-empty'>{escape(detail)}</p>" if detail else ""
        return f"<div class='feed {kind}'>{head}</div>{note}</div>", empty
    head += f"<span class='line'>{escape(detail)}</span></div>"
    used = [item for item in stories if item["fate"] == "used"]
    watch = [item for item in stories if item["fate"] == "watch"]
    aside = [item for item in stories if item["fate"] == "aside"]
    points = sum(item["points"] or 0 for item in used)
    counts = {"used": len(used), "watch": len(watch), "aside": len(aside), "points": points}
    up = sum(1 for item in used if (item["points"] or 0) > 0)
    down = sum(1 for item in used if (item["points"] or 0) < 0)
    flat = len(used) - up - down
    bar_counts = {"up": up, "down": down, "flat": flat, "watch": len(watch), "aside": len(aside)}
    return (
        f"<div class='feed {kind}'>{head}{_fate_bar(bar_counts)}{_fate_key(counts)}"
        f"{_used_group(used)}{_aside_group(aside)}{_watch_group(watch)}</div>"
    ), counts


def _story_fate(line: str) -> dict:
    title, _, note = line.partition(" — ")
    note = note.strip()
    if note.startswith("In the call") or note.startswith("In the prediction") or note.startswith("Kept,"):
        fate = "used"
    elif note.startswith("Kept"):
        fate = "watch"
    elif note:
        fate = "aside"
    else:
        fate = "watch"
    return {"title": title.strip(), "note": note, "fate": fate, "points": _note_points(note)}


def _note_points(note: str) -> int | None:
    for token in note.replace(",", " ").replace(".", " ").split():
        if token[:1] in "+-" and token[1:].isdigit():
            return int(token)
    return None


def _fate_bar(counts: dict[str, int]) -> str:
    parts = []
    for key in ("up", "down", "flat", "watch", "aside"):
        count = counts.get(key, 0)
        if count:
            parts.append(f"<span class='{key}' style='flex:{count} {count} 0'></span>")
    if not parts:
        return ""
    return f"<div class='fate-bar'>{''.join(parts)}</div>"


def _fate_key(counts: dict[str, int]) -> str:
    if counts["used"]:
        kind = impact_class(counts["points"])
        call = f"<strong class='{kind}'>{impact_text(counts['points'])}</strong> in the prediction"
        swatch = kind
    else:
        call = "<strong>0</strong> in the prediction"
        swatch = "none"
    return (
        "<p class='fate-key'>"
        f"<span><i class='swatch {swatch}'></i>{call}</span>"
        f"<span><i class='swatch watch'></i><strong>{counts['watch']}</strong> on watch</span>"
        f"<span><i class='swatch aside'></i><strong>{counts['aside']}</strong> set aside</span>"
        "</p>"
    )


def _used_group(rows: list[dict]) -> str:
    if not rows:
        return "<div class='fate-group'><h3>In the prediction</h3><p class='quiet'>Nothing from this feed went into the prediction.</p></div>"
    body = "".join(_used_row(row) for row in rows)
    return (
        "<div class='fate-group'>"
        "<h3>In the prediction</h3>"
        "<p class='fate-deck'>These stories clearly say up or down, so the points went into the prediction.</p>"
        f"{body}</div>"
    )


def _used_row(row: dict) -> str:
    points = row["points"]
    pill = ""
    if points is not None:
        pill = f"<span class='impact {impact_class(points)}'>{impact_text(points)}</span>"
    why = ""
    if row["note"].startswith("Kept,"):
        why = "<span class='why'>Kept, because it may move Nifty.</span>"
    title = f"<span class='title'>{escape(row['title'])}{why}</span>"
    return f"<div class='story used'>{title}{pill}</div>"


def _aside_group(rows: list[dict]) -> str:
    if not rows:
        return "<div class='fate-group'><h3>Set aside</h3><p class='quiet'>Nothing was set aside.</p></div>"
    body = "".join(
        "<div class='story aside'>"
        f"<span class='title'>{escape(row['title'])}<span class='why'>{escape(_plain(row['note']))}</span></span>"
        "</div>"
        for row in rows
    )
    return (
        "<div class='fate-group'>"
        "<h3>Set aside</h3>"
        "<p class='fate-deck'>Kept out because the story cannot move Nifty.</p>"
        f"{body}</div>"
    )


def _watch_group(rows: list[dict]) -> str:
    if not rows:
        return ""
    body = "".join(
        f"<div class='story watch'><span class='title'>{escape(row['title'])}</span></div>" for row in rows
    )
    return (
        "<details class='watch-pile'>"
        f"<summary>{len(rows)} on watch. No clear up or down, so no points.</summary>"
        f"{body}</details>"
    )


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


def _quote_tile(label: str, value: float | None, tint: float | None, suffix: str = "", points: bool = False, hint: str = "") -> str:
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
    note = f"<em>{escape(hint)}</em>" if hint else ""
    return f"<div class='tile {kind}'><span>{escape(label)}</span><strong class='{kind}'>{escape(shown)}</strong>{note}</div>"


def _topline(history: list[Ensemble], gift: dict | None, open_call: Ensemble | None) -> str:
    closed = _last_closed(history)
    opened = _next_open_call(history, open_call)
    gift_bits = _gift_bits(gift)
    if closed is None and opened is None and gift_bits is None:
        return ""
    cards = []
    marks: list[tuple[str, float, str]] = []
    if closed is not None:
        called, landed, diff = closed
        cards.append(
            "<div class='top-card'>"
            "<span>Last close</span>"
            "<div class='top-pair'>"
            f"<p><b>{_level_text(called)}</b><small>predicted</small></p>"
            f"<p><b>{_level_text(landed)}</b><small>Nifty was</small></p>"
            f"<p class='{impact_class(diff)}'><b>{impact_text(diff)}</b><small>diff</small></p>"
            "</div></div>"
        )
        marks.append(("Predicted", called, "#6b3fa0"))
        landed_color = {"plus": "#0c7a3a", "minus": "#c62828", "flat": "#5e584f"}[impact_class(diff)]
        marks.append(("Nifty", landed, landed_color))
    if opened is not None:
        level, due = opened
        at, on = _stamp_bits(due)
        cards.append(
            "<div class='top-card'>"
            "<span>Next open</span>"
            "<div class='top-pair'>"
            f"<p><b>{_level_text(level)}</b><small>{escape(at)} · {escape(on)}</small></p>"
            "</div></div>"
        )
        marks.append(("Open", level, "#1d4e89"))
    if gift_bits is not None:
        shown, extra, kind = gift_bits
        change = f"<small class='{kind}'>{escape(extra)}</small>" if extra else "<small>outside India</small>"
        cards.append(
            f"<div class='top-card'>"
            "<span>GIFT Nifty</span>"
            "<div class='top-pair'>"
            f"<p><b>{escape(shown)}</b>{change}</p>"
            "</div></div>"
        )
        if gift is not None and gift.get("price") is not None:
            marks.append(("GIFT", float(gift["price"]), "#b86e00"))
    plot = _glance_plot(marks) if len(marks) >= 2 else ""
    return (
        "<section class='topline' aria-label='Predictions at a glance'>"
        f"<div class='top-grid'>{''.join(cards)}</div>"
        f"{plot}</section>"
    )


def _last_closed(history: list[Ensemble]) -> tuple[float, float, float] | None:
    done = [
        row for row in history
        if row.horizon == "session" and row.nifty_level is not None and row.actual is not None
    ]
    if not done:
        return None
    row = max(done, key=lambda item: item.ts)
    called = row.nifty_level + row.mu
    landed = row.nifty_level + row.actual
    return called, landed, landed - called


def _next_open_call(history: list[Ensemble], open_call: Ensemble | None) -> tuple[float, datetime] | None:
    rows = [row for row in history if row.horizon == "open" and row.nifty_level is not None and row.actual is None]
    if open_call is not None and open_call.horizon == "open" and open_call.nifty_level is not None and open_call.actual is None:
        if all(row.id != open_call.id for row in rows):
            rows.append(open_call)
    if not rows:
        return None
    row = max(rows, key=lambda item: item.ts)
    return (row.nifty_level or 0) + row.mu, next_open(parse_ts(row.ts))


def _gift_bits(gift: dict | None) -> tuple[str, str, str] | None:
    if not gift or gift.get("price") is None:
        return None
    price = float(gift["price"])
    change = gift.get("change")
    shown = f"{price:,.0f}"
    if change is None:
        return shown, "", "flat"
    number = int(change) if float(change).is_integer() else change
    extra = impact_text(number) if isinstance(number, int) else f"{float(number):+.1f}"
    return shown, extra, impact_class(float(change))


def _glance_plot(marks: list[tuple[str, float, str]]) -> str:
    lo, hi = _call_bounds([value for _name, value, _color in marks])
    width, pad_x, baseline = 640, 16, 28
    span = hi - lo or 1

    def sx(value: float) -> float:
        return pad_x + (value - lo) / span * (width - 2 * pad_x)

    placed = [(name, sx(value), color, f"{name} {_level_text(value)}") for name, value, color in marks]
    spans = [_label_span(x, text, width) for _name, x, _color, text in placed]
    rows = _label_rows(spans)
    height = baseline + 18 + (max(rows) + 1) * 16 + 4
    parts = [
        f"<svg class='call-plot' viewBox='0 0 {width} {height}' role='img' aria-label='Predictions on one scale' "
        "style='font-family:ui-sans-serif,sans-serif'>"
        f"<line x1='{pad_x}' y1='{baseline}' x2='{width - pad_x}' y2='{baseline}' stroke='#e4ddd2' stroke-width='4' stroke-linecap='round'/>"
    ]
    by_name = {name: value for name, value, _color in marks}
    if "Predicted" in by_name and "Nifty" in by_name:
        left, right = sorted((sx(by_name["Predicted"]), sx(by_name["Nifty"])))
        color = next(item[2] for item in marks if item[0] == "Nifty")
        parts.append(
            f"<line x1='{left:.1f}' y1='{baseline}' x2='{right:.1f}' y2='{baseline}' stroke='{color}' stroke-width='4' stroke-linecap='round'/>"
        )
    for name, x, color, _text in placed:
        parts.append(f"<circle cx='{x:.1f}' cy='{baseline}' r='5' fill='{color}' stroke='#fff' stroke-width='1.5'/>")
    for (_name, _x, _color, text), (lx, anchor_name, _left, _right), row in zip(placed, spans, rows):
        y = baseline + 18 + row * 16
        parts.append(
            f"<text x='{lx:.1f}' y='{y}' text-anchor='{anchor_name}' font-size='11' fill='#1c1915'>{escape(text)}</text>"
        )
    parts.append("</svg>")
    return "".join(parts)


def _compare_html(ensemble: Ensemble | None, history: list[Ensemble], nifty: float | None = None) -> str:
    finished, forward = _settled_calls(ensemble, history)
    stories = []
    if finished is not None and finished.nifty_level is not None and finished.actual is not None:
        stories.append(f"<p class='story'>{_scored_call(finished)}</p>{_scored_plot(finished)}")
    if forward is not None and forward.nifty_level is not None:
        stories.append(f"<p class='story'>{_open_call(forward, nifty)}</p>{_open_plot(forward, nifty)}")
    if not stories:
        return ""
    body = "".join(stories)
    return (
        "<section class='compare' aria-label='Prediction against Nifty'>"
        "<h2>Prediction</h2>"
        "<p class='deck'>Last close first. Then the prediction still waiting.</p>"
        f"{body}"
        "</section>"
    )


def _scored_call(row: Ensemble) -> str:
    made = parse_ts(row.ts)
    due = session_close(made)
    anchor = row.nifty_level or 0
    predicted = anchor + row.mu
    observed = anchor + (row.actual or 0)
    made_at, made_on = _stamp_bits(made)
    due_at, due_on = _stamp_bits(due)
    return (
        f"Prediction was made when Nifty 50 was {_bold(_level_text(anchor))} "
        f"at {_bold(made_at)} on {_bold(made_on)}. "
        f"It predicted Nifty 50 would be {_bold(_level_text(predicted))} "
        f"at {_bold(due_at)} on {_bold(due_on)}. "
        f"Nifty 50 was {_bold(_level_text(observed))} then "
        f"({_deviation(observed - predicted)})."
    )


def _open_call(row: Ensemble, nifty: float | None) -> str:
    made = parse_ts(row.ts)
    due = session_close(made)
    anchor = row.nifty_level or 0
    predicted = anchor + row.mu
    made_at, made_on = _stamp_bits(made)
    due_at, due_on = _stamp_bits(due)
    sentence = (
        f"This prediction was made when Nifty 50 was {_bold(_level_text(anchor))} "
        f"at {_bold(made_at)} on {_bold(made_on)}. "
        f"It predicts Nifty 50 will be {_bold(_level_text(predicted))} "
        f"at {_bold(due_at)} on {_bold(due_on)}."
    )
    if nifty is None:
        return sentence
    return (
        f"{sentence} Live Nifty 50 is {_bold(_level_text(nifty))} "
        f"({_deviation(nifty - predicted, 'off so far')})."
    )


def _scored_plot(row: Ensemble) -> str:
    anchor = row.nifty_level or 0
    predicted = anchor + row.mu
    observed = anchor + (row.actual or 0)
    return _call_plot(anchor, predicted, observed, "Seen", "Last close")


def _open_plot(row: Ensemble, nifty: float | None) -> str:
    anchor = row.nifty_level or 0
    predicted = anchor + row.mu
    return _call_plot(anchor, predicted, nifty, "Live", "Still waiting")


def _call_plot(anchor: float, predicted: float, seen: float | None, seen_name: str, label: str) -> str:
    marks: list[tuple[str, float, str]] = [
        ("When", anchor, "#746c62"),
        ("Predicted", predicted, "#6b3fa0"),
    ]
    if seen is not None:
        marks.append((seen_name, seen, {"plus": "#0c7a3a", "minus": "#c62828", "flat": "#5e584f"}[impact_class(seen - predicted)]))
    lo, hi = _call_bounds([value for _name, value, _color in marks])
    width, pad_x, baseline = 640, 18, 22
    span = hi - lo or 1

    def sx(value: float) -> float:
        return pad_x + (value - lo) / span * (width - 2 * pad_x)

    placed = [(name, sx(value), color, f"{name} {_level_text(value)}") for name, value, color in marks]
    spans = [_label_span(x, text, width) for _name, x, _color, text in placed]
    rows = _label_rows(spans)
    height = baseline + 16 + (max(rows) + 1) * 16 + 6
    parts = [
        f"<svg class='call-plot' viewBox='0 0 {width} {height}' role='img' aria-label='{escape(label)}' "
        "style='font-family:ui-sans-serif,sans-serif'>"
        f"<line x1='{pad_x}' y1='{baseline}' x2='{width - pad_x}' y2='{baseline}' stroke='#e4ddd2'/>"
    ]
    if seen is not None:
        left, right = sorted((sx(predicted), sx(seen)))
        parts.append(
            f"<line x1='{left:.1f}' y1='{baseline - 8}' x2='{right:.1f}' y2='{baseline - 8}' "
            f"stroke='{marks[-1][2]}' stroke-width='1.5' stroke-dasharray='3 3'/>"
        )
    same = [x for _name, x, _color, _text in placed]
    for name, x, color, _text in placed:
        if name == "When" and sum(abs(x - other) < 1 for other in same) > 1:
            parts.append(f"<circle cx='{x:.1f}' cy='{baseline}' r='7' fill='none' stroke='{color}' stroke-width='2'/>")
        else:
            parts.append(f"<circle cx='{x:.1f}' cy='{baseline}' r='4' fill='{color}'/>")
    for (_name, _x, _color, text), (lx, anchor_name, _left, _right), row in zip(placed, spans, rows):
        y = baseline + 16 + row * 16
        parts.append(
            f"<text x='{lx:.1f}' y='{y}' text-anchor='{anchor_name}' font-size='11' fill='#1c1915'>{escape(text)}</text>"
        )
    parts.append("</svg>")
    return "".join(parts)


def _call_bounds(values: list[float]) -> tuple[float, float]:
    lo, hi = min(values), max(values)
    if hi - lo < 12:
        mid = (lo + hi) / 2
        lo, hi = mid - 6, mid + 6
    pad = (hi - lo) * 0.12
    return lo - pad, hi + pad


def _label_span(x: float, text: str, width: int) -> tuple[float, str, float, float]:
    half = len(text) * 3.3
    if x - half < 4:
        return 4, "start", 4, 4 + half * 2
    if x + half > width - 4:
        right = width - 4
        return right, "end", right - half * 2, right
    return x, "middle", x - half, x + half


def _label_rows(spans: list[tuple[float, str, float, float]]) -> list[int]:
    rows: list[list[tuple[float, float]]] = []
    assigned = [0] * len(spans)
    for index in sorted(range(len(spans)), key=lambda item: spans[item][2]):
        left, right = spans[index][2], spans[index][3]
        row = 0
        while row < len(rows) and any(right >= taken_left - 8 and left <= taken_right + 8 for taken_left, taken_right in rows[row]):
            row += 1
        if row == len(rows):
            rows.append([])
        rows[row].append((left, right))
        assigned[index] = row
    return assigned


def _stamp_bits(stamp: datetime) -> tuple[str, str]:
    return stamp.strftime("%H:%M"), stamp.strftime("%d %b")


def _bold(text: str) -> str:
    return f"<strong>{escape(text)}</strong>"


def _deviation(value: float, label: str = "off by") -> str:
    kind = impact_class(value)
    return f"{label} <strong class='{kind}'>{impact_text(value)}</strong>"


def _settled_calls(ensemble: Ensemble | None, history: list[Ensemble]) -> tuple[Ensemble | None, Ensemble | None]:
    rows = [row for row in history if row.horizon == "session" and row.nifty_level is not None]
    if ensemble is not None and ensemble.horizon == "session" and ensemble.nifty_level is not None:
        if all(row.id != ensemble.id for row in rows):
            rows.append(ensemble)
    rows.sort(key=lambda row: row.ts)
    finished_rows = [row for row in rows if row.actual is not None]
    waiting_rows = [row for row in rows if row.actual is None]
    finished = finished_rows[-1] if finished_rows else None
    forward = waiting_rows[-1] if waiting_rows else None
    if finished is not None and forward is not None and forward.ts < finished.ts:
        forward = None
    return finished, forward


def _ahead_html(ahead: dict | None) -> str:
    if not ahead:
        return ""
    move = float(ahead["move"])
    raw = [(str(label), float(value)) for label, value in ahead.get("parts") or []]
    shown = [int(round(value)) for _label, value in raw]
    if shown:
        shown[-1] += int(round(move)) - sum(shown)
    total = sum(shown)
    rows = []
    for (label, _value), points in zip(raw, shown):
        rows.append(
            "<div class='matter'>"
            f"<span class='name'>{escape(label)}</span>"
            f"<span class='impact ahead-point {impact_class(points)}'>{impact_text(points)}</span>"
            "</div>"
        )
    body = "\n".join(rows) or "<p class='due'>No drivers yet.</p>"
    due = escape(str(ahead.get("due") or ""))
    note = escape(str(ahead.get("note") or ""))
    note_html = f"<p class='due'>{note}</p>" if note else ""
    return (
        "<section class='ahead'>"
        f"<h2>Next close <span class='impact {impact_class(total)}' data-ahead='{total}'>{impact_text(total)}</span></h2>"
        f"<p class='due'>Due {due}</p>"
        f"{note_html}"
        "<p class='deck'>What is already in the next session’s move.</p>"
        f"{body}"
        "</section>"
    )


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
        f"<section><h2>Moving the prediction{_mover_total(moving)}</h2>"
        "<p class='deck'>Points these stories added to the prediction. Bigger numbers moved it more.</p>"
        f"{move_html}</section>"
        f"<section><h2>Quiet or stuck</h2>"
        "<p class='deck'>Amber is waiting. Red had no answer. Neither is in the number.</p>"
        f"{watch_html}</section>"
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
            f"<span class='line'>{escape(_plain(sentence))}</span>{points}</div>"
        )
    return "\n".join(html)


def _activity(events: list[Event], feeds: list[dict] | None = None) -> str:
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
    score_html = f"<p class='score'>{escape(_plain(score.sentence))}</p>" if score else ""
    trail = "\n".join(_trail_line(stamp, grouped[stamp]) for stamp in order[1:9])
    checked = _checked(latest)
    tone = "count" if checked == 8 else "count short"
    story = _call_story(latest, feeds)
    return (
        "<section class='roster'>"
        f"<div class='roster-head'><span>Agents</span><span class='{tone}'>{checked} of 8</span></div>"
        "<p class='deck'>This hour, then earlier hours. Each line says who answered and how the prediction was made.</p>"
        f"{_roster_rows(latest)}{score_html}<p class='how'>{escape(story)}</p>{trail}"
        "</section>"
    )


_LEARN_COLOR = {
    "Board": "#4a453e",
    "World": "#1d4e89",
    "Crude": "#b86e00",
    "Rupee": "#0f6e6e",
    "Policy": "#6b3fa0",
    "Flows": "#3d6b4f",
    "Weights": "#8a4b2f",
    "Options": "#5c6b7a",
    "Scout": "#3a6ea5",
}


def _news(families: list[tuple[str, int, float]]) -> str:
    heavier, lighter = news_shifts(families)
    if not heavier and not lighter:
        body = "<p class='deck wait'>Headline weights start after a story is checked.</p>"
    else:
        body = (
            "<div class='news-cols'>"
            f"{_news_col('Heavier', heavier)}"
            f"{_news_col('Lighter', lighter)}"
            "</div>"
        )
    return (
        "<section class='news' id='news'>"
        "<div class='roster-head'><span>News</span></div>"
        "<p class='deck'>Heavier means that kind of headline pulls the prediction harder than when it started. "
        "Lighter means those points were cut. The number is the points added or removed.</p>"
        f"{body}</section>"
    )


def _news_col(title: str, rows: list[dict]) -> str:
    kind = "heavier" if title == "Heavier" else "lighter"
    if not rows:
        lines = "<p class='quiet'>None yet.</p>"
    else:
        lines = "".join(
            f"<div class='news-row'><span class='name'>{escape(row['label'])}</span>"
            f"<span class='pts'>{row['points']}</span></div>"
            for row in rows
        )
    return f"<div class='news-col {kind}'><h2>{title}</h2>{lines}</div>"


def _learning(claims: list[Claim], ensembles: list[Ensemble]) -> str:
    series = agent_misses(claims, ensembles)
    names = [(BOARD_AGENT, "Board")] + list(ROSTER)
    cards = []
    waiting = []
    for key, name in names:
        row = _learn_row(name, series.get(key) or [])
        if row:
            cards.append(row)
        else:
            waiting.append(name)
    wait = ""
    if waiting:
        wait = f"<p class='deck wait'>Not enough scores for {escape(', '.join(waiting))}.</p>"
    banner = _gain_banner(series.get(BOARD_AGENT) or [])
    return (
        "<section class='learn' id='learning'>"
        "<div class='roster-head'><span>Improving</span></div>"
        "<p class='deck'>The line rises when later predictions miss by less. The grey line is 50, no change. "
        "Each card shows that score, then the points added to the next prediction. Above zero on the card, the agent has been too low.</p>"
        f"{banner}"
        f"<div class='learn-grid'>{''.join(cards)}</div>{wait}</section>"
    )


def _gain_kind(score: int) -> tuple[str, str]:
    if score > 50:
        return "Better", "up"
    if score < 50:
        return "Worse", "down"
    return "Same", "flat"


def _gain_banner(misses: list[float]) -> str:
    trail = learning_trail(misses, keep=48)
    if not trail:
        return "<p class='deck wait'>The board line starts after 4 checked predictions.</p>"
    word, kind = _gain_kind(trail[-1])
    return (
        "<div class='gain-banner'>"
        f"<p class='gain-read'><strong class='gain {kind}'>{trail[-1]}</strong> {word}</p>"
        f"{_gain_plot(trail)}</div>"
    )


def _gain_mark(misses: list[float]) -> str:
    score = learning_score(misses)
    if score is None:
        return "<span class='gain'></span>"
    _word, kind = _gain_kind(score)
    return f"<span class='gain {kind}'>{score}</span>"


def _learn_row(name: str, misses: list[float]) -> str:
    trail = shift_trail(misses, keep=48)
    if not trail:
        return ""
    shift = trail[-1]
    kind = "up" if shift > 0.5 else "down" if shift < -0.5 else ""
    color = _LEARN_COLOR.get(name, "#4a453e")
    return (
        f"<div class='learn-card'><span class='name'>{escape(name)}</span>"
        f"{_gain_mark(misses)}"
        f"<span class='line {kind}'>{impact_text(shift)}</span>"
        f"{_learn_plot(trail, color)}</div>"
    )


def _gain_scale(scores: list[int]) -> tuple[float, float]:
    lo = min(50.0, float(min(scores)))
    hi = max(50.0, float(max(scores)))
    if hi - lo < 20:
        mid = (lo + hi) / 2
        lo = min(lo, mid - 10)
        hi = max(hi, mid + 10)
    pad = (hi - lo) * 0.08
    return lo - pad, hi + pad


def _gain_plot(scores: list[int]) -> str:
    width, height = 640, 96
    pad_x, pad_y = 12, 14
    lo, hi = _gain_scale(scores)
    latest = scores[-1]
    color = "#0c7a3a" if latest > 50 else "#c62828" if latest < 50 else "#746c62"

    def sx(index: int) -> float:
        last = max(len(scores) - 1, 1)
        return pad_x + (width - 2 * pad_x) * index / last

    def sy(value: float) -> float:
        return pad_y + (1 - (value - lo) / (hi - lo)) * (height - 2 * pad_y)

    mid = sy(50)
    pts = [f"{sx(index):.1f},{sy(value):.1f}" for index, value in enumerate(scores)]
    end_x, end_y = sx(len(scores) - 1), sy(scores[-1])
    area = f"{sx(0):.1f},{mid:.1f} " + " ".join(pts) + f" {end_x:.1f},{mid:.1f}"
    return (
        f"<svg class='gain-plot' viewBox='0 0 {width} {height}' role='img' aria-label='Improving'>"
        f"<line x1='{pad_x}' y1='{mid:.1f}' x2='{width - pad_x}' y2='{mid:.1f}' stroke='#e4ddd2'/>"
        f"<polygon points='{area}' fill='{color}' fill-opacity='0.14'/>"
        f"<polyline fill='none' stroke='{color}' stroke-width='2' points='{' '.join(pts)}'/>"
        f"<circle cx='{end_x:.1f}' cy='{end_y:.1f}' r='3.5' fill='{color}'/>"
        f"</svg>"
    )


def _learn_plot(scores: list[float], color: str) -> str:
    width, height = 240, 72
    pad_x, pad_y = 10, 10
    lo, hi = -30.0, 30.0

    def sx(index: int) -> float:
        last = max(len(scores) - 1, 1)
        return pad_x + (width - 2 * pad_x) * index / last

    def sy(value: float) -> float:
        return pad_y + (1 - (value - lo) / (hi - lo)) * (height - 2 * pad_y)

    zero = sy(0)
    pts = [f"{sx(index):.1f},{sy(value):.1f}" for index, value in enumerate(scores)]
    end_x, end_y = sx(len(scores) - 1), sy(scores[-1])
    area = f"{sx(0):.1f},{zero:.1f} " + " ".join(pts) + f" {end_x:.1f},{zero:.1f}"
    return (
        f"<svg class='learn-plot' viewBox='0 0 {width} {height}' aria-hidden='true'>"
        f"<line x1='{pad_x}' y1='{zero:.1f}' x2='{width - pad_x}' y2='{zero:.1f}' stroke='#e4ddd2'/>"
        f"<polygon points='{area}' fill='{color}' fill-opacity='0.14'/>"
        f"<polyline fill='none' stroke='{color}' stroke-width='2' points='{' '.join(pts)}'/>"
        f"<circle cx='{end_x:.1f}' cy='{end_y:.1f}' r='3.5' fill='{color}'/>"
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


def _plain(text: str) -> str:
    return (
        text.replace("Scored the session call", "Checked the close prediction")
        .replace("Scored the open call", "Checked the open prediction")
        .replace("Scored the week call", "Checked the week prediction")
        .replace("Scored an open call", "Checked the open prediction")
        .replace("Missed the mean by", "Off by")
        .replace("Inside the curve.", "Inside the expected range.")
        .replace("no call has been scored", "no prediction has been checked")
        .replace("Calls from this hour cannot be scored.", "This hour’s predictions cannot be checked.")
        .replace("Its calls stayed biased.", "Its predictions stayed to one side.")
        .replace("No proof this cannot move Nifty.", "It may still move Nifty.")
        .replace("Not proved irrelevant.", "It may still move Nifty.")
        .replace("No proved direction, so no points.", "No clear up or down, so no points.")
        .replace("Spread ", "Range ")
    )


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
        f"<span class='line'>{escape(_plain(sentence))}</span>{points}</div>"
    )


def _trail_line(stamp: str, events: list[Event]) -> str:
    when = parse_ts(stamp).strftime("%H:%M")
    board = _by_agent(events).get(BOARD_AGENT)
    mean = "—"
    if board is not None and board.sentence not in STATUS_LINES:
        mean = impact_text(board.impact)
    summary = f"{when} · {_checked(events)} of 8 · prediction {mean}"
    return f"<p class='trail'>{escape(summary)}. {escape(_call_story(events))}</p>"


def _call_story(events: list[Event], feeds: list[dict] | None = None) -> str:
    found = _by_agent(events)
    moved = []
    quiet = []
    shut = []
    stuck = []
    for key, name in ROSTER:
        event = found.get(key)
        if event is None:
            continue
        sentence = event.sentence
        if sentence in MISSED_LINES or sentence == "No check":
            stuck.append(name)
        elif sentence == "Market shut":
            shut.append(name)
        elif sentence in STATUS_LINES:
            quiet.append(name)
        elif event.impact:
            moved.append(f"{name} added {impact_text(event.impact)}: {sentence.rstrip('.')}.")
        else:
            moved.append(f"{name} reported: {sentence.rstrip('.')}.")
    board = found.get(BOARD_AGENT)
    if board is not None and board.sentence not in STATUS_LINES:
        parts = [f"The prediction was {impact_text(board.impact)}."]
    else:
        parts = ["No prediction this hour."]
    parts.extend(moved)
    if quiet:
        parts.append(f"{_name_list(quiet)} was quiet." if len(quiet) == 1 else f"{_name_list(quiet)} were quiet.")
    if shut:
        parts.append(f"{_name_list(shut)} found the market shut.")
    if stuck:
        parts.append(f"{_name_list(stuck)} had no answer.")
    score = found.get(SCORE_AGENT)
    if score is not None:
        text = _plain(score.sentence).rstrip(".")
        parts.append(f"{text}.")
    boss = found.get(BOSS_AGENT)
    if boss is not None and not boss.sentence.startswith("Watching"):
        text = _plain(boss.sentence).rstrip(".")
        parts.append(f"{text}.")
    news = _feed_story(feeds)
    if news:
        parts.append(news)
    return " ".join(parts)


def _feed_story(feeds: list[dict] | None) -> str:
    if not feeds:
        return ""
    bits = []
    for row in feeds:
        label = str(row.get("label") or "").strip()
        if not label:
            continue
        lines = [str(line) for line in row.get("lines") or [] if str(line)]
        if lines:
            used = sum("In the call" in line or "In the prediction" in line or line.startswith("Kept,") or "Kept," in line for line in lines)
            aside = sum("not an event" in line or "cannot" in line or "heavyweights" in line or "cinema" in line or "lifestyle" in line for line in lines)
            bits.append(f"{label} read {len(lines)} stories. {used} kept. {aside} set aside.")
        else:
            detail = str(row.get("detail") or "").strip().rstrip(".")
            if detail:
                bits.append(f"{label}: {detail}.")
    return " ".join(bits)


def _name_list(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + " and " + names[-1]


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
    if text.startswith("Board ready") or text.startswith("Spread ") or text.startswith("Range "):
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
        return _empty_chart("No prediction this hour.")
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
        markers.append(("Average", book_mean, "#6b3fa0"))

    parts = [
        f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='Prediction' "
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
            f"<text x='{pad}' y='{baseline - 16}' fill='#746c62' font-size='12'>The band starts after two predictions.</text>"
        )
    for name, value, color in markers:
        x = sx(value)
        dash = " stroke-dasharray='3 3'" if name == "Average" else ""
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


def _error_chart(residuals: list[tuple[float, float]], history: list[Ensemble] | None = None) -> str:
    rows = _scored_for_chart(residuals, history or [])
    if len(rows) < 2:
        return "<svg viewBox='0 0 400 160'><text x='20' y='80' fill='#746c62'>No error curve yet.</text></svg>"
    return _error_readout(rows) + _error_svg(rows)


def _scored_for_chart(residuals: list[tuple[float, float]], history: list[Ensemble]) -> list[Ensemble]:
    scored = [row for row in history if row.residual is not None]
    scored.sort(key=lambda row: (row.ts, row.id))
    if len(scored) >= 2:
        return scored
    if len(residuals) < 2:
        return scored
    return [
        Ensemble(
            id=str(index),
            ts="",
            mu=0.0,
            sigma=sigma,
            n_shocks=0,
            nifty_level=None,
            actual=None,
            residual=residual,
        )
        for index, (residual, sigma) in enumerate(residuals)
    ]


def _error_readout(rows: list[Ensemble]) -> str:
    values = [float(row.residual or 0) for row in rows]
    mean = sum(values) / len(values)
    latest = values[-1]
    note = _same_close_note(rows)
    note_html = f"<p class='error-note'>{escape(note)}</p>" if note else ""
    return (
        "<p class='error-read'>"
        f"Average miss <strong class='{impact_class(mean)}'>{impact_text(mean)}</strong>. "
        f"{escape(_bias_phrase(mean))} {escape(_trend_phrase(values))}"
        f" Latest <strong class='{impact_class(latest)}'>{impact_text(latest)}</strong>."
        f"</p>{note_html}"
    )


def _bias_phrase(mean: float) -> str:
    points = abs(int(round(mean)))
    if points == 0:
        return "On average the prediction matched Nifty."
    side = "above" if mean < 0 else "below"
    return f"On average the prediction sat {points} points {side} Nifty."


def _trend_phrase(values: list[float]) -> str:
    if len(values) < 4:
        return ""
    cut = max(len(values) // 3, 1)
    early = sum(values[:cut]) / cut
    late = sum(values[-cut:]) / cut
    if abs(late) + 20 < abs(early):
        text = "Later predictions miss by less."
    elif abs(late) > abs(early) + 20:
        text = "Later predictions miss by more."
    else:
        text = "Later predictions miss by about the same."
    if early <= -10 and late >= 10:
        return "Later predictions now finish above Nifty."
    if early >= 10 and late <= -10:
        return "Later predictions now finish below Nifty."
    return text


def _same_close_note(rows: list[Ensemble]) -> str:
    levels = []
    for row in rows:
        if row.nifty_level is None or row.actual is None:
            continue
        levels.append(round(row.nifty_level + row.actual))
    if not levels:
        return ""
    top = max(set(levels), key=levels.count)
    count = levels.count(top)
    if count < 3 or count * 2 <= len(rows):
        return ""
    return f"{count} of these predictions were checked against one close, {_level_text(top)}."


def _miss_ticks(lo: float, hi: float) -> list[float]:
    span = hi - lo or 1
    step = 50 if span <= 280 else 100 if span <= 700 else 200
    start = math.ceil((lo - 1e-6) / step) * step
    ticks = []
    value = start
    while value <= hi + 1e-6:
        ticks.append(float(value))
        value += step
    if lo < 0 < hi and not any(abs(tick) < 1e-6 for tick in ticks):
        ticks.append(0.0)
        ticks.sort()
    return ticks


def _smooth_path(values: list[float]) -> list[float]:
    if len(values) < 3:
        return []
    path = []
    for index in range(len(values)):
        chunk = values[max(0, index - 1): index + 2]
        path.append(sum(chunk) / len(chunk))
    return path


def _miss_tip(row: Ensemble) -> str:
    when = ""
    if row.ts:
        when = parse_ts(row.ts).strftime("%d %b %H:%M") + ". "
    kind = "Open" if row.horizon == "open" else "Close"
    miss = impact_text(float(row.residual or 0))
    if row.nifty_level is None or row.actual is None:
        return f"{when}{kind}. Miss {miss}."
    call = row.nifty_level + row.mu
    done = row.nifty_level + row.actual
    return f"{when}{kind}. Predicted {_level_text(call)}. Nifty {_level_text(done)}. Miss {miss}."


def _error_svg(rows: list[Ensemble]) -> str:
    values = [float(row.residual or 0) for row in rows]
    mean = sum(values) / len(values)
    width, height = 440, 300
    pad_l, pad_r, pad_t, pad_b = 46, 36, 18, 72
    plot_top, plot_bottom = pad_t, height - pad_b
    lo = min(values + [0.0, mean])
    hi = max(values + [0.0, mean])
    pad = max((hi - lo) * 0.12, 12)
    lo -= pad
    hi += pad
    span = hi - lo or 1
    last = max(len(rows) - 1, 1)

    def sx(index: int) -> float:
        return pad_l + (width - pad_l - pad_r) * index / last

    def sy(value: float) -> float:
        return plot_top + (hi - value) / span * (plot_bottom - plot_top)

    label = f"Miss over time. Average {impact_text(mean)}. Latest {impact_text(values[-1])}."
    parts = [
        f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='{escape(label)}' "
        "style='font-family:ui-sans-serif,sans-serif'>"
    ]
    for tick in _miss_ticks(lo, hi):
        y = sy(tick)
        stroke = "#c4b8a8" if abs(tick) < 1e-6 else "#f3efe8"
        parts.append(f"<line x1='{pad_l}' y1='{y:.1f}' x2='{width - pad_r}' y2='{y:.1f}' stroke='{stroke}'/>")
        parts.append(
            f"<text x='{pad_l - 6}' y='{y + 3:.1f}' text-anchor='end' font-size='10' fill='#746c62'>{impact_text(tick)}</text>"
        )
    mean_y = sy(mean)
    parts.append(
        f"<line x1='{pad_l}' y1='{mean_y:.1f}' x2='{width - pad_r}' y2='{mean_y:.1f}' "
        "stroke='#6b3fa0' stroke-dasharray='4 3' stroke-width='1.5'/>"
    )
    close_index = [index for index, row in enumerate(rows) if row.horizon != "open"]
    path_index = close_index if len(close_index) >= 3 else list(range(len(values)))
    path = _smooth_path([values[index] for index in path_index])
    if path:
        pts = " ".join(f"{sx(path_index[index]):.1f},{sy(value):.1f}" for index, value in enumerate(path))
        parts.append(f"<polyline fill='none' stroke='#1c1915' stroke-width='2.5' points='{pts}'/>")
    avg_y = mean_y - 8
    if avg_y < plot_top + 11:
        avg_y = mean_y + 14
    parts.append(
        f"<text x='{width - pad_r}' y='{avg_y:.1f}' text-anchor='end' font-size='11' fill='#6b3fa0'>"
        f"avg {impact_text(mean)}</text>"
    )
    zero = sy(0)
    for index, row in enumerate(rows):
        value = values[index]
        color = "#0c7a3a" if value > 0.5 else "#c62828" if value < -0.5 else "#5e584f"
        x = sx(index)
        y = sy(value)
        tip = escape(_miss_tip(row))
        parts.append(
            f"<g><title>{tip}</title>"
            f"<line x1='{x:.1f}' y1='{zero:.1f}' x2='{x:.1f}' y2='{y:.1f}' stroke='{color}' stroke-width='2'/>"
            f"<circle cx='{x:.1f}' cy='{y:.1f}' r='4.5' fill='{color}' stroke='#fff' stroke-width='1.5'/>"
            f"</g>"
        )
        if row.horizon == "open":
            oy = y - 11
            if oy < plot_top + 9:
                oy = y + 14
            parts.append(f"<text x='{x:.1f}' y='{oy:.1f}' text-anchor='middle' font-size='9' fill='#746c62'>open</text>")
        if index == len(rows) - 1:
            parts.append(
                f"<text x='{x + 9:.1f}' y='{y + 3:.1f}' text-anchor='start' font-size='11' fill='{color}'>"
                f"{impact_text(value)}</text>"
            )
    if rows[0].ts:
        days: list[list] = []
        for index, row in enumerate(rows):
            stamp = parse_ts(row.ts)
            day = stamp.strftime("%d %b")
            y = plot_bottom + 14
            parts.append(
                f"<text x='{sx(index):.1f}' y='{y:.1f}' text-anchor='start' font-size='10' fill='#746c62' "
                f"transform='rotate(52 {sx(index):.1f} {y:.1f})'>{stamp.strftime('%H:%M')}</text>"
            )
            if not days or days[-1][0] != day:
                days.append([day, index, index])
            else:
                days[-1][2] = index
        for day, start, end in days:
            x = (sx(start) + sx(end)) / 2
            parts.append(
                f"<text x='{x:.1f}' y='{height - 8:.1f}' text-anchor='middle' font-size='11' fill='#4a453e'>{day}</text>"
            )
    if not rows[0].ts:
        placed = -1e9
        for index in range(len(rows)):
            x = sx(index)
            if index not in (0, len(rows) - 1) and x - placed < 34:
                continue
            parts.append(
                f"<text x='{x:.1f}' y='{plot_bottom + 16:.1f}' text-anchor='middle' font-size='10' fill='#746c62'>{index + 1}</text>"
            )
            placed = x
    parts.append("</svg>")
    return "".join(parts)
