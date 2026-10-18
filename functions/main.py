"""Hourly tick on zero-41fde. Leave this undeployed until asked to ship."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from firebase_admin import initialize_app, storage
from firebase_functions import scheduler_fn

initialize_app()

BUCKET = "zero-41fde.firebasestorage.app"


def _root() -> Path:
    root = Path("/tmp/niftyteam")
    (root / "data").mkdir(parents=True, exist_ok=True)
    candidates = [HERE / "beats.yaml", HERE.parent / "beats.yaml"]
    source = next(path for path in candidates if path.exists())
    (root / "beats.yaml").write_text(source.read_text())
    return root


def _bucket_sync(root: Path, download: bool) -> None:
    bucket = storage.bucket(BUCKET)
    database = root / "data" / "niftyteam.sqlite"
    blob = bucket.blob("niftyteam/niftyteam.sqlite")
    if download:
        if blob.exists():
            blob.download_to_filename(str(database))
        return
    if database.exists():
        blob.upload_from_filename(str(database))
    chart = root / "data" / "chart.html"
    if chart.exists():
        bucket.blob("niftyteam/chart.html").upload_from_filename(str(chart))


@scheduler_fn.on_schedule(schedule="0 * * * *", timezone="Asia/Kolkata")
def nifty_tick(event: scheduler_fn.ScheduledEvent) -> None:
    from niftyteam.tick import tick

    root = _root()
    _bucket_sync(root, download=True)
    tick(root)
    _bucket_sync(root, download=False)
