"""
Reset the per-diem instance: wipe all run data from PostgreSQL and delete the
files on disk (uploaded source workbooks, generated reports, cached rosters).

This is DESTRUCTIVE and irreversible. It is meant for resetting a dev box or a
fresh deployment — not for routine use.

Usage:
    python scripts/reset_data.py              # asks for confirmation
    python scripts/reset_data.py --yes        # skip the confirmation prompt
    python scripts/reset_data.py --keep-cache # keep downloaded rosters (no re-download)
    python scripts/reset_data.py --include-config   # also reset the config table

What it clears:
    DB tables : runs, claims, verdicts, overrides, audit
                (config is preserved unless --include-config is passed)
    Files     : UPLOADS_DIR, REPORTS_DIR, and ROSTER_CACHE_DIR (contents only)
                (the roster cache is preserved when --keep-cache is passed, so
                 rosters are not re-downloaded from Google Drive on the next run)

Connection + paths come from the same env vars the app uses (DATABASE_URL,
UPLOADS_DIR, REPORTS_DIR, ROSTER_CACHE_DIR). Run it with the backend venv so
`perdiem` is importable, e.g.:

    backend/.venv/bin/python scripts/reset_data.py
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# Make the `perdiem` package importable regardless of the current directory.
_BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import text  # noqa: E402

from perdiem.config import settings  # noqa: E402
from perdiem.db.session import SessionLocal, engine  # noqa: E402

# Truncated together with CASCADE, so FK order does not matter.
_DATA_TABLES = ["runs", "claims", "verdicts", "overrides", "audit"]
_CONFIG_TABLE = "config"


def _safe_db_url(url: str) -> str:
    """Hide the password when echoing the connection target."""
    if "@" not in url:
        return url
    prefix, host = url.rsplit("@", 1)
    if ":" in prefix:
        prefix = prefix.rsplit(":", 1)[0] + ":***"
    return f"{prefix}@{host}"


def clear_tables(include_config: bool) -> None:
    tables = _DATA_TABLES + ([_CONFIG_TABLE] if include_config else [])
    table_list = ", ".join(tables)
    session = SessionLocal()
    try:
        session.execute(text(f"TRUNCATE {table_list} RESTART IDENTITY CASCADE"))
        session.commit()
        print(f"  Truncated tables: {table_list}")
    except Exception as exc:
        session.rollback()
        print(f"  ERROR truncating tables: {exc}")
        raise
    finally:
        session.close()


def clear_dir(path_str: str, label: str) -> None:
    """Delete every entry inside a directory, leaving the directory itself."""
    if not path_str:
        print(f"  {label}: not configured, skipped")
        return
    path = Path(path_str)
    if not path.exists():
        print(f"  {label}: {path} does not exist, skipped")
        return
    removed = 0
    for entry in path.iterdir():
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()
        removed += 1
    print(f"  {label}: cleared {removed} item(s) from {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Wipe all per-diem run data and files.")
    parser.add_argument("--yes", "-y", action="store_true", help="skip the confirmation prompt")
    parser.add_argument(
        "--keep-cache",
        action="store_true",
        help="preserve ROSTER_CACHE_DIR so rosters aren't re-downloaded from Drive",
    )
    parser.add_argument(
        "--include-config",
        action="store_true",
        help="also truncate the config table (resets app settings to defaults)",
    )
    args = parser.parse_args()

    print("This will PERMANENTLY delete:")
    tables = _DATA_TABLES + ([_CONFIG_TABLE] if args.include_config else [])
    print(f"  DB    : {', '.join(tables)}")
    print(f"  DB url: {_safe_db_url(settings.database_url)}")
    print(f"  Files : {settings.uploads_dir}")
    print(f"          {settings.reports_dir}")
    print()

    # Decide the cache: --keep-cache forces keep; --yes is non-interactive and
    # honours the flag (default = delete). Otherwise ask, defaulting to KEEP so a
    # dev who hasn't read the docs doesn't accidentally trigger a Drive re-download.
    keep_cache = args.keep_cache
    if not keep_cache and not args.yes:
        ans = input(
            f"Also delete the roster cache ({settings.roster_cache_dir})?\n"
            "Keeping it avoids re-downloading rosters from Google Drive. Delete it? [y/N]: "
        ).strip().lower()
        keep_cache = ans not in ("y", "yes")

    if keep_cache:
        print(f"\nRoster cache will be KEPT: {settings.roster_cache_dir}")
    else:
        print(f"\nRoster cache WILL be deleted: {settings.roster_cache_dir}")

    if not args.yes:
        answer = input("Type 'yes' to continue: ").strip().lower()
        if answer != "yes":
            print("Aborted.")
            sys.exit(0)

    print("\nClearing database...")
    clear_tables(args.include_config)

    print("\nClearing files...")
    clear_dir(settings.uploads_dir, "uploads")
    clear_dir(settings.reports_dir, "reports")
    if keep_cache:
        print(f"  roster cache: kept {settings.roster_cache_dir}")
    else:
        clear_dir(settings.roster_cache_dir, "roster cache")

    engine.dispose()
    print("\nDone.")


if __name__ == "__main__":
    main()
