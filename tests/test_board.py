from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from niftyteam.boss import agree_to_rescue, boss_sentence, crew_sentence, wake, watch_line
from niftyteam.chart import _mover_total, render_page
from niftyteam.config import impact_class, load_config
from niftyteam.ensemble import adjust_sigma, apply_score, attributed_points, build_ensemble, claim_weight, learned_midpoint, next_sigma_floor
from niftyteam.estimate import apply_family_bias, estimate_headline, family_bias, fit_move, fitted_move, gift_gap_estimate, headline_kind, judge_headline, level_estimate, news_shifts, oi_change_estimate, pcr_estimate, promoted_miss
from niftyteam.learn import call_shift, learning_score, learning_trail
from niftyteam.horizons import forecast_move, next_open, session_close, sessions_ahead, week_move
from niftyteam.models import Claim, Ensemble, Event, Source
from niftyteam.pcr import option_book, parse_flows
from niftyteam.scout import agent_line, parse_google_feed, parse_results, query_for, scout_sentence
from niftyteam.search import feed_items, parse_gift
from niftyteam.store import Store
from niftyteam.tick import _fold_feed, _make_claim, _publish, _report_limits, _rescue_news, _scout, _still_names, accuracy_notes, items_for_feed, miss_titles

IST = ZoneInfo("Asia/Kolkata")


def _source(source_id="et-markets", kind="rss", n=0, weight=0.4, status="active"):
    return Source(id=source_id, beat="flows", kind=kind, url="https://example.com", status=status, weight=weight, n_scored=n)


def _claim(title, url, shock, midpoint, source_id="et-markets", low=20, high=60, confidence=0.4):
    now = datetime(2026, 10, 18, 15, tzinfo=IST)
    return Claim(
        id=url,
        beat="flows",
        source_id=source_id,
        ts=now.isoformat(),
        headline=title,
        url=url,
        shock_key=shock,
        direction="down" if midpoint < 0 else "up",
        points_low=low,
        points_high=high,
        midpoint=midpoint,
        confidence=confidence,
        nifty_level=25000,
        score_after=(now + timedelta(hours=24)).isoformat(),
        status="open",
    )


def test_skip_opinion_and_penny():
    assert estimate_headline("Can Nifty, Sensex rally further or will bears reign in?") is None
    assert estimate_headline("10 penny stocks plunge up to 75% in six months") is None
    assert estimate_headline("Jefferies’ Chris Wood says it’s time to diversify") is None


def test_fii_selling_and_heavyweight_profit():
    sold = estimate_headline("FPI selling crosses Rs 52,000 crore in October as Nifty defies foreign exodus")
    assert sold["direction"] == "down"
    assert sold["shock_key"] == "flows:down"
    bank = estimate_headline("ICICI Bank profit spurts 20% on NII; core profitability a tad lower")
    assert bank["direction"] == "up"
    assert bank["shock_key"] == "weights:ICICI Bank:up"
    assert estimate_headline("Axis Bank Q2 profit up 38% on loan growth") is None
    assert estimate_headline("3 Tanker Stocks Retail Investors Are Watching For Higher Oil Shipping Rates") is None


def test_duplicate_url_and_same_shock_nets_once(tmp_path):
    store = Store(tmp_path / "board.sqlite")
    store.seed_sources([{"id": "et-markets", "beat": "flows", "kind": "rss", "url": "https://et.example/rss"}])
    store.seed_sources([{"id": "mint", "beat": "flows", "kind": "rss", "url": "https://mint.example/rss"}])
    first = _claim("FPI selling crosses 52000 crore", "https://et.example/a", "flows:down", -50)
    again = _claim("FPI selling crosses 52000 crore", "https://et.example/a", "flows:down", -50)
    other = _claim("FPIs pull out 52100 cr", "https://mint.example/b", "flows:down", -40, source_id="mint")
    up = _claim("HDFC profit", "https://et.example/c", "weights:HDFC Bank:up", 20, source_id="et-markets")
    assert store.add_claim(first) is True
    assert store.add_claim(again) is False
    assert store.add_claim(other) is True
    assert store.add_claim(up) is True
    sources = {row.id: row for row in store.sources()}
    built = build_ensemble([first, other, up], sources, sigma_floor=10)
    assert built["n_shocks"] == 2
    assert built["mu"] < 0
    store.close()


def test_random_domain_stays_a_proposal(tmp_path):
    store = Store(tmp_path / "board.sqlite")
    assert store.remember_link("random-blog.example", "https://random-blog.example/x", "proposal") is True
    assert store.remember_link("random-blog.example", "https://random-blog.example/x", "proposal") is False
    assert "random-blog.example" not in {row.domain for row in store.sources()}
    added = store.add_probation_source("www.livemint.com", "https://www.livemint.com/rss/x", "flows")
    assert added is True
    minted = [row for row in store.sources() if row.domain == "www.livemint.com"][0]
    assert minted.status == "probation"
    claim = _claim("Oil jumps", "https://www.livemint.com/story", "crude:down", -60, source_id=minted.id)
    built = build_ensemble([claim], {minted.id: minted}, sigma_floor=10)
    assert built is not None
    assert built["mu"] == pytest.approx(-60)
    store.close()


def test_score_updates_weight_and_chart_colors():
    source = _source(n=29, weight=1)
    source.residual_sum = 29 * 40
    note = apply_score(source, residual=40, book_std=10)
    assert source.n_scored == 30
    assert source.status == "retired"
    assert note is not None
    floor = next_sigma_floor(30, [False] * 30)
    assert floor > 30
    tight = next_sigma_floor(30, [True] * 30)
    assert tight < 30
    stamp = datetime.now(IST).replace(microsecond=0)
    current = Ensemble(id="e", ts=stamp.isoformat(), mu=-35, sigma=22, n_shocks=2, nifty_level=25000)
    history = [
        Ensemble(id=str(i), ts=(stamp - timedelta(days=i + 1)).isoformat(), mu=0, sigma=10, n_shocks=1, nifty_level=level)
        for i, level in enumerate((24000, 24200, 24400, 24600, 24800))
    ]
    history.append(current)
    history.append(
        Ensemble(id="old", ts=(stamp - timedelta(days=400)).isoformat(), mu=0, sigma=10, n_shocks=1, nifty_level=10000)
    )
    page = render_page(
        current,
        [],
        [
            Event(1, stamp.isoformat(), "Oil jumps", -60, agent="crude"),
            Event(2, stamp.isoformat(), "Asia higher", 20, agent="global"),
            Event(3, stamp.isoformat(), "Quiet", 0, agent="fx"),
            Event(4, stamp.isoformat(), "Quiet", 0, agent="policy"),
            Event(5, stamp.isoformat(), "Quiet", 0, agent="flows"),
            Event(6, stamp.isoformat(), "No answer", 0, agent="weights"),
            Event(7, stamp.isoformat(), "Market shut", 0, agent="pcr"),
            Event(8, stamp.isoformat(), "Scout looked across the web. 2 new stories, 1 new source.", 0, agent="scout"),
            Event(9, stamp.isoformat(), "Spread 22", -35, agent="board"),
            Event(10, stamp.isoformat(), "Scored an open call. Nifty fell 12.", -12, agent="score"),
            Event(11, (stamp - timedelta(hours=1)).isoformat(), "Quiet", 0, agent="global"),
            Event(12, (stamp - timedelta(hours=1)).isoformat(), "Spread 10", 8, agent="board"),
            Event(13, stamp.isoformat(), "Watching. Every agent is working.", 0, agent="boss"),
        ],
        25000,
        0,
        stamp.isoformat(),
        {"price": 23085, "change": -9.5},
        1166,
        history=history,
    )
    assert "GIFT Nifty" in page
    assert "23,085" in page
    forecast = page.split("aria-label='Prediction'", 1)[1].split("</svg>", 1)[0]
    assert "Spot 25,000" in forecast
    assert "GIFT 23,085" in forecast
    assert "Next -35" in forecast
    assert "Average 24,494" in forecast
    assert "10,000" not in forecast
    assert "stroke='#0c7a3a'" in forecast
    assert "stroke='#b86e00'" in forecast
    assert "stroke='#1d4e89'" in forecast
    assert "stroke='#6b3fa0'" in forecast
    assert "200-day average" in page
    assert "previous three" in page
    assert "stroke-opacity='0.18'" in forecast
    assert "stroke-opacity='0.35'" in forecast
    assert "stroke-opacity='0.55'" in forecast
    assert "stroke='#6b3fa0' stroke-width='2' points=" in forecast
    assert "Not enough scores" in page
    assert "FII net" in page
    assert "+1,166 cr" in page
    assert "class='impact minus'>-60" in page
    assert "class='impact plus'>+20" in page
    assert "<h2>Moving the prediction<span class='impact minus'>-40</span></h2>" in page
    assert impact_class(0) == "flat"
    assert "class='light on'" in page
    assert f"Last run {stamp.strftime('%d %b %H:%M')}" in page
    assert "7 of 8" in page
    assert "Scout looked across the web." in page
    assert "Market shut" in page
    assert "Oil jumps" in page
    assert "Range 22" in page
    assert "Checked the open prediction." in page
    assert "Needs a look" not in page
    assert "Watching. Every agent is working." in page
    assert "The prediction was -35." in page
    assert "Crude added -60: Oil jumps." in page
    assert "World added +20: Asia higher." in page
    assert "Rupee, Policy and Flows were quiet." in page
    assert "Options found the market shut." in page
    assert "Weights had no answer." in page
    assert f"{(stamp - timedelta(hours=1)).strftime('%H:%M')} · 1 of 8 · prediction +8" in page
    assert "The prediction was +8." in page


def test_called_level_sits_beside_the_live_nifty():
    done = Ensemble(
        id="old", ts="2026-10-16T10:00:00+05:30", mu=40, sigma=20, n_shocks=2, nifty_level=24800, actual=10,
    )
    call = Ensemble(id="e", ts="2026-10-19T10:00:00+05:30", mu=15, sigma=20, n_shocks=1, nifty_level=24900)
    page = render_page(call, [], [], 24910, 0, history=[done, call])
    card = page.split("aria-label='Prediction against Nifty'", 1)[1].split("</section>", 1)[0]
    assert "Prediction was made when Nifty 50 was" in card
    assert "24,800" in card
    assert "at <strong>10:00</strong> on <strong>16 Oct</strong>" in card
    assert "would be" in card
    assert "24,840" in card
    assert "at <strong>15:30</strong> on <strong>16 Oct</strong>" in card
    assert "Nifty 50 was <strong>24,810</strong> then" in card
    assert "24,810" in card
    assert "off by <strong class='minus'>-30</strong>" in card
    assert "This prediction was made when Nifty 50 was" in card
    assert "24,900" in card
    assert "at <strong>10:00</strong> on <strong>19 Oct</strong>" in card
    assert "will be" in card
    assert "24,915" in card
    assert "at <strong>15:30</strong> on <strong>19 Oct</strong>" in card
    assert "Live Nifty 50 is" in card
    assert "24,910" in card
    assert "off so far <strong class='minus'>-5</strong>" in card
    assert "aria-label='Last close'" in card
    assert "aria-label='Still waiting'" in card
    assert "When 24,800" in card
    assert "Predicted 24,840" in card
    assert "Seen 24,810" in card
    assert "When 24,900" in card
    assert "Predicted 24,915" in card
    assert "Live 24,910" in card
    assert "stroke='#c62828'" in card
    pending = render_page(call, [], [], None, 0)
    assert "will be" in pending
    assert "24,915" in pending
    assert "Live Nifty 50 is" not in pending
    assert " then (" not in pending
    open_plot = pending.split("aria-label='Still waiting'", 1)[1].split("</svg>", 1)[0]
    assert "When 24,900" in open_plot
    assert "Predicted 24,915" in open_plot
    assert "Live " not in open_plot
    blank = render_page(None, [], [], 24810, 0)
    assert "Prediction was made" not in blank


def test_topline_puts_the_last_close_next_open_and_gift_first():
    done = Ensemble(
        id="old", ts="2026-10-16T10:00:00+05:30", mu=40, sigma=20, n_shocks=2, nifty_level=24800, actual=10,
    )
    opened = Ensemble(
        id="op", ts="2026-10-19T16:00:00+05:30", mu=25, sigma=10, n_shocks=1,
        nifty_level=24810, horizon="open",
    )
    page = render_page(
        None, [], [], 24810, 1, gift={"price": 24900, "change": 15}, history=[done], open_call=opened,
    )
    top = page.split("aria-label='Predictions at a glance'", 1)[1].split("</section>", 1)[0]
    assert top.index("Last close") < top.index("Next open") < top.index("GIFT Nifty")
    assert "24,840" in top
    assert "24,810" in top
    assert ">-30<" in top or "-30" in top
    assert "24,835" in top
    assert "09:15" in top
    assert "20 Oct" in top
    assert "24,900" in top
    assert "+15" in top
    assert "Predicted 24,840" in top
    assert "Nifty 24,810" in top
    assert "Open 24,835" in top
    assert "GIFT 24,900" in top


def test_mover_total_sums_the_shown_numbers():
    rows = [
        ("World", "Gold", "ok", -47.6),
        ("Crude", "Oil", "ok", 40.4),
        ("Rupee", "USD", "ok", 5.4),
        ("Policy", "Quiet", "idle", 9.6),
    ]
    assert _mover_total(rows) == "<span class='impact minus'>-3</span>"


def test_hard_day_families():
    hormuz = estimate_headline("Missile war raises fear of a Hormuz blockade")
    assert hormuz["shock_key"] == "world:crude:down"
    assert estimate_headline("Federal Reserve shock hits markets")["shock_key"] == "world:global:down"
    assert estimate_headline("S&P slides on a global selloff")["shock_key"] == "world:global:down"
    assert hormuz["direction"] == "down"
    cyclone = estimate_headline("Severe cyclone nears the Gujarat coast")
    assert cyclone["shock_key"] == "calamity:cyclone"
    assert cyclone["beat"] == "crude"
    buy = estimate_headline("Reliance announces a share buyback")
    assert buy["shock_key"] == "weights:Reliance:buyback"
    assert estimate_headline("A small firm declares a dividend") is None
    assert estimate_headline("Reliance board declares a dividend")["shock_key"] == "weights:Reliance:dividend"
    assert estimate_headline("Scientists announce a battery discovery") is None
    found = estimate_headline("Reliance strikes oil in a new discovery")
    assert found["shock_key"] == "find:Reliance"
    assert found["horizon"] == "week"
    merger = estimate_headline("HDFC Bank in talks for a merger")
    assert merger["horizon"] == "week"
    assert merger["shock_key"] == "weights:HDFC Bank:merger"


def test_three_shocks_keep_the_crash():
    sources = {f"s{i}": _source(f"s{i}") for i in range(4)}
    claims = [
        _claim("a", "https://a", "world:crude:down", -40, source_id="s0"),
        _claim("b", "https://b", "world:global:down", -30, source_id="s1"),
        _claim("c", "https://c", "calamity:cyclone", -25, source_id="s2"),
        _claim("d", "https://d", "fx:up", 5, source_id="s3"),
    ]
    built = build_ensemble(claims, sources, sigma_floor=10)
    assert built["mu"] < -20
    assert built["sigma"] >= abs(built["mu"]) * 0.6 - 0.01


def test_family_bias_shifts_the_next_claim():
    guess = {"midpoint": -40, "points_high": 60, "confidence": 0.4, "shock_key": "world:crude:down"}
    shifted = apply_family_bias(guess, 4, 40)
    assert shifted["midpoint"] == pytest.approx(-35)
    assert family_bias(4, 40) == pytest.approx(5)


def test_news_shifts_split_heavier_from_lighter():
    heavier, lighter = news_shifts([
        ("world:global:down", 3, -600),
        ("crude:up", 10, -2000),
        ("calamity:earthquake", 1, 55),
        ("level:brent", 4, -200),
        ("fx:up", 1, 0),
    ])
    assert heavier[0] == {"label": "War and sanctions", "points": 30}
    assert {"label": "Oil easing", "points": 30} in lighter
    assert {"label": "Earthquake", "points": 11} in lighter
    assert all(row["label"] != "Brent" for row in heavier + lighter)
    page = render_page(None, [], [], 25000, 8, families=[("policy:down", 2, -400), ("crude:up", 10, -2000)])
    block = page.split("id='news'", 1)[1].split("</section>", 1)[0]
    assert "RBI tightening" in block.split(">Lighter<", 1)[0]
    assert "Oil easing" in block.split(">Lighter<", 1)[1]
    assert "Headline weights start after a story is checked." in render_page(None, [], [], None, 0)


def test_error_is_split_and_reused():
    points = attributed_points([(-40, 1), (-20, 1)], mu=-30, actual=-50)
    assert points == pytest.approx([-50, -30])
    assert learned_midpoint(-40, 4, sum(points[:1]) * 4) == pytest.approx(-45)
    assert forecast_move([("2026-10-19", 24880, 25000)], "2026-10-19", 25000) == pytest.approx(-120)
    assert adjust_sigma(30, 10, [(1, 4)]) == pytest.approx(34.5)
    assert adjust_sigma(30, 10, [(4, 1)]) == pytest.approx(27)
    kind = headline_kind("Cyclone shuts the Gujarat coast")
    assert promoted_miss("Cyclone shuts the Gujarat coast", []) is None
    again = promoted_miss("Cyclone shuts the Gujarat coast", [(kind, -1)])
    assert again["shock_key"] == f"miss:{kind}"
    assert again["direction"] == "down"
    assert promoted_miss("Cyclone shuts the Gujarat coast", [(kind, -1), (kind, 1)]) is None


def test_family_slope_after_30_pairs(tmp_path):
    store = Store(tmp_path / "board.sqlite")
    for _ in range(30):
        store.add_family_pair("world:crude:down", 10, -20)
    assert fitted_move(store.family_pairs("world:crude:down"), 10, -65) == pytest.approx(-20)
    store.close()


def test_week_score_waits_five_sessions():
    stamp = datetime(2026, 10, 18, 10, tzinfo=IST)
    due = sessions_ahead(stamp)
    assert due.isoformat().startswith("2026-10-23")
    assert week_move([("2026-10-23", 25100, 25020)], "2026-10-23", 25000) == pytest.approx(100)
    assert miss_titles(-80, 30, ["Cyclone headline", ""]) == ["Cyclone headline"]
    assert miss_titles(-10, 30, ["Quiet headline"]) == []


def test_two_beats_one_shock_one_mean():
    oil = _source("et-crude")
    world = _source("yahoo-gspc")
    a = _claim("Crude oil jumps", "https://a", "crude:down", -70, source_id="et-crude", low=40, high=80)
    b = _claim("Oil jumps on the same shock", "https://b", "crude:down", -50, source_id="yahoo-gspc", low=40, high=80)
    built = build_ensemble([a, b], {"et-crude": oil, "yahoo-gspc": world}, sigma_floor=10)
    assert built["n_shocks"] == 1
    assert built["mu"] == pytest.approx(-60)


def test_scout_runs_when_other_beats_do_not(tmp_path, monkeypatch):
    store = Store(tmp_path / "board.sqlite")
    page = """
    <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.reddit.com%2Fr%2Fnews">FPI selling crosses Rs 52000 crore</a>
    <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fnews.example%2Ffpi">FPI selling crosses Rs 52,000 crore in October</a>
    """
    monkeypatch.setattr("niftyteam.tick.search_web", lambda client, query: parse_results(page))
    claims, failed, line = _scout(store, datetime(2026, 10, 18, 3, tzinfo=IST), 25000)
    assert failed is False
    assert len(claims) == 1
    assert "1 new story, 1 new source" in line
    assert any("1 new story, 1 new source" in event.sentence for event in store.events(5))
    assert agent_line({"scout"}) == "1 agent worked this update."
    assert query_for(0) != query_for(1)
    minted = [row for row in store.sources() if row.domain == "news.example"]
    assert minted[0].status == "probation"
    assert minted[0].kind == "web"
    assert scout_sentence(0, 0, failed=True).startswith("Scout looked")
    store.close()


def _chain():
    def row(expiry, put_oi, call_oi, put_chg, call_chg):
        return {
            "expiryDate": expiry,
            "PE": {"openInterest": put_oi, "changeinOpenInterest": put_chg},
            "CE": {"openInterest": call_oi, "changeinOpenInterest": call_chg},
        }

    return {
        "records": {
            "expiryDates": ["20-Oct-2026", "27-Oct-2026", "24-Nov-2026"],
            "data": [
                row("20-Oct-2026", 200, 100, 80000, 20000),
                row("27-Oct-2026", 300, 100, 10000, 40000),
                row("24-Nov-2026", 50, 100, 0, 0),
            ],
        }
    }


def test_week_and_month_pcr_and_option_change():
    book = option_book(_chain(), "2026-10-18")
    assert book["week"]["expiry"] == "20-Oct-2026"
    assert book["week"]["oi_pcr"] == pytest.approx(2.0)
    assert book["month"]["expiry"] == "27-Oct-2026"
    assert book["month"]["oi_pcr"] == pytest.approx(3.0)
    assert book["same_expiry"] is False
    week = pcr_estimate(0.08, 0.05, 0, "Weekly put-call ratio", "pcr:week")
    month = pcr_estimate(-0.06, 0.05, 0, "Monthly put-call ratio", "pcr:month")
    shifted = oi_change_estimate(60000, 0, 0)
    assert week["shock_key"] == "pcr:week:up"
    assert "Weekly put-call ratio rose" in week["body"]
    assert month["shock_key"] == "pcr:month:down"
    assert "Monthly put-call ratio fell" in month["body"]
    assert shifted["shock_key"] == "pcr:oi:up"
    assert "more puts" in shifted["body"]
    later = option_book(_chain(), "2026-11-01")
    assert later["week"]["expiry"] == "24-Nov-2026"
    assert later["same_expiry"] is True


def test_accuracy_notes_cover_gaps():
    notes = accuracy_notes(
        nifty=None,
        news_answered=False,
        news_claims=0,
        scout_failed=True,
        chain_state="shut",
        fii_failed=True,
        down_ids=["yahoo-crude"],
        scored=False,
    )
    text = " ".join(notes)
    assert "Nifty price is missing" in text
    assert "no feed answered" in text
    assert "web search did not answer" in text
    assert "market is shut" in text
    assert "FII flow did not answer" in text
    assert "yahoo-crude" in text
    assert "no prediction has been checked" in text
    quiet = accuracy_notes(
        nifty=25000,
        news_answered=True,
        news_claims=0,
        scout_failed=False,
        chain_state="ok",
        fii_failed=False,
        down_ids=[],
        scored=True,
    )
    assert quiet == ["News agents: no story was strong enough to score."]


def test_quiet_tick_does_not_fill_the_log(tmp_path):
    store = Store(tmp_path / "board.sqlite")
    stamp = datetime(2026, 10, 18, 19, tzinfo=IST)
    _publish(store, {}, [], stamp, 25000, {"scout", "flows"})
    _report_limits(
        store,
        stamp,
        nifty=25000,
        news_answered=True,
        news_claims=0,
        scout_failed=False,
        chain_state="shut",
        fii_failed=False,
        scored=False,
    )
    assert store.events() == []
    assert store.meta("agents") == "2"
    assert "market is shut" in (store.meta("issues") or "")
    store.close()


def test_gift_uses_near_month_future():
    quote = parse_gift({
        "data": [
            {"INSTRUMENTTYPE": "FUTIDX", "SYMBOL": "NIFTY", "EXPIRYDATE": "27-Oct-2026", "LASTPRICE": "23085.00", "DAYCHANGE_1": -9.5},
            {"INSTRUMENTTYPE": "FUTIDX", "SYMBOL": "NIFTY", "EXPIRYDATE": "27-Oct-2026", "LASTPRICE": "23085.00", "DAYCHANGE_1": -9.5},
            {"INSTRUMENTTYPE": "FUTIDX", "SYMBOL": "NIFTY", "EXPIRYDATE": "23-Nov-2026", "LASTPRICE": "23126.00", "DAYCHANGE_1": -52.5},
        ]
    })
    assert quote["price"] == 23085
    assert quote["expiry"] == "27-Oct-2026"
    assert quote["change"] == -9.5


def test_learning_score_follows_the_later_miss():
    closer = [10, 10, 10, 10, 2, 2, 2, 2]
    worse = [2, 2, 2, 2, 10, 10, 10, 10]
    assert learning_score(closer[:3]) is None
    assert learning_score(closer) > 50
    assert learning_score(worse) < 50
    assert learning_trail(closer)[-1] == learning_score(closer)
    assert len(learning_trail(closer + closer)) <= 8


def test_open_and_session_clocks():
    sunday = datetime(2026, 10, 18, 19, tzinfo=IST)
    assert next_open(sunday) == datetime(2026, 10, 19, 9, 15, tzinfo=IST)
    assert session_close(sunday) == datetime(2026, 10, 19, 15, 30, tzinfo=IST)
    monday = datetime(2026, 10, 19, 10, tzinfo=IST)
    assert session_close(monday) == datetime(2026, 10, 19, 15, 30, tzinfo=IST)
    assert next_open(monday) == datetime(2026, 10, 20, 9, 15, tzinfo=IST)


def test_gift_gap_is_the_open_call():
    guess = gift_gap_estimate(23085 - 23146)
    assert guess["horizon"] == "open"
    assert guess["shock_key"] == "gift:gap"
    assert guess["midpoint"] == pytest.approx(-61)


def test_dii_row_is_kept():
    flows = parse_flows([
        {"category": "FII/FPI", "netValue": "1,166.25"},
        {"category": "DII", "netValue": "-420.50"},
    ])
    assert flows["fii"] == pytest.approx(1166.25)
    assert flows["dii"] == pytest.approx(-420.50)


def test_fitted_band_after_30_pairs():
    pairs = [(2.0, -16.0) for _ in range(30)]
    assert fitted_move(pairs[:29], 2.0, -4.0) == pytest.approx(-4.0)
    assert fitted_move(pairs, 2.0, -4.0) == pytest.approx(-16.0)
    guess = level_estimate("brent", 2.0, pairs)
    assert guess["horizon"] == "session"
    assert guess["driver"] == 2.0
    assert guess["midpoint"] == pytest.approx(-16.0)


def test_google_news_keeps_the_publisher():
    page = """
    <rss><channel>
      <item>
        <title>FPI selling crosses Rs 52,000 crore - Example News</title>
        <link>https://news.google.com/rss/articles/abc</link>
        <source url="https://news.example/fpi">Example News</source>
      </item>
      <item>
        <title>Only a wrapper</title>
        <link>https://news.google.com/rss/articles/nope</link>
        <source url="https://news.google.com/rss/articles/nope">Google News</source>
      </item>
    </channel></rss>
    """
    rows = parse_google_feed(page)
    assert len(rows) == 1
    assert rows[0]["domain"] == "news.example"
    assert "news.google.com" not in rows[0]["url"]


def test_boss_restarts_a_stopped_agent(tmp_path):
    store = Store(tmp_path / "board.sqlite")
    store.seed_sources([
        {"id": "yahoo-crude", "beat": "crude", "kind": "rss", "url": "https://example.com/oil"},
        {"id": "nse-pcr", "beat": "pcr", "kind": "pcr", "url": "https://example.com/pcr"},
    ])
    crude = store.source("yahoo-crude")
    crude.status = "down"
    crude.weight = 0
    crude.fail_streak = 4
    store.save_source(crude)
    options = store.source("nse-pcr")
    options.status = "retired"
    options.weight = 0
    options.n_scored = 30
    store.save_source(options)
    assert wake(store) == ["Crude"]
    crude = store.source("yahoo-crude")
    assert crude.status == "active"
    assert crude.weight == 0.4
    assert crude.fail_streak == 0
    options = store.source("nse-pcr")
    assert options.status == "retired"
    assert options.weight == 0
    assert boss_sentence([], []) == "Watching. Every agent is working."
    assert boss_sentence(["Crude"], []) == "Restarted Crude. Working again."
    assert boss_sentence(["Crude"], ["Crude"]) == "Restarted Crude. Still stuck."
    assert boss_sentence(["World", "Options"], ["Options"]) == "Restarted World and Options. Options still stuck."
    store.close()


def test_two_agents_agree_before_the_boss_is_restarted():
    stuck = "Restarted Crude. Still stuck."
    working = {
        "World": "Asia higher",
        "Crude": "No answer",
        "Rupee": "Quiet",
        "Policy": "Market shut",
        "Flows": "Feed down",
        "Weights": "No answer",
        "Options": "No answer",
        "Scout": "Search failed",
    }
    assert agree_to_rescue("Watching. Every agent is working.", working) == []
    assert agree_to_rescue(stuck, {"World": "Asia higher"}) == ["World"]
    assert watch_line(stuck, ["World"]) == "Restarted Crude. Still stuck. World is watching the boss."
    assert agree_to_rescue(stuck, working) == ["World"]
    reports = dict(working)
    reports["Rupee"] = "Rupee slides"
    reports["Scout"] = "Scout looked across the web. 1 new story, 1 new source."
    voters = agree_to_rescue(stuck, reports)
    assert voters == ["World", "Rupee", "Scout"]
    assert crew_sentence(voters, ["Crude"]) == "Restarted by World, Rupee, and Scout. Still stuck."
    assert crew_sentence(["World", "Rupee"], []) == "Restarted by World and Rupee. Working again."


def test_brent_headline_does_not_hide_a_down_crude_feed(tmp_path, monkeypatch):
    store = Store(tmp_path / "board.sqlite")
    stamp = datetime(2026, 10, 18, 12, tzinfo=IST)
    feed = {"crude": ("Feed down", 0), "global": ("Quiet", 0)}
    seen = {}

    def fake_news(store, config, stamp, nifty, soften=False, only=None):
        seen["only"] = set(only or ())
        return [], set(), {"crude": ("Oil jumps", -40)}

    monkeypatch.setattr("niftyteam.tick._news", fake_news)
    _claims, _worked, lines, restarted = _rescue_news(
        store, {}, stamp, 25000, False, [], set(), dict(feed), [], {"crude"},
    )
    assert seen["only"] == {"crude"}
    assert lines["crude"][0] == "Oil jumps"
    assert "Crude" in restarted
    assert "Crude" in _still_names(store, feed, [], "shut", [], set(), False, "Quiet", False, False)
    display = {"crude": ("Brent rose 1.20 since the last print.", -12)}
    _fold_feed(display, feed)
    assert display["crude"][0] == "Feed down"
    store.close()


def test_a_live_print_is_not_replaced_by_the_old_average(tmp_path):
    store = Store(tmp_path / "board.sqlite")
    for _ in range(8):
        store.add_family_points("gift:gap", -5)
        store.add_family_pair("gift:gap", -40, -5)
    stamp = datetime(2026, 10, 18, 12, tzinfo=IST)
    claim = _make_claim(_source("gift"), gift_gap_estimate(-80), "gift:1", stamp, 25000, store)
    assert claim.driver == pytest.approx(-80)
    assert claim.midpoint == pytest.approx(-80)
    store.close()


def test_thirty_clean_pairs_scale_the_next_print(tmp_path):
    store = Store(tmp_path / "board.sqlite")
    for _ in range(30):
        store.add_family_pair("gift:gap", -40, -20, clean=True)
    stamp = datetime(2026, 10, 18, 12, tzinfo=IST)
    claim = _make_claim(_source("gift"), gift_gap_estimate(-80), "gift:1", stamp, 25000, store)
    assert claim.midpoint == pytest.approx(-40)
    store.close()


def test_old_attributed_pairs_do_not_set_the_slope(tmp_path):
    store = Store(tmp_path / "board.sqlite")
    for _ in range(30):
        store.add_family_pair("gift:gap", -40, -5)
    stamp = datetime(2026, 10, 18, 12, tzinfo=IST)
    claim = _make_claim(_source("gift"), gift_gap_estimate(-80), "gift:1", stamp, 25000, store)
    assert claim.midpoint == pytest.approx(-80)
    assert store.family_pairs("gift:gap", clean_only=True) == []
    store.close()


def test_a_headline_shifts_by_its_usual_miss(tmp_path):
    store = Store(tmp_path / "board.sqlite")
    for _ in range(4):
        store.add_family_residual("world:crude:down", 10)
    guess = {
        "beat": "global",
        "direction": "down",
        "points_low": 40,
        "points_high": 90,
        "midpoint": -65,
        "confidence": 0.25,
        "headline": "Crude jumps",
        "shock_key": "world:crude:down",
        "body": "Crude jumps",
    }
    stamp = datetime(2026, 10, 18, 12, tzinfo=IST)
    claim = _make_claim(_source(), guess, "https://example.com/oil", stamp, 25000, store)
    assert claim.driver is None
    assert claim.midpoint == pytest.approx(-60)
    assert call_shift([10, 10, 10, 10]) == pytest.approx(5)
    store.close()


def test_pcr_keeps_the_live_sign():
    higher = pcr_estimate(0.2, 0.05, -10)
    lower = pcr_estimate(-0.2, 0.05, 10)
    assert higher["direction"] == "up"
    assert higher["driver"] == pytest.approx(0.2)
    assert lower["direction"] == "down"
    assert lower["driver"] == pytest.approx(-0.2)


def test_age_does_not_raise_the_weight():
    source = _source(n=200, weight=1)
    claim = _claim("FII selling", "https://example.com/fii", "fii:down", -20, confidence=1)
    assert claim_weight(claim, source, shrink_until=20) == pytest.approx(1)


def test_learning_row_shows_the_next_shift():
    now = datetime(2026, 10, 18, 15, tzinfo=IST)
    claim = _claim("Crude jumps", "https://example.com/oil", "world:crude:down", -65)
    claim.beat = "global"
    claim.residual = 10
    claim.ts = now.isoformat()
    page = render_page(None, [], [], 25000, 4, claims=[claim])
    assert "Not enough scores" in page
    assert "The board line starts after 4 checked predictions." in page
    row = page.split(">World<", 1)[1].split("</div>", 1)[0]
    assert "+2" in row


def _scored_rows(misses: list[float], beat: str = "global"):
    now = datetime(2026, 10, 18, 15, tzinfo=IST)
    claims = []
    history = []
    for index, miss in enumerate(misses):
        stamp = (now - timedelta(hours=len(misses) - index)).isoformat()
        claim = _claim("Crude jumps", f"https://example.com/{index}", "world:crude:down", -65)
        claim.beat = beat
        claim.residual = miss
        claim.ts = stamp
        claims.append(claim)
        history.append(Ensemble(id=str(index), ts=stamp, mu=0, sigma=10, n_shocks=1, nifty_level=25000, residual=miss))
    return claims, history


def test_improving_rises_when_later_misses_shrink():
    misses = [20, 20, 20, 20, 4, 4, 4, 4]
    claims, history = _scored_rows(misses)
    page = render_page(None, [], [], 25000, 8, history=history, claims=claims)
    score = learning_score(misses)
    assert score > 50
    assert f"class='gain up'>{score}" in page
    assert "Better" in page
    line = page.split("aria-label='Improving'", 1)[1].split("</svg>", 1)[0]
    assert "stroke='#0c7a3a'" in line
    row = page.split(">World<", 1)[1].split("</svg>", 1)[0]
    assert f"class='gain up'>{score}" in row


def test_improving_falls_when_later_misses_grow():
    misses = [4, 4, 4, 4, 20, 20, 20, 20]
    _claims, history = _scored_rows(misses, beat="flows")
    page = render_page(None, [], [], 25000, 8, history=history)
    score = learning_score(misses)
    assert score < 50
    assert f"class='gain down'>{score}" in page
    assert "Worse" in page
    line = page.split("aria-label='Improving'", 1)[1].split("</svg>", 1)[0]
    assert "stroke='#c62828'" in line


def test_pulse_and_tijori_join_the_agent_feeds():
    sources = {row["id"]: row for row in load_config()["sources"]}
    assert sources["pulse"]["beat"] == "flows"
    assert sources["pulse"]["important"] is True
    assert sources["pulse"]["label"] == "Pulse"
    assert sources["pulse"]["url"] == "https://pulse.zerodha.com/feed.php"
    assert sources["tijori"]["beat"] == "weights"
    assert sources["tijori"]["important"] is True
    assert sources["tijori"]["label"] == "Tijori"
    assert sources["tijori"]["url"] == "https://www.tijorialerts.com/company-updates/"
    allow = set(load_config()["allowlist"])
    assert "pulse.zerodha.com" in allow
    assert "www.tijorialerts.com" in allow
    assert "tijorialerts.com" in allow


def test_pulse_and_tijori_keep_a_story_unless_it_cannot_move_nifty():
    bank = judge_headline("Axis Bank Q2 profit up 38% on loan growth")
    assert bank["verdict"] == "keep"
    assert bank["guess"]["direction"] == "up"
    chips = judge_headline("Amazon says its AI chips will work with a popular coding language")
    assert chips["verdict"] == "keep"
    assert chips["guess"] is None
    cinema = judge_headline("Prahaar box office collection keeps the momentum going")
    assert cinema["verdict"] == "discard"
    assert "cinema" in cinema["reason"]
    assert judge_headline("Can Nifty rally further?")["verdict"] == "discard"
    assert judge_headline("8th Pay Commission: 14% Then, 140% Now?")["verdict"] == "keep"
    assert judge_headline("A small firm declares a dividend")["verdict"] == "discard"
    scored = judge_headline("Reliance board declares a dividend")
    assert scored["verdict"] == "scored"
    old = {"title": "Old Pulse item", "published": datetime(2026, 10, 1, tzinfo=IST), "url": "https://pulse.example/old", "summary": ""}
    since = datetime(2026, 10, 19, tzinfo=IST)
    assert items_for_feed([old], since, important=True) == [old]
    assert items_for_feed([old], since, important=False) == []


def test_important_feeds_show_that_they_were_checked():
    page = render_page(
        None,
        [],
        [],
        None,
        0,
        feeds=[
            {"label": "Pulse", "state": "read", "detail": "Checked · 8 stories", "lines": ["CoreWeave jumps — Kept, +8. Not proved irrelevant."]},
            {"label": "Tijori", "state": "miss", "detail": "No answer"},
        ],
    )
    assert "Important feeds" in page
    assert "class='feed ok'" in page
    assert "Pulse" in page
    assert "Checked · 8 stories" in page
    assert "CoreWeave jumps" in page
    assert "1 of 1 went into the prediction, adding <strong class='plus'>+8</strong>." in page
    assert "Kept, because it may move Nifty." in page
    assert "class='feed bad'" in page
    assert "Tijori" in page
    assert "No answer" in page
    assert "Important feeds" not in render_page(None, [], [], None, 0)


def test_an_important_feed_starts_with_more_weight(tmp_path):
    store = Store(tmp_path / "feeds.sqlite")
    store.seed_sources([
        {"id": "pulse", "beat": "flows", "kind": "rss", "url": "https://pulse.zerodha.com/feed.php", "important": True},
        {"id": "et-markets", "beat": "flows", "kind": "rss", "url": "https://et.example/rss"},
    ])
    assert store.source("pulse").weight == 1
    assert store.source("et-markets").weight == 0.4
    store.close()


def test_a_listing_page_is_read_as_a_feed():
    page = """
    <html><head>
    <script type="application/ld+json">{"@type":"ItemList","itemListElement":[
      {"name":"Reliance announces a buyback","url":"https://www.tijorialerts.com/company-updates/reliance/"},
      {"name":"","url":"https://example.com/skip"}
    ]}</script>
    </head></html>
    """
    rows = feed_items(page.encode())
    assert rows == [
        {
            "title": "Reliance announces a buyback",
            "url": "https://www.tijorialerts.com/company-updates/reliance/",
            "published": None,
            "summary": "",
        }
    ]
    rss = b"""<?xml version="1.0"?><rss version="2.0"><channel><item>
      <title>Oil jumps</title><link>https://pulse.zerodha.com/x</link>
      </item></channel></rss>"""
    assert feed_items(rss)[0]["title"] == "Oil jumps"
    assert feed_items(rss)[0]["url"] == "https://pulse.zerodha.com/x"


def test_fit_move_adds_the_usual_miss():
    short = [(2.0, -10.0) for _ in range(29)]
    assert fit_move(short, 4.0, -8.0) == pytest.approx(-8.0)
    line = [(2.0, -10.0) for _ in range(30)]
    assert fit_move(line, 4.0, -8.0) == pytest.approx(-20.0)
    mixed = [(1.0, -10.0)] * 15 + [(2.0, -12.0)] * 15
    assert fit_move(mixed, 4.0, -8.0) == pytest.approx(-28.0)

