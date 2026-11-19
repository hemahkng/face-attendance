"""Daily database backups. Runs inside the server, so no extra scheduler is needed."""
import shutil
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

import database as dbm

BACKUP_DIR = dbm.BASE_DIR / "backups"
KEEP = 30
PATTERN = "attendance_????-??-??_??????.db"


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


def make_backup(extra_dir: str = "") -> dict:
    """Consistent copy of the live database (safe while the server is running)."""
    BACKUP_DIR.mkdir(exist_ok=True)
    name = f"attendance_{datetime.now():%Y-%m-%d_%H%M%S}.db"
    dest = BACKUP_DIR / name
    src, dst = sqlite3.connect(dbm.DB_PATH), sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    _prune(BACKUP_DIR)
    result = {"file": name, "size_kb": round(dest.stat().st_size / 1024), "copied_to": None, "copy_error": None}
    if extra_dir:
        try:
            shutil.copy2(dest, Path(extra_dir) / name)
            _prune(Path(extra_dir))
            result["copied_to"] = extra_dir
        except OSError as e:
            result["copy_error"] = f"Could not copy to {extra_dir}: {e.strerror or e}"
    return result


def list_backups(limit: int = 8):
    if not BACKUP_DIR.exists():
        return []
    out = []
    for f in sorted(BACKUP_DIR.glob(PATTERN), reverse=True)[:limit]:
        out.append({"name": f.name, "size_kb": round(f.stat().st_size / 1024),
                    "time": f.name[11:21] + " " + f.name[22:24] + ":" + f.name[24:26]})
    return out


def _loop():
    time.sleep(30)
    while True:
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            if not any(BACKUP_DIR.glob(f"attendance_{today}_*.db")):
                with dbm.db() as con:
                    extra = dbm.get_settings(con).get("backup_folder", "")
                r = make_backup(extra)
                print(f"Backup created: {r['file']}" + (f" | {r['copy_error']}" if r["copy_error"] else ""))
        except Exception as e:                      # never let a backup problem stop the server
            print("Backup failed:", e)
        time.sleep(600)


def start_scheduler():
    threading.Thread(target=_loop, daemon=True, name="backup").start()
