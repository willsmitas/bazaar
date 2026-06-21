"""
add_school.py — Register a new school (a new isolated marketplace).

Creates one row in the `schools` table. The email domains you give here are what
new users register with: anyone signing up with a matching domain joins this
school's marketplace, and the frontend themes itself from the colors + emoji.

    py -m db.add_school --name "Yale University" --slug yale \
        --domains yale.edu --primary "#00356B" --accent "#286DC0" --emoji 🐶

Run `py -m db.add_school --help` for all options.
"""
from __future__ import annotations

import argparse
import re
import sys

from db.database import SessionLocal
from db.models import School


def _force_utf8_output() -> None:
    """Windows consoles default to cp1252, which can't encode emoji in the help
    text or success output. Switch stdout/stderr to UTF-8 where supported."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

_HEX_RE  = re.compile(r"^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$")
_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


# ── argparse type validators ────────────────────────────────────────────────────

def _hex_color(value: str) -> str:
    if not _HEX_RE.match(value):
        raise argparse.ArgumentTypeError(f"{value!r} is not a hex color like #00356B")
    return value.lower()


def _slug(value: str) -> str:
    v = value.strip().lower()
    if not _SLUG_RE.match(v) or len(v) > 63:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a valid slug (lowercase letters, digits, hyphens; max 63 chars)"
        )
    return v


def _domains(value: str) -> list[str]:
    out: list[str] = []
    for raw in re.split(r"[,\s]+", value.strip()):
        d = raw.strip().lstrip("@").lower()
        if not d:
            continue
        if "@" in d or " " in d or "." not in d:
            raise argparse.ArgumentTypeError(f"{raw!r} doesn't look like an email domain")
        out.append(d)
    if not out:
        raise argparse.ArgumentTypeError("provide at least one email domain")
    # de-duplicate while preserving order
    seen: set[str] = set()
    return [d for d in out if not (d in seen or seen.add(d))]


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="py -m db.add_school",
        description="Add a new school (an isolated marketplace) to Bazaar.",
    )
    p.add_argument("--name",     required=True, help="Display name, e.g. 'Yale University'")
    p.add_argument("--slug",     required=True, type=_slug, help="URL slug, e.g. 'yale'")
    p.add_argument("--domains",  required=True, type=_domains,
                   help="Email domain(s), comma-separated, e.g. 'yale.edu,alumni.yale.edu'")
    p.add_argument("--primary",  type=_hex_color, default="#4E3629", help="Primary brand color (hex)")
    p.add_argument("--accent",   type=_hex_color, default="#9E7E38", help="Accent brand color (hex)")
    p.add_argument("--emoji",    default=None, help="Mascot emoji, e.g. '🐶'")
    p.add_argument("--logo-url", dest="logo_url", default=None, help="URL to the school's logo")
    p.add_argument("--inactive", action="store_true",
                   help="Create the school but don't open it for registration yet")
    return p.parse_args(argv)


def main(argv=None) -> None:
    _force_utf8_output()   # must precede _parse_args so --help can print emoji
    args = _parse_args(argv)

    db = SessionLocal()
    try:
        # Reject duplicates so registration stays deterministic.
        if db.query(School).filter(School.slug == args.slug).first():
            raise SystemExit(f"A school with slug '{args.slug}' already exists.")
        if db.query(School).filter(School.name == args.name).first():
            raise SystemExit(f"A school named '{args.name}' already exists.")

        # A domain may map to exactly one school, or registration would be ambiguous.
        for existing in db.query(School).all():
            clash = set(existing.email_domains or []) & set(args.domains)
            if clash:
                raise SystemExit(
                    f"Domain(s) {', '.join(sorted(clash))} already belong to '{existing.name}'."
                )

        school = School(
            name=args.name,
            slug=args.slug,
            email_domains=args.domains,
            primary_color=args.primary,
            accent_color=args.accent,
            emoji=args.emoji,
            logo_url=args.logo_url,
            is_active=not args.inactive,
        )
        db.add(school)
        db.commit()
        db.refresh(school)

        state = "active" if school.is_active else "inactive (not open for registration)"
        print(f"Created school '{school.name}' ({school.slug}) — {state}")
        print(f"  school_id:     {school.school_id}")
        print(f"  email domains: {', '.join(school.email_domains)}")
        print(f"  colors:        {school.primary_color} / {school.accent_color}")
        if school.emoji:
            print(f"  emoji:         {school.emoji}")
        if school.is_active:
            joined = ", ".join("@" + d for d in school.email_domains)
            print(f"\nUsers registering with {joined} now join this marketplace.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
