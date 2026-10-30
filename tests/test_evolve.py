import random
from datetime import date, datetime, timedelta

import pytest

from niftyteam.chart import render_page
from niftyteam.config import IST
from niftyteam.signoff import author_review, digest, display_close, note_author, note_critic, presentable, public_forecast
from niftyteam.evolve import (
    band_mass,
    coverage_scale,
    counted_width,
    feature_row,
    gap_phrase,
    live_ready,
    next_session,
    publish,
    replay,
    skill_ratio,
    study,
    up_chance,
)


def test_same_day_us_settle_is_left_out_and_the_vix_close_is_kept():
    books = _walk(date(2026, 10, 16), 30, seed=3)
    day = books["nifty"][-1][0]
    for name in ("es", "inr", "brent"):
        books[name] = [(bar_day, 10.0) for bar_day, _close in books[name]]
        books[name][-1] = (day, 99999.0)
    books["vix"][-2] = (books["vix"][-2][0], 10.0)
    books["vix"][-1] = (day, 16.0)
    row = feature_row(books, day)
    assert row is not None
    assert row["es"] == 0
    assert row["inr"] == 0
    assert row["brent"] == 0
    assert row["vix"] == 6


def test_the_close_being_predicted_is_not_a_feature():
    books = _walk(date(2026, 10, 16), 30, seed=4)
    day = books["nifty"][-2][0]
    before = feature_row(books, day)
    books["nifty"][-1] = (books["nifty"][-1][0], 999999.0)
    assert feature_row(books, day) == before


def test_the_call_does_not_see_the_move_it_is_scoring():
    samples = _signal(80)
    first, _fit = replay(samples, prior=[1.0])
    samples[-1]["actual"] = 10000.0
    second, _fit = replay(samples, prior=[1.0])
    assert [row["mu"] for row in first] == [row["mu"] for row in second]
    assert [row["published"] for row in first] == [row["published"] for row in second]
    assert [row["sigma"] for row in first] == [row["sigma"] for row in second]


def test_a_flipped_relationship_pulls_the_weight_across():
    samples = []
    for index in range(200):
        signal = 1.0 if index % 2 == 0 else -1.0
        move = (2.0 if index < 100 else -2.0) * signal
        samples.append({"day": f"{index:04d}", "actual": move, "x": [signal]})
    _rows, fit = replay(samples, forget=0.85, lam=0.01, warm=30, prior=[1.0])
    assert fit.slopes()[0] < 0


def test_no_edge_keeps_the_center_on_unchanged():
    assert skill_ratio(10, 9) == 0
    assert skill_ratio(5, 10) == 0.5
    assert publish(40, 0) == 0
    assert publish(40, 0.5) == 20


def test_the_band_scale_uses_only_past_misses_and_live_needs_sixty():
    pairs = [(float(index), 50.0) for index in range(100)]
    scale = coverage_scale(pairs)
    held = sum(1 for err, sigma in pairs if err <= scale * sigma) / len(pairs)
    assert abs(held - band_mass()) <= 0.02
    assert coverage_scale(pairs[:30]) == 1.0
    short = [{"actual": 50.0, "mu": 20.0} for _ in range(59)]
    assert live_ready(short) is False
    ready = [{"actual": 50.0, "mu": 20.0} for _ in range(60)]
    assert live_ready(ready) is True
    close = [{"actual": 50.0, "mu": 10.0} for _ in range(60)]
    assert live_ready(close) is False


def test_the_counted_band_holds_at_least_ninety_percent():
    misses = [float(index) for index in range(1, 81)]
    half, share = counted_width(misses)
    assert half == 72
    assert share == pytest.approx(0.90)
    assert sum(1 for miss in misses if miss <= half) / len(misses) >= 0.90


def test_shaded_band_is_the_normal_middle():
    assert band_mass() == pytest.approx(0.6827, abs=0.001)
    assert up_chance(0, 100) == pytest.approx(0.5, abs=0.001)
    assert up_chance(100, 100) > 0.8


def test_an_open_session_is_not_the_anchor_and_friday_points_at_monday():
    books = _walk(date(2026, 10, 16), 100, seed=5)
    last = books["nifty"][-1][0]
    midday = datetime.fromisoformat(last + "T11:00:00").replace(tzinfo=IST)
    early = study(books, midday, live_from=last)
    assert early is not None
    assert early["anchor_day"] < last
    closed = datetime.fromisoformat(last + "T16:10:00").replace(tzinfo=IST)
    done = study(books, closed, live_from=last)
    assert done is not None
    assert done["anchor_day"] == last
    assert done["due"] == "2026-10-19"
    assert done["gap"] == gap_phrase(last, "2026-10-19")
    assert "break" in done["gap"]
    assert next_session("2026-10-16") == "2026-10-19"
    assert gap_phrase("2026-10-21", "2026-10-22") == "about 24 hours after the last close"
    assert done["sigma"] > 0
    assert done["mu"] == 0
    assert done["proof"]["wide_share"] >= 0.90
    assert done["proof"]["wide"] > done["sigma"]


def test_a_forecast_is_shown_only_after_both_signatures(tmp_path):
    from datetime import datetime

    from niftyteam.config import IST
    from niftyteam.store import Store

    view = {
        "anchor": 22811.35,
        "anchor_day": "2026-10-21",
        "due": "2026-10-22",
        "mu": 0.0,
        "sigma": 137.97,
        "raw": 19.04,
        "proof": {"band": 0.662, "window": 80, "live_n": 0, "fit": 133.9, "flat": 132.9, "momentum": 193.9, "studied": 1169},
    }
    moved = dict(view, mu=19.0)
    assert author_review(moved)["verdict"] == "refuse"
    assert author_review(view)["verdict"] == "agree"
    store = Store(tmp_path / "sign.sqlite")
    note_author(store, view)
    stamp = datetime(2026, 10, 21, 20, tzinfo=IST)
    assert presentable(view, {"verdict": "agree", "digest": digest(view)}, None, None, stamp) is None
    note_critic(store, view, "agree", [])
    shown = presentable(
        view,
        {"verdict": "agree", "digest": digest(view)},
        {"verdict": "agree", "digest": digest(view)},
        None,
        stamp,
    )
    assert shown["anchor"] == 22811.35
    late = datetime(2026, 10, 22, 16, tzinfo=IST)
    assert presentable(
        view,
        {"verdict": "agree", "digest": digest(view)},
        {"verdict": "agree", "digest": digest(view)},
        view,
        late,
    ) is None
    newer = dict(view, sigma=150.0)
    note_author(store, newer)
    assert presentable(
        newer,
        {"verdict": "agree", "digest": digest(newer)},
        {"verdict": "agree", "digest": digest(view)},
        view,
        stamp,
    )["sigma"] == 137.97
    store.close()


def test_an_old_close_is_replaced_by_a_fresh_look(tmp_path):
    from niftyteam.store import Store

    books = _walk(date(2099, 1, 9), 100, seed=5)
    last = books["nifty"][-1][0]
    store = Store(tmp_path / "look.sqlite")
    old = {
        "anchor": 22000.0,
        "anchor_day": "2026-10-15",
        "due": "2026-10-16",
        "mu": 0.0,
        "sigma": 100.0,
        "raw": 0.0,
        "proof": {"band": 0.66, "window": 80, "live_n": 0, "fit": 10, "flat": 10, "momentum": 12, "studied": 80},
    }
    note_author(store, old)
    note_critic(store, old, "agree", [])
    stamp = datetime.fromisoformat(last + "T16:10:00").replace(tzinfo=IST)
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return books

    shown = display_close(store, stamp, fetch=fetch, look=True)
    assert calls["n"] == 1
    assert shown is not None
    assert shown["due"] == next_session(last)
    assert shown["anchor_day"] == last
    assert shown["mu"] == 0
    assert shown["signed"] is False
    page = render_page(None, [], [], 25000, 0, forecast=shown)
    assert "may finish between" in page
    assert "This guess is old." not in page
    again = display_close(store, stamp, fetch=fetch, look=True)
    assert calls["n"] == 1
    assert again["due"] == shown["due"]
    missed = display_close(store, stamp, fetch=lambda: None, look=True)
    assert missed["due"] == shown["due"]
    store.close()


def test_the_page_shows_the_bell_and_the_proofs():
    view = {
        "anchor": 25000,
        "anchor_day": "2026-10-21",
        "due": "2099-01-04",
        "gap": "about 24 hours after the last close",
        "mu": 0,
        "raw": 42,
        "sigma": 150,
        "skill": 0,
        "up": 0.5,
        "parts": [["US futures", 0], ["Base", 0]],
        "trail": [[160, 170], [150, 168], [148, 166]],
        "proof": {
            "studied": 400,
            "window": 80,
            "fit": 140,
            "printed": 150,
            "flat": 150,
            "momentum": 210,
            "band": 0.66,
            "wide": 400,
            "wide_share": 0.90,
            "direction": None,
            "direction_n": 0,
            "earlier": 155,
            "later": 148,
            "improving": False,
            "quieter": False,
            "live_n": 0,
            "live_mae": None,
        },
    }
    page = render_page(
        None,
        [],
        [],
        25120,
        0,
        gift={"price": 25240, "change": 4, "live": True},
        ahead={"move": 12, "parts": [["Base", 12]], "due": "2026-10-22"},
        forecast=view,
        spot_live=False,
    )
    assert "may finish between" in page
    assert "at 15:30 on Sunday 4 Jan" in page
    assert "24,600" in page and "25,400" in page
    assert "id='spot-dot'" in page and "id='gift-dot'" in page
    assert "prices.json" in page
    assert "id='spot-state' class='pill'>Closed" in page
    assert "id='gift-state' class='pill on'>Live" in page
    assert "The fit missed by 140" in page
    assert "No change missed by 150" in page
    assert "middle stayed put" in page
    shared = public_forecast(view)
    assert shared["low_text"] == "24,600"
    assert shared["high_text"] == "25,400"
    assert shared["anchor_text"] == "25,000"
    assert shared["mu"] == 0
    assert shared["coverage"] == "90% of the last 80 past checks finished inside a range this wide."
    assert shared["signed_line"] == ""
    assert "data-session='0.0'" in page
    assert "90% of the last 80 past checks finished inside a range this wide." in page
    assert "will be" not in page
    assert "Next close" not in page
    assert "Next open" not in page
    assert "this hour guessed" not in page
    stale = dict(view, due="2026-10-22")
    old = render_page(None, [], [], 25120, 0, forecast=stale)
    assert "24,600" not in old and "25,400" not in old
    assert "This guess is old." in old
    assert "may finish between" not in old
    assert "id='spot-dot'" not in old


def _walk(end: date, count: int, seed: int) -> dict[str, list[tuple[str, float]]]:
    rng = random.Random(seed)
    days = []
    cursor = end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    days.reverse()
    nifty, es, rupee, brent, vix = 22000.0, 5000.0, 84.0, 80.0, 14.0
    books = {name: [] for name in ("nifty", "es", "inr", "brent", "vix")}
    for day in days:
        nifty += rng.gauss(0, 80)
        es += rng.gauss(0, 20)
        rupee += rng.gauss(0, 0.05)
        brent += rng.gauss(0, 0.8)
        vix = max(9.0, vix + rng.gauss(0, 0.3))
        key = day.isoformat()
        books["nifty"].append((key, nifty))
        books["es"].append((key, es))
        books["inr"].append((key, rupee))
        books["brent"].append((key, brent))
        books["vix"].append((key, vix))
    return books


def _signal(count: int) -> list[dict]:
    rows = []
    for index in range(count):
        signal = 1.0 if index % 2 == 0 else -1.0
        rows.append({"day": f"{index:04d}", "actual": signal, "x": [signal]})
    return rows

