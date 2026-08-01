"""Return the lab to a clean, freshly-migrated state.

Run with::

    python scripts/reset_demo.py                 # asks before deleting anything
    python scripts/reset_demo.py --yes           # no prompt
    python scripts/reset_demo.py --yes --seed    # reset, then load the demo data
    python scripts/reset_demo.py --keep-uploads  # database only

What it removes:

* every table in the configured database, then re-applies the Alembic
  migrations from scratch;
* the files under ``data/uploads/`` and ``data/exports/``.

What it never touches:

* ``data/sample/`` - the committed demo datasets. Those are inputs, not state.
  Regenerate them with the ``scripts/generate_*_sample_data.py`` scripts.
* ``.env`` and anything outside the project's own data directory.

**This deletes data.** It is aimed at a local demo database. It refuses to run
against ``ENVIRONMENT=production`` without ``--force``, and it prints the
database it is about to drop - never the credentials - so a wrong ``.env`` is
visible before anything is lost rather than after.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings  # noqa: E402
from app.models import Base  # noqa: E402  (registers every table)
from app.models.session import engine  # noqa: E402


def database_label() -> str:
    """A log-safe description of the target database - never the password."""
    url = settings.database_url
    if url.startswith("sqlite"):
        path = url.split("///")[-1]
        return f"SQLite file {path}"
    scheme = url.split("://", 1)[0]
    host = url.rsplit("@", 1)[-1] if "@" in url else "(unspecified host)"
    return f"{scheme} database at {host}"


def drop_everything() -> None:
    """Drop every table the models know about, plus Alembic's own bookkeeping.

    ``Base.metadata.drop_all`` alone would leave ``alembic_version`` behind,
    and the next ``alembic upgrade head`` would then believe the schema was
    already at head and create nothing - a reset that produces an empty
    database the application cannot use.
    """
    from sqlalchemy import text

    Base.metadata.drop_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))


def apply_migrations() -> int:
    """Run ``alembic upgrade head`` in a subprocess and return its exit code."""
    print("Applying migrations (alembic upgrade head)...")
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        check=False,
    )
    return completed.returncode


def clear_directory(directory: Path) -> int:
    """Delete the contents of ``directory``, keeping the directory and .gitkeep."""
    if not directory.is_dir():
        return 0
    removed = 0
    for entry in directory.iterdir():
        if entry.name == ".gitkeep":
            continue
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.unlink(missing_ok=True)
        removed += 1
    return removed


def confirm(prompt: str) -> bool:
    """Ask for an explicit yes on an interactive terminal."""
    if not sys.stdin.isatty():
        print("Not an interactive terminal; re-run with --yes to confirm.")
        return False
    return input(f"{prompt} [y/N] ").strip().lower() in {"y", "yes"}


def main() -> int:
    """Reset the demo environment."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--yes", action="store_true", help="Do not ask for confirmation.")
    parser.add_argument(
        "--keep-uploads",
        action="store_true",
        help="Reset the database but keep the uploaded and exported files.",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Run scripts/seed_database.py afterwards to load the demo data.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow the reset to run against a non-local ENVIRONMENT.",
    )
    args = parser.parse_args()

    print("SAP AI Application Lab - demo reset\n")
    print(f"  Environment: {settings.environment}")
    print(f"  Database:    {database_label()}")
    if not args.keep_uploads:
        print(f"  Uploads:     {settings.upload_dir}")
        print(f"  Exports:     {settings.export_dir}")
    print()

    if settings.environment != "local" and not args.force:
        print(
            f"Refusing to reset with ENVIRONMENT={settings.environment}. "
            "This script deletes data. Re-run with --force if that is really "
            "what you want."
        )
        return 2

    if not args.yes and not confirm("Delete all of the above and re-migrate?"):
        print("Nothing was changed.")
        return 1

    print("Dropping tables...")
    drop_everything()

    exit_code = apply_migrations()
    if exit_code != 0:
        print("\nThe migrations failed. The database is empty; fix the error and re-run.")
        return exit_code

    if not args.keep_uploads:
        settings.ensure_directories()
        uploads = clear_directory(settings.upload_dir)
        exports = clear_directory(settings.export_dir)
        print(f"Removed {uploads} upload(s) and {exports} export(s).")

    print("\nThe database is empty and at the latest migration.")

    if args.seed:
        print()
        completed = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "seed_database.py"), "--yes"],
            cwd=PROJECT_ROOT,
            check=False,
        )
        if completed.returncode != 0:
            return completed.returncode
    else:
        print("Next: python scripts/seed_database.py    (loads the bundled demo data)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
