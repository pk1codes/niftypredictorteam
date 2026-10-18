from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from niftyteam.boss import agree_to_rescue, boss_sentence, crew_sentence, wake, watch_line
from niftyteam.chart import render_page
from niftyteam.config import impact_class
from niftyteam.ensemble import adjust_sigma, apply_score, attributed_points, build_ensemble, learned_midpoint, next_sigma_floor
from niftyteam.estimate import apply_family_bias, estimate_headline, fitted_move, gift_gap_estimate, headline_kind, level_estimate, oi_change_estimate, pcr_estimate, promoted_miss
from niftyteam.learn import learning_score, learning_trail
from niftyteam.horizons import forecast_move, next_open, session_close, sessions_ahead, week_move
from niftyteam.models import Claim, Ensemble, Event, Source
from niftyteam.pcr import option_book, parse_flows
from niftyteam.scout import agent_line, parse_google_feed, parse_results, query_for, scout_sentence
from niftyteam.search import parse_gift
from niftyteam.store import Store
from niftyteam.tick import _fold_feed, _publish, _report_limits, _rescue_news, _scout, _still_names, accuracy_notes, miss_titles

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
    forecast = page.split("aria-label='Forecast'", 1)[1].split("</svg>", 1)[0]
    assert "Spot 25,000" in forecast
    assert "GIFT 23,085" in forecast
    assert "Next -35" in forecast
    assert "Mean 24,494" in forecast
    assert "10,000" not in forecast
    assert "stroke='#0c7a3a'" in forecast
    assert "stroke='#b86e00'" in forecast
    assert "stroke='#1d4e89'" in forecast
    assert "stroke='#6b3fa0'" in forecast
    assert "200-day mean" in page
    assert "previous three bells" in page
    assert "stroke-opacity='0.18'" in forecast
    assert "stroke-opacity='0.35'" in forecast
    assert "stroke-opacity='0.55'" in forecast
    assert "stroke='#6b3fa0' stroke-width='2' points=" in forecast
    assert "Not enough scores" in page
    assert "FII net" in page
    assert "+1,166 cr" in page
    assert "class='impact minus'>-60" in page
    assert "class='impact plus'>+20" in page
    assert impact_class(0) == "flat"
    assert "class='light on'" in page
    assert f"Last run {stamp.strftime('%d %b %H:%M')}" in page
    assert "7 of 8" in page
    assert "Scout looked across the web." in page
    assert "Market shut" in page
    assert "Oil jumps" in page
    assert "Spread 22" in page
    assert "Scored an open call." in page
    assert "Needs a look" not in page
    assert "Watching. Every agent is working." in page
    assert f"{(stamp - timedelta(hours=1)).strftime('%H:%M')} · 1 of 8 · mean +8" in page


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
    assert "no call has been scored" in text
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

