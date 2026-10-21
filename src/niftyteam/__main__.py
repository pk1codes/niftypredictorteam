from __future__ import annotations

import argparse
import json

from niftyteam.ahead import ahead_view
from niftyteam.evolve import evolve_view
from niftyteam.signoff import presented, write_public_forecast
from niftyteam.chart import render_page, write_prices
from niftyteam.config import find_root, impact_text, load_dotenv, now_ist
from niftyteam.search import live_quotes
from niftyteam.ensemble import book_std
from niftyteam.store import Store
from niftyteam.tick import important_view, tick


def main() -> None:
    parser = argparse.ArgumentParser(prog="niftyteam")
    parser.add_argument("command", choices=("tick", "board", "report", "chart", "quotes"))
    args = parser.parse_args()
    if args.command == "tick":
        raise SystemExit(tick())
    root = find_root()
    if args.command == "quotes":
        found = live_quotes()
        path = root / "data" / "prices.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_prices(path, found.get("nifty"), found.get("gift"))
        print(path)
        return
    load_dotenv(root)
    store = Store(root / "data" / "niftyteam.sqlite")
    try:
        if args.command == "board":
            _board(store)
        elif args.command == "report":
            _report(store)
        else:
            latest = store.latest_ensemble("session")
            opened = store.latest_ensemble("open")
            rows = store.ensembles()
            residuals = [(row.residual, row.sigma) for row in rows if row.residual is not None]
            cached = store.meta("nifty")
            gift_price = store.meta("gift_nifty")
            found = live_quotes()
            spot = found.get("nifty") or {}
            fresh_gift = found.get("gift")
            if spot.get("price") is not None:
                cached = f"{float(spot['price']):.2f}"
                spot_live = bool(spot.get("live"))
            else:
                spot_live = False
            if fresh_gift and fresh_gift.get("price") is not None:
                gift = fresh_gift
            elif gift_price:
                gift = {"price": float(gift_price), "change": float(store.meta("gift_change") or 0), "live": False}
            else:
                gift = None
            fii = store.meta("fii_net")
            agents = store.meta("agents")
            raw_notes = store.meta("issues")
            try:
                notes = json.loads(raw_notes) if raw_notes else []
            except json.JSONDecodeError:
                notes = []
            html = render_page(
                latest,
                residuals,
                store.events(80),
                float(cached) if cached else None,
                len(residuals),
                store.meta("last_tick"),
                gift,
                float(fii) if fii else None,
                notes,
                int(agents) if agents else None,
                rows,
                opened,
                store.scored_claims(),
                ahead_view(store),
                important_view(store),
                store.families(),
                presented(store, now_ist()),
                spot_live=spot_live,
            )
            path = root / "data" / "chart.html"
            path.write_text(html)
            level = float(cached) if cached else None
            write_prices(
                path.parent / "prices.json",
                None if level is None else {"price": level, "live": spot_live},
                gift,
            )
            shown = presented(store, now_ist())
            write_public_forecast(path.parent / "forecast.json", shown)
            write_public_forecast(root / "docs" / "forecast.json", shown)
            print(path)
    finally:
        store.close()


def _board(store: Store) -> None:
    latest = store.latest_ensemble()
    if latest is None:
        print("No forecast yet.")
    else:
        print(f"Mean {impact_text(latest.mu)}  spread {latest.sigma:.0f}")
    for event in store.events(80):
        print(f"{event.ts[5:16]}  {event.sentence}  {impact_text(event.impact)}")


def _report(store: Store) -> None:
    rows = [row for row in store.ensembles() if row.residual is not None]
    if not rows:
        print("No scored forecasts yet.")
        return
    residuals = [row.residual for row in rows]
    mean = sum(residuals) / len(residuals)
    flags = [abs(row.actual - row.mu) <= row.sigma for row in rows]
    print(f"Error mean {mean:+.1f}")
    print(f"Error spread {book_std(residuals):.1f}")
    print(f"Inside 1 spread {sum(flags) / len(flags):.0%} of {len(rows)}")
    print("Sources")
    for source in store.sources():
        if source.n_scored == 0:
            continue
        src_mean = source.residual_sum / source.n_scored
        print(f"  {source.id}  n={source.n_scored}  bias={src_mean:+.1f}  weight={source.weight:.2f}  {source.status}")


if __name__ == "__main__":
    main()
