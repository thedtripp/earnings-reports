"""Build the demo page from earnings.ics. Usage: python3 build_site.py [--out _site]"""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path

from earnings_calendar import site

ROOT = Path(__file__).parent


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--ics", default=str(ROOT / "earnings.ics"))
    p.add_argument("--out", default=str(ROOT / "_site"))
    args = p.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    data = Path(args.ics).read_bytes()
    cover = ROOT / "assets" / "cover.png"
    if cover.exists():
        shutil.copy(cover, out / "cover.png")
    shutil.copy(args.ics, out / "earnings.ics")
    now = datetime.now(timezone.utc)
    (out / "index.html").write_text(
        site.render(site.rows_from_ics(data, today=now), now, "cover.png" if cover.exists() else None),
        encoding="utf-8")
    print(f"wrote {out / 'index.html'}")


if __name__ == "__main__":
    main()
