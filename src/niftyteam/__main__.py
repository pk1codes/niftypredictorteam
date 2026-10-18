from __future__ import annotations

import argparse
import json

from niftyteam.chart import render_page
from niftyteam.config import find_root, impact_text, load_dotenv
from niftyteam.ensemble import book_std
from niftyteam.store import Store
from niftyteam.tick import tick


def main() -> None:
    parser = argparse.ArgumentParser(prog="niftyteam")
    parser.add_argument("command", choices=("tick", "board", "report", "chart"))
    args = parser.parse_args()
    if args.command == "tick":
        raise SystemExit(tick())
    root = find_root()
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
            gift = None
            if gift_price:
                gift = {"price": float(gift_price), "change": float(store.meta("gift_change") or 0)}
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
            )
            path = root / "data" / "chart.html"
            path.write_text(html)
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
