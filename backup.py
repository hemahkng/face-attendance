"""Daily PostgreSQL backups using pg_dump. Runs inside the server."""

import gzip
import shutil
import subprocess
import tempfile
import threading
import time
import os
from datetime import datetime
from pathlib import Path

import database as dbm

BASE_DIR = Path(__file__).resolve().parent
BACKUP_DIR = BASE_DIR / "backups"
KEEP = 30
PATTERN = "attendance_????-??-??_??????.sql.gz"


def check_folder(path: str):
    """Return an error message if the folder can't be used for backups, else None."""
    p = Path(path)

    if not p.is_dir():
        return "That folder does not exist."

    try:
        probe = p / ".write_test"
        probe.write_text("ok")
        probe.unlink()
    except OSError:
        return "Cannot write to that folder."

    return None


def _prune(folder: Path):
    files = sorted(folder.glob(PATTERN))

    for old in files[:-KEEP]:
        try:
            old.unlink()
        except OSError:
            pass


def _get_pg_dump():
    """Find pg_dump executable."""
    exe = shutil.which("pg_dump")

    if exe:
        return exe

    # Windows fallback
    fallback = Path(r"C:\Program Files\PostgreSQL\19\bin\pg_dump.exe")

    if fallback.exists():
        return str(fallback)

    raise FileNotFoundError(
        "pg_dump was not found. Install PostgreSQL command-line tools "
        "or add PostgreSQL bin folder to PATH."
    )


def _get_database_url():
    """Get PostgreSQL URL from environment without exposing credentials."""
    from dotenv import load_dotenv

    load_dotenv()

    url = os.getenv("DATABASE_URL")

    if not url:
        raise RuntimeError("DATABASE_URL is missing from .env")

    # Remove SQLAlchemy-specific driver name for pg_dump
    url = url.replace(
        "postgresql+psycopg://",
        "postgresql://",
        1,
    )

    return url


def make_backup(extra_dir: str = "") -> dict:
    """Create a compressed PostgreSQL backup using pg_dump."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    name = f"attendance_{datetime.now():%Y-%m-%d_%H%M%S}.sql.gz"
    dest = BACKUP_DIR / name
    temp_dest = BACKUP_DIR / (name + ".tmp")

    pg_dump_path = _get_pg_dump()
    database_url = _get_database_url()

    command = [
        pg_dump_path,
        "--dbname",
        database_url,
        "--no-owner",
        "--no-privileges",
    ]

    try:
        # Keep stderr in a temporary file to avoid pipe deadlocks.
        with tempfile.TemporaryFile() as error_file:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=error_file,
            )

            try:
                with gzip.open(temp_dest, "wb") as gz:
                    shutil.copyfileobj(process.stdout, gz)
            finally:
                if process.stdout:
                    process.stdout.close()

            return_code = process.wait()

            error_file.seek(0)
            error_text = (
                error_file.read()
                .decode(
                    "utf-8",
                    errors="replace",
                )
                .strip()
            )

        if return_code != 0:
            raise RuntimeError(error_text or f"pg_dump failed with code {return_code}")

        # Move temporary file into its final name only after success.
        temp_dest.replace(dest)

    except Exception:
        try:
            temp_dest.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    _prune(BACKUP_DIR)

    result = {
        "file": name,
        "size_kb": round(dest.stat().st_size / 1024),
        "copied_to": None,
        "copy_error": None,
    }

    # Optional second backup location
    if extra_dir:
        try:
            target_folder = Path(extra_dir)

            shutil.copy2(dest, target_folder / name)
            _prune(target_folder)

            result["copied_to"] = extra_dir

        except OSError as e:
            result["copy_error"] = f"Could not copy to {extra_dir}: {e.strerror or e}"

    return result


def list_backups(limit: int = 8):
    """Return recent backups for the dashboard."""
    if not BACKUP_DIR.exists():
        return []

    out = []

    for f in sorted(
        BACKUP_DIR.glob(PATTERN),
        reverse=True,
    )[:limit]:
        name = f.name

        out.append(
            {
                "name": name,
                "size_kb": round(f.stat().st_size / 1024),
                "time": (name[11:21] + " " + name[22:24] + ":" + name[24:26]),
            }
        )

    return out


def _loop():
    time.sleep(30)

    while True:
        try:
            today = datetime.now().strftime("%Y-%m-%d")

            # Only one automatic backup per day
            if not any(BACKUP_DIR.glob(f"attendance_{today}_*.sql.gz")):
                with dbm.db() as con:
                    extra = dbm.get_settings(con).get(
                        "backup_folder",
                        "",
                    )

                result = make_backup(extra)

                print(
                    f"Backup created: {result['file']}"
                    + (f" | {result['copy_error']}" if result["copy_error"] else "")
                )

        except Exception as e:
            # Backup failure must never stop the application.
            print("Backup failed:", e)

        time.sleep(600)


def start_scheduler():
    threading.Thread(
        target=_loop,
        daemon=True,
        name="backup",
    ).start()
