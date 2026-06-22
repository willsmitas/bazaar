"""
dedupe_listings.py — Collapse duplicate listings created by double-submits.

A client bug let rapid taps on "Post Listing" insert the same listing several
times. This groups ACTIVE listings that share the same seller, title, and type,
keeps one, and marks the rest as 'removed' (a soft delete — the same thing the
in-app delete does, so nothing is hard-deleted and they simply stop showing up).

Within each group it keeps the earliest listing that has a photo, or the
earliest overall if none do. Only 'active' listings are considered, so rows that
are sold, in-negotiation, or already removed are never touched.

Dry run by default — it only prints what it would do. Add --apply to commit.

    py -m db.dedupe_listings            # preview (no changes)
    py -m db.dedupe_listings --apply    # remove the duplicates
"""
from __future__ import annotations

import sys
from collections import defaultdict

from db.database import SessionLocal
from db.models import Listing, ListingStatus


def _force_utf8_output() -> None:
    """Windows consoles default to cp1252, which can't encode emoji that may
    appear in listing titles. Switch stdout/stderr to UTF-8 where supported."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main(argv=None) -> None:
    _force_utf8_output()
    argv = sys.argv[1:] if argv is None else argv
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return
    apply = "--apply" in argv

    db = SessionLocal()
    try:
        listings = (
            db.query(Listing)
            .filter(Listing.status == ListingStatus.active)
            .order_by(Listing.created_at.asc())
            .all()
        )

        groups: dict[tuple, list] = defaultdict(list)
        for listing in listings:
            groups[(listing.seller_id, listing.title, listing.type)].append(listing)

        dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
        if not dup_groups:
            print("No duplicate active listings found.")
            return

        total = 0
        for (_seller, title, ltype), rows in dup_groups.items():
            rows.sort(key=lambda r: r.created_at)
            keeper = next((r for r in rows if r.thumbnail_url), rows[0])
            dupes = [r for r in rows if r.listing_id != keeper.listing_id]
            total += len(dupes)

            print(f"{title!r} ({ltype.value}) — {len(rows)} copies; "
                  f"keeping {keeper.listing_id} ({keeper.created_at:%Y-%m-%d %H:%M})")
            for d in dupes:
                verb = "removed" if apply else "would remove"
                print(f"    {verb}  {d.listing_id}  {d.created_at:%Y-%m-%d %H:%M}")
                if apply:
                    d.status = ListingStatus.removed

        if apply:
            db.commit()
            print(f"\nDone — removed {total} duplicate listing(s).")
        else:
            print(f"\nDry run — {total} duplicate(s) across {len(dup_groups)} group(s) "
                  f"would be removed. Re-run with --apply to remove them.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
