from __future__ import annotations

import json
from datetime import datetime, time

from niftyteam.config import IST
from niftyteam.horizons import decision_due

V1 = ("nifty5", "es", "usdinr", "brent")
LABELS = {
    "nifty5": "Five sessions",
    "es": "US futures",
    "usdinr": "Rupee",
    "brent": "Brent",
}
RAW = {"brent": "brent_px", "usdinr": "usdinr_px", "es": "es_px"}
WINDOW = 20
MIN_TRAIN = 30
MAE_STEP = 30.0
RIDGE = 1.0


def anchor_close(bars: list, stamp: datetime) -> float | None:
    if stamp.timetz().replace(tzinfo=None) < time(15, 30):
        return None
    day = stamp.date().isoformat()
    for bar in bars:
        if bar[0] == day:
            return float(bar[1])
    return None


def five_session_move(bars: list, day: str) -> float | None:
    closes: dict[str, float] = {}
    for bar in bars:
        if bar[0] <= day:
            closes[bar[0]] = float(bar[1])
    ordered = [closes[key] for key in sorted(closes)]
    if len(ordered) < 6:
        return None
    return ordered[-1] - ordered[-6]


def judge_due(bars: list, due_day: str, now: datetime) -> tuple[str, float | None]:
    """Score the exact due date, discard a gap inside the fetch, otherwise wait."""
    closes: dict[str, float] = {}
    for bar in bars:
        closes[bar[0]] = float(bar[1])
    if due_day in closes:
        due_at = datetime.combine(
            datetime.fromisoformat(due_day).date(),
            time(15, 30),
            tzinfo=IST,
        )
        stamp = now if now.tzinfo is not None else now.replace(tzinfo=IST)
        if stamp >= due_at.astimezone(stamp.tzinfo):
            return "score", closes[due_day]
        return "wait", None
    if not closes:
        return "wait", None
    days = sorted(closes)
    if due_day < days[0] or due_day > days[-1]:
        return "wait", None
    return "discard", None


def project(
    history: list[tuple[list[float], float]],
    today: list[float],
    lam: float = RIDGE,
) -> tuple[float, list[float], float]:
    """Fit earlier days only. Return the move, each driver's points, and the intercept."""
    width = len(today)
    if width == 0:
        if not history:
            return 0.0, [], 0.0
        intercept = sum(item[1] for item in history) / len(history)
        return intercept, [], intercept
    if not history:
        return 0.0, [0.0] * width, 0.0
    columns = [[row[index] for row, _target in history] for index in range(width)]
    means = []
    scales = []
    for column in columns:
        mean = sum(column) / len(column)
        var = sum((item - mean) ** 2 for item in column) / len(column)
        means.append(mean)
        scales.append(var ** 0.5 if var ** 0.5 > 1e-12 else 1.0)
    size = width + 1
    matrix = [[0.0] * size for _ in range(size)]
    target = [0.0] * size
    matrix[0][0] = float(len(history))
    for row, outcome in history:
        target[0] += outcome
        scaled = [(row[index] - means[index]) / scales[index] for index in range(width)]
        for index, value in enumerate(scaled):
            matrix[0][index + 1] += value
            matrix[index + 1][0] += value
            target[index + 1] += value * outcome
            for other, second in enumerate(scaled):
                matrix[index + 1][other + 1] += value * second
    for index in range(width):
        matrix[index + 1][index + 1] += lam
    solved = _solve(matrix, target)
    if solved is None:
        return 0.0, [0.0] * width, 0.0
    intercept = solved[0]
    contribs = []
    total = intercept
    for index, value in enumerate(today):
        point = solved[index + 1] * ((value - means[index]) / scales[index])
        contribs.append(point)
        total += point
    return total, contribs, intercept


def choose_published(rows: list[dict], model_move: float, frozen_on: str = "") -> float | None:
    """Return the model move when the last 20 scored days were an untouched win."""
    if len(rows) < WINDOW:
        return None
    window = rows[-WINDOW:]
    if any(int(row["train_n"]) < MIN_TRAIN for row in window):
        return None
    if frozen_on and any(row["day"] < frozen_on for row in window):
        return None
    model_mae = sum(abs(row["actual"] - row["model_move"]) for row in window) / WINDOW
    base_mae = sum(abs(row["actual"]) for row in window) / WINDOW
    if model_mae < base_mae:
        return model_move
    return None


def consider_edit(
    samples: list[dict],
    kept: list[str],
    probation: list[str],
    frozen_on: str = "",
) -> tuple[list[str], list[str], str | None]:
    """One driver change, judged only on days outside the latest 20."""
    if len(samples) < WINDOW + 12:
        return list(kept), list(probation), None
    if frozen_on and any(sample["day"] < frozen_on for sample in samples[-WINDOW:]):
        return list(kept), list(probation), None
    selection = samples[:-WINDOW]
    base = walk_mae(selection, list(kept))
    if base is None:
        return list(kept), list(probation), None
    best_name = None
    best_gain = MAE_STEP
    for name in probation:
        if name in kept:
            continue
        mae = walk_mae(selection, list(kept) + [name])
        if mae is None:
            continue
        gain = base - mae
        if gain > best_gain:
            best_gain = gain
            best_name = name
    if best_name is not None:
        return list(kept) + [best_name], [name for name in probation if name != best_name], best_name
    drop_name = None
    drop_rise = None
    for name in kept:
        mae = walk_mae(selection, [item for item in kept if item != name])
        if mae is None:
            continue
        rise = mae - base
        if rise <= MAE_STEP and (drop_rise is None or rise < drop_rise):
            drop_rise = rise
            drop_name = name
    if drop_name is None:
        return list(kept), list(probation), None
    kept_next = [name for name in kept if name != drop_name]
    probation_next = list(probation)
    if drop_name not in probation_next:
        probation_next.append(drop_name)
    return kept_next, probation_next, drop_name


def walk_mae(samples: list[dict], names: list[str]) -> float | None:
    usable: list[tuple[list[float], float]] = []
    errors = []
    for sample in samples:
        vector = _vector(sample, names)
        if vector is None:
            continue
        usable.append((vector, float(sample["actual"])))
        if len(usable) < 3:
            continue
        pred, _contribs, _intercept = project(usable[:-1], vector)
        errors.append(abs(float(sample["actual"]) - pred))
    if len(errors) < 10:
        return None
    return sum(errors) / len(errors)


def scored_samples(store) -> list[dict]:
    samples = []
    for call in store.ahead_calls():
        if call["status"] != "scored" or call["actual_move"] is None:
            continue
        values = {
            name: value
            for name, value in store.snapshots(call["day"]).items()
            if not name.endswith("_px")
        }
        samples.append({"day": call["day"], "values": values, "actual": float(call["actual_move"])})
    return samples


def ahead_view(store) -> dict | None:
    row = store.latest_ahead()
    if row is None:
        return None
    try:
        parts = json.loads(row["parts"] or "[]")
    except json.JSONDecodeError:
        parts = []
    return {"move": float(row["predicted_move"]), "parts": parts, "due": row["due_day"]}


def run_ahead(store, stamp: datetime, bars: list, fetch_prices=None) -> None:
    _seed(store)
    _score_open(store, stamp, bars)
    due = decision_due(stamp)
    if due is None:
        return
    day = stamp.date().isoformat()
    if store.ahead_call(day) is not None:
        return
    if store.meta("ahead_edit_day") != day:
        _edit(store, day)
        store.set_meta("ahead_edit_day", day)
    if anchor_close(bars, stamp) is None or fetch_prices is None:
        return
    prices = fetch_prices() or {}
    _place(store, stamp, bars, prices, due)


def _score_open(store, stamp: datetime, bars: list) -> None:
    for call in store.ahead_calls():
        if call["status"] != "open":
            continue
        kind, close = judge_due(bars, call["due_day"], stamp)
        if kind == "wait":
            continue
        if kind == "discard":
            store.finish_ahead(call["day"], None, "discarded")
            continue
        store.finish_ahead(call["day"], float(close) - float(call["anchor"]), "scored")


def _edit(store, day: str) -> None:
    _seed(store)
    kept, probation = _split(store)
    _kept, _probation, changed = consider_edit(
        scored_samples(store),
        kept,
        probation,
        store.meta("ahead_frozen_on") or "",
    )
    if changed is None or (changed in _kept and changed not in V1):
        return
    for name in _kept:
        store.set_ahead_status(name, "kept")
    for name in _probation:
        if name not in _kept:
            store.ensure_ahead_driver(name, "probation")
            store.set_ahead_status(name, "probation")
    store.set_meta("ahead_frozen_on", day)


def _place(store, stamp: datetime, bars: list, prices: dict, due: datetime) -> None:
    day = stamp.date().isoformat()
    anchor = anchor_close(bars, stamp)
    if anchor is None or any(name not in prices or prices[name] is None for name in RAW):
        return
    store.save_snapshots(day, {RAW[name]: float(prices[name]) for name in RAW})
    previous = {name: store.previous_snapshot(RAW[name], day) for name in RAW}
    if any(value is None for value in previous.values()):
        return
    nifty5 = five_session_move(bars, day)
    if nifty5 is None:
        return
    features = {
        "nifty5": nifty5,
        "es": float(prices["es"]) - float(previous["es"]),
        "usdinr": float(prices["usdinr"]) - float(previous["usdinr"]),
        "brent": float(prices["brent"]) - float(previous["brent"]),
    }
    store.save_snapshots(day, features)
    kept = _order([row["name"] for row in store.ahead_drivers() if row["status"] == "kept"])
    if any(name not in features for name in kept):
        return
    history = []
    gate_rows = []
    for call in store.ahead_calls():
        if call["status"] != "scored" or call["actual_move"] is None:
            continue
        gate_rows.append(
            {
                "day": call["day"],
                "actual": float(call["actual_move"]),
                "model_move": float(call["model_move"]),
                "train_n": int(call["train_n"]),
            }
        )
        values = store.snapshots(call["day"])
        if any(name not in values for name in kept):
            continue
        history.append(([float(values[name]) for name in kept], float(call["actual_move"])))
    model_move, contribs, intercept = project(history, [features[name] for name in kept])
    published = choose_published(gate_rows, model_move, store.meta("ahead_frozen_on") or "")
    if published is None:
        predicted = 0.0
        parts = [(LABELS.get(name, name), 0.0) for name in kept] + [("Base", 0.0)]
        shown = {name: 0.0 for name in kept}
    else:
        predicted = model_move
        parts = [(LABELS.get(name, name), contribs[index]) for index, name in enumerate(kept)]
        parts.append(("Base", intercept))
        shown = {name: contribs[index] for index, name in enumerate(kept)}
    store.add_ahead_call(
        day,
        anchor,
        due.date().isoformat(),
        predicted,
        model_move,
        len(history),
        json.dumps(parts),
    )
    for row in store.ahead_drivers():
        if row["status"] == "kept":
            store.set_ahead_driver(row["name"], "kept", shown.get(row["name"], 0.0))
        else:
            store.set_ahead_driver(row["name"], row["status"], 0.0)


def _seed(store) -> None:
    for name in V1:
        store.ensure_ahead_driver(name, "kept")


def _split(store) -> tuple[list[str], list[str]]:
    kept = []
    probation = []
    for row in store.ahead_drivers():
        if row["status"] == "kept":
            kept.append(row["name"])
        elif row["status"] == "probation":
            probation.append(row["name"])
    return _order(kept), probation


def _order(names: list[str]) -> list[str]:
    rank = {name: index for index, name in enumerate(V1)}
    return sorted(names, key=lambda name: (rank.get(name, 100), name))


def _vector(sample: dict, names: list[str]) -> list[float] | None:
    values = sample["values"]
    if any(name not in values for name in names):
        return None
    return [float(values[name]) for name in names]


def _solve(matrix: list[list[float]], target: list[float]) -> list[float] | None:
    size = len(target)
    rows = [matrix[index][:] + [target[index]] for index in range(size)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda row: abs(rows[row][col]))
        if abs(rows[pivot][col]) < 1e-12:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        scale = rows[col][col]
        for col_index in range(col, size + 1):
            rows[col][col_index] /= scale
        for row in range(size):
            if row == col:
                continue
            factor = rows[row][col]
            for col_index in range(col, size + 1):
                rows[row][col_index] -= factor * rows[col][col_index]
    return [rows[index][size] for index in range(size)]
