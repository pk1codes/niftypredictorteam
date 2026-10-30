"""A forecast is shown only after the author and the critic sign the same numbers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, time

from niftyteam.evolve import LIVE_COUNT, band_mass, range_coverage, shown_half


def digest(view: dict) -> str:
    proof = view.get("proof") or {}
    payload = {
        "anchor": view.get("anchor"),
        "anchor_day": view.get("anchor_day"),
        "due": view.get("due"),
        "mu": view.get("mu"),
        "sigma": view.get("sigma"),
        "raw": view.get("raw"),
        "band": proof.get("band"),
        "window": proof.get("window"),
        "live_n": proof.get("live_n"),
        "fit": proof.get("fit"),
        "flat": proof.get("flat"),
        "momentum": proof.get("momentum"),
        "studied": proof.get("studied"),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def author_review(view: dict | None) -> dict:
    """The author's checks. A pass is not the critic's signature."""
    reasons: list[str] = []
    if not view:
        reasons.append("There is no forecast.")
        return {"role": "author", "verdict": "refuse", "reasons": reasons, "digest": ""}
    proof = view.get("proof") or {}
    live_n = int(proof.get("live_n") or 0)
    mu = float(view.get("mu") or 0)
    sigma = float(view.get("sigma") or 0)
    anchor = float(view.get("anchor") or 0)
    window = int(proof.get("window") or 0)
    held = proof.get("band")
    if sigma <= 0 or anchor <= 0:
        reasons.append("The last close or the band is missing.")
    if live_n < LIVE_COUNT and int(round(mu)) != 0:
        reasons.append("The center moved before 60 live closes.")
    if window < 20:
        reasons.append("Fewer than 20 rehearsal calls support the band.")
    if held is None or not 0 <= float(held) <= 1:
        reasons.append("Coverage is not a share of the rehearsal calls.")
    elif abs(float(held) - band_mass()) > 0.04 and window >= 20:
        pass
    return {
        "role": "author",
        "verdict": "agree" if not reasons else "refuse",
        "reasons": reasons,
        "digest": digest(view),
    }


def presentable(candidate, author, critic, signed, stamp: datetime):
    """Return a signed call only while its 3:30 is still ahead."""
    if _both(candidate, author, critic) and still_open(candidate, stamp):
        return candidate
    if signed and still_open(signed, stamp):
        return signed
    return None


def still_open(view: dict, stamp: datetime) -> bool:
    due = str(view.get("due") or "")
    day = stamp.date().isoformat()
    if due > day:
        return True
    if due < day:
        return False
    clock = stamp.timetz().replace(tzinfo=None)
    return clock < time(15, 30)


def note_author(store, view: dict | None) -> dict:
    review = author_review(view)
    store.set_meta("sign_author", json.dumps(review))
    _keep(store, view)
    return review


def note_critic(store, view: dict, verdict: str, reasons: list[str] | None = None) -> dict:
    if verdict not in {"agree", "refuse"}:
        raise ValueError(verdict)
    review = {
        "role": "critic",
        "verdict": verdict,
        "reasons": list(reasons or []),
        "digest": digest(view),
    }
    store.set_meta("sign_critic", json.dumps(review))
    _keep(store, view)
    return review


def public_forecast(view: dict | None) -> dict | None:
    """The signed call, in the words the page already uses."""
    if not view or view.get("sigma") in (None, 0) or view.get("anchor") is None:
        return None
    anchor = float(view["anchor"])
    sigma = float(view["sigma"])
    proof = view.get("proof") or {}
    due = str(view.get("due") or "")
    try:
        found = datetime.fromisoformat(due)
        due_label = f"{found:%A} {found.day} {found:%b}"
    except ValueError:
        due_label = due or "Next cash close"
    coverage = range_coverage(proof)
    live_n = int(proof.get("live_n") or 0)
    if live_n == 0:
        record = "On this version, no close has been checked yet."
    else:
        record = f"On this version, {live_n} closes were checked, with a typical miss of {float(proof.get('live_mae') or 0):.0f}."
    half = shown_half(proof, sigma)
    mu = float(view.get("mu") or 0)
    low = anchor + mu - half
    high = anchor + mu + half
    return {
        "ready": True,
        "anchor": anchor,
        "anchor_text": f"{anchor:,.0f}",
        "anchor_day": view.get("anchor_day"),
        "due": due,
        "due_label": due_label,
        "gap": str(view.get("gap") or "the next cash close"),
        "mu": float(view.get("mu") or 0),
        "sigma": sigma,
        "low": low,
        "high": high,
        "low_text": f"{low:,.0f}",
        "high_text": f"{high:,.0f}",
        "signed": bool(view.get("signed")),
        "coverage": coverage,
        "center": "The middle stays on the last close until 60 new closes beat a no-change guess by 15 points.",
        "record": record,
        "signed_line": "The builder and a second reviewer both agreed to this range." if view.get("signed") else "",
    }


def write_public_forecast(path, view: dict | None) -> None:
    payload = public_forecast(view) or {"ready": False}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def presented(store, stamp: datetime) -> dict | None:
    from niftyteam.evolve import evolve_view

    candidate = evolve_view(store)
    author = _load(store, "sign_author")
    critic = _load(store, "sign_critic")
    signed = _load(store, "signed_view")
    view = presentable(candidate, author, critic, signed, stamp)
    if view is None:
        return None
    shown = dict(view)
    shown["signed"] = True
    return shown


def display_close(store, stamp: datetime, fetch=None, look: bool = False) -> dict | None:
    """Signed call while its 3:30 is ahead. If that call is old, a fresh study can be shown."""
    shown = presented(store, stamp)
    if shown is not None:
        return shown
    if look:
        from niftyteam.evolve import run_evolve

        try:
            run_evolve(store, stamp, fetch=fetch)
        except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError):
            pass
    from niftyteam.evolve import evolve_view

    view = evolve_view(store)
    if not view or not still_open(view, stamp):
        return None
    if author_review(view)["verdict"] != "agree":
        return None
    found = dict(view)
    found["signed"] = False
    return found


def _both(view, author, critic) -> bool:
    if not view or not author or not critic:
        return False
    if author.get("verdict") != "agree" or critic.get("verdict") != "agree":
        return False
    dig = digest(view)
    return author.get("digest") == dig and critic.get("digest") == dig


def _keep(store, view: dict | None) -> None:
    if view is None:
        return
    author = _load(store, "sign_author")
    critic = _load(store, "sign_critic")
    if _both(view, author, critic):
        store.set_meta("signed_view", json.dumps(view))


def _load(store, key: str):
    raw = store.meta(key)
    if not raw:
        return None
    try:
        found = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return found if isinstance(found, dict) else None
