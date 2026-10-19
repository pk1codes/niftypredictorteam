import json
import re
from datetime import date, datetime, timedelta

import pytest

from niftyteam.ahead import (
    choose_published,
    consider_edit,
    judge_due,
    project,
    run_ahead,
    scored_samples,
)
from niftyteam.chart import render_page
from niftyteam.config import IST
from niftyteam.horizons import decision_due
from niftyteam.store import Store


def test_monday_due_is_tuesday_and_friday_due_is_monday():
    monday = datetime(2026, 10, 19, 16, 35, tzinfo=IST)
    friday = datetime(2026, 10, 16, 16, 35, tzinfo=IST)
    assert decision_due(monday) == datetime(2026, 10, 20, 15, 30, tzinfo=IST)
    assert decision_due(friday) == datetime(2026, 10, 19, 15, 30, tzinfo=IST)
    assert decision_due(datetime(2026, 10, 19, 15, 59, tzinfo=IST)) is None
    assert decision_due(datetime(2026, 10, 18, 19, tzinfo=IST)) is None


def test_second_tick_does_not_insert_another_call(tmp_path):
    store = Store(tmp_path / "ahead.sqlite")
    store.save_snapshots("2026-10-16", {"es_px": 5000.0, "usdinr_px": 84.0, "brent_px": 70.0})
    stamp = datetime(2026, 10, 19, 16, 35, tzinfo=IST)
    bars = _bars("2026-10-19", [100, 110, 120, 130, 140, 150, 160, 170])
    prices = {"es": 5100.0, "usdinr": 85.0, "brent": 72.0}
    fetches = {"n": 0}

    def fetch():
        fetches["n"] += 1
        return dict(prices)

    run_ahead(store, stamp, bars, fetch)
    run_ahead(store, stamp, bars, lambda: {"es": 9999.0, "usdinr": 1.0, "brent": 1.0})
    call = store.ahead_call("2026-10-19")
    assert fetches["n"] == 1
    assert call["due_day"] == "2026-10-20"
    assert call["anchor"] == 170
    assert call["predicted_move"] == 0
    assert call["baseline_move"] == 0
    assert store.snapshots("2026-10-19")["es"] == pytest.approx(100)
    assert store.snapshots("2026-10-19")["nifty5"] == pytest.approx(50)
    assert store.conn.execute("SELECT COUNT(*) AS n FROM ahead_calls").fetchone()["n"] == 1
    for table in ("claims", "ensembles", "levels", "level_pairs", "family_pairs"):
        assert store.conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"] == 0
    store.close()


def test_missing_due_date_is_discarded_and_not_trained(tmp_path):
    store = Store(tmp_path / "ahead.sqlite")
    store.add_ahead_call("2026-10-01", 100, "2026-10-02", 0, 1, 0, "[]")
    store.finish_ahead("2026-10-01", 5, "scored")
    store.save_snapshots("2026-10-01", {"nifty5": 1.0})
    store.add_ahead_call("2026-10-19", 100, "2026-10-20", 0, 0, 0, "[]")
    bars = [("2026-10-19", 100.0), ("2026-10-21", 130.0)]
    stamp = datetime(2026, 10, 21, 16, 35, tzinfo=IST)
    run_ahead(store, stamp, bars, None)
    assert store.ahead_call("2026-10-19")["status"] == "discarded"
    assert store.ahead_call("2026-10-19")["actual_move"] is None
    assert [sample["day"] for sample in scored_samples(store)] == ["2026-10-01"]
    store.close()


def test_a_due_bar_that_has_aged_out_stays_open(tmp_path):
    store = Store(tmp_path / "ahead.sqlite")
    store.add_ahead_call("2026-10-19", 100, "2026-10-20", 0, 0, 0, "[]")
    bars = [("2026-11-02", 100.0), ("2026-11-03", 101.0)]
    run_ahead(store, datetime(2026, 11, 3, 16, 35, tzinfo=IST), bars, None)
    assert store.ahead_call("2026-10-19")["status"] == "open"
    assert judge_due([("2026-10-19", 90.0)], "2026-10-20", datetime(2026, 10, 19, 16, 35, tzinfo=IST))[0] == "wait"
    store.close()


def test_walk_forward_does_not_train_on_its_own_day():
    rows = [([float(i)], float(i) * 2) for i in range(1, 15)]
    first, _contribs, _intercept = project(rows[:-1], rows[-1][0])
    rows[-1] = (rows[-1][0], 9999.0)
    second, _contribs, _intercept = project(rows[:-1], rows[-1][0])
    assert first == pytest.approx(second)
    moved, _contribs, _intercept = project(rows, rows[-1][0])
    assert moved != pytest.approx(first)


def test_published_move_stays_zero_until_the_untouched_window_wins():
    short = [_scored(i, train_n=30, actual=10, model=10) for i in range(1, 20)]
    assert choose_published(short, 4) is None
    young = [_scored(i, train_n=29, actual=10, model=10) for i in range(1, 21)]
    assert choose_published(young, 4) is None
    tied = [_scored(i, train_n=30, actual=10, model=0) for i in range(1, 21)]
    assert choose_published(tied, 4) is None
    ahead = [_scored(i, train_n=30, actual=10, model=8) for i in range(1, 21)]
    assert choose_published(ahead, 4) == 4
    frozen = ahead[:]
    frozen[0] = _scored(1, train_n=30, actual=10, model=8, day="2025-12-01")
    assert choose_published(frozen, 4, frozen[-1]["day"]) is None


def test_point_contributions_equal_the_predicted_move():
    history = [([1.0, 0.0], 10.0), ([2.0, 0.0], 20.0), ([3.0, 0.0], 30.0), ([4.0, 0.0], 40.0)]
    pred, contribs, intercept = project(history, [5.0, 1.0])
    assert pred == pytest.approx(sum(contribs) + intercept)
    page = render_page(
        None,
        [],
        [],
        None,
        0,
        ahead={"move": 0.8, "parts": [("Five sessions", 0.4), ("Base", 0.4)], "due": "2026-10-20"},
    )
    shown = [int(item) for item in re.findall(r"ahead-point[^>]*>([+-]?\d+)", page)]
    total = int(re.search(r"data-ahead='(-?\d+)'", page).group(1))
    assert sum(shown) == total == 1
    assert "Next close" in page
    assert "Due 2026-10-20" in page


def test_a_live_call_shows_parts_that_sum_to_the_move(tmp_path):
    store = Store(tmp_path / "ahead.sqlite")
    for index in range(50):
        day = (date(2026, 1, 1) + timedelta(days=index)).isoformat()
        store.add_ahead_call(day, 1000, day, 2.0 * (index + 1), 2.0 * (index + 1), 30, "[]")
        store.finish_ahead(day, 2.0 * (index + 1), "scored")
        store.save_snapshots(day, {"nifty5": float(index + 1), "es": 0.0, "usdinr": 0.0, "brent": 0.0})
    store.save_snapshots("2026-10-16", {"es_px": 10.0, "usdinr_px": 80.0, "brent_px": 70.0})
    store.set_meta("ahead_edit_day", "2026-10-19")
    stamp = datetime(2026, 10, 19, 16, 35, tzinfo=IST)
    bars = _bars("2026-10-19", [100, 120, 140, 160, 180, 200, 240])
    run_ahead(
        store,
        stamp,
        bars,
        lambda: {"es": 10.0, "usdinr": 80.0, "brent": 70.0},
    )
    call = store.ahead_call("2026-10-19")
    parts = json.loads(call["parts"])
    assert call["predicted_move"] == pytest.approx(call["model_move"])
    assert call["predicted_move"] == pytest.approx(sum(value for _label, value in parts))
    assert abs(call["predicted_move"]) > 1
    store.close()


def test_driver_edits_use_days_outside_the_latest_window():
    samples = []
    for index in range(40):
        day = (date(2026, 1, 1) + timedelta(days=index)).isoformat()
        samples.append(
            {
                "day": day,
                "values": {"signal": float(index + 1), "noise": 0.0},
                "actual": 80.0 * (index + 1),
            }
        )
    kept, probation, changed = consider_edit(samples, ["signal", "noise"], [])
    assert changed == "noise"
    assert kept == ["signal"]
    assert probation == ["noise"]
    promoted, _probation, added = consider_edit(samples, ["noise"], ["signal"])
    assert added == "signal"
    assert promoted == ["noise", "signal"]
    hidden = []
    for index in range(40):
        day = (date(2026, 3, 1) + timedelta(days=index)).isoformat()
        if index < 20:
            values = {"noise": 1.0, "signal": 0.0}
            actual = 5.0
        else:
            values = {"noise": 1.0, "signal": float(index)}
            actual = 80.0 * index
        hidden.append({"day": day, "values": values, "actual": actual})
    kept_hidden, _probation, added = consider_edit(hidden, ["noise"], ["signal"])
    assert "signal" not in kept_hidden
    assert added != "signal"
    _kept, _probation, changed = consider_edit(samples, ["signal", "noise"], [], samples[-5]["day"])
    assert changed is None


def _scored(index: int, train_n: int, actual: float, model: float, day: str | None = None) -> dict:
    return {
        "day": day or (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
        "actual": actual,
        "model_move": model,
        "train_n": train_n,
    }


def _bars(end: str, closes: list[float]) -> list[tuple[str, float]]:
    day = date.fromisoformat(end)
    found = []
    for close in reversed(closes):
        while day.weekday() >= 5:
            day -= timedelta(days=1)
        found.append((day.isoformat(), float(close)))
        day -= timedelta(days=1)
    return list(reversed(found))
