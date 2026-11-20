import hashlib
import hmac
import io
import os
import re
import secrets
import threading
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import List, Optional

import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

import backup
import database as dbm
import face_engine as engine
import reports

BASE = dbm.BASE_DIR
STATIC = BASE / "static"
EMB_BYTES = 512 * 4
DUPLICATE_SIM = 0.60  # same face enrolled under another ID
write_lock = threading.Lock()


# ---------- password + secret key ----------
def hash_password(pw: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex()
    return f"{salt}${h}"


def check_password(pw: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(pw, salt), stored)


def secret_key() -> str:
    p = BASE / "secret.key"
    if not p.exists():
        p.write_text(secrets.token_hex(32))
    return p.read_text().strip()


# ---------- in-memory gallery of enrolled faces ----------
class Gallery:
    def __init__(self):
        self.ids, self.names, self.embs = [], [], np.zeros((0, 512), np.float32)

    def reload(self, con):
        rows = con.execute(
            "SELECT emp_id, name, embedding FROM employees WHERE active = 1"
        ).fetchall()
        rows = [r for r in rows if r["embedding"] and len(r["embedding"]) == EMB_BYTES]
        self.ids = [r["emp_id"] for r in rows]
        self.names = [r["name"] for r in rows]
        self.embs = (
            np.array([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
            if rows
            else np.zeros((0, 512), np.float32)
        )

    def best(self, emb, exclude=None):
        if len(self.ids) == 0:
            return None, 0.0
        sims = self.embs @ emb
        if exclude in self.ids:
            sims[self.ids.index(exclude)] = -1
        i = int(np.argmax(sims))
        return i, float(sims[i])


gallery = Gallery()
streaks = {}  # emp_id -> (count, last_seen_time)
login_fails = {}  # ip -> [timestamps]


@asynccontextmanager
async def lifespan(app):
    dbm.init_db()
    with dbm.db() as con:
        s = dbm.get_settings(con)
        if "admin_password" not in s:
            dbm.set_setting(
                con,
                "admin_password",
                hash_password(os.environ.get("ADMIN_PASSWORD", "admin123")),
            )
            dbm.set_setting(con, "password_is_default", "1")
        gallery.reload(con)
    backup.start_scheduler()
    print("Loading face model (first run downloads ~300 MB)...")
    engine.warm_up()
    print("Ready. Open http://localhost:8000")
    yield


app = FastAPI(title="Face Attendance", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware, secret_key=secret_key(), max_age=8 * 3600, same_site="lax"
)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def require_admin(request: Request):
    if not request.session.get("admin"):
        raise HTTPException(401, "Please log in.")


# ---------- pages ----------
@app.get("/")
def home():
    return RedirectResponse("/kiosk")


@app.get("/kiosk")
def kiosk_page():
    return FileResponse(STATIC / "kiosk.html")


@app.get("/login")
def login_page():
    return FileResponse(STATIC / "login.html")


@app.get("/admin")
def admin_page(request: Request):
    if not request.session.get("admin"):
        return RedirectResponse("/login")
    return FileResponse(STATIC / "admin.html")


# ---------- auth ----------
class LoginBody(BaseModel):
    password: str


@app.post("/api/login")
def login(body: LoginBody, request: Request):
    ip = request.client.host if request.client else "?"
    recent = [t for t in login_fails.get(ip, []) if time.time() - t < 300]
    if len(recent) >= 5:
        raise HTTPException(429, "Too many attempts. Try again in 5 minutes.")
    with dbm.db() as con:
        stored = dbm.get_settings(con)["admin_password"]
    if not check_password(body.password, stored):
        login_fails[ip] = recent + [time.time()]
        raise HTTPException(401, "Wrong password.")
    login_fails.pop(ip, None)
    request.session["admin"] = True
    return {"ok": True}


@app.post("/api/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


# ---------- kiosk: recognise a frame and log attendance ----------
class FrameBody(BaseModel):
    image: str


MESSAGES = {
    "no_face": "Look at the camera",
    "multiple": "One person at a time, please",
    "too_far": "Move closer to the camera",
}


LIVENESS_FRONT_YAW = 15  # must start roughly facing the camera
LIVENESS_TURN_YAW = 18  # degrees of head turn that proves a live person
LIVENESS_WINDOW = 15  # seconds allowed to complete the turn
LIVENESS_RELAX = (
    0.12  # a turned face matches a little lower, so relax the threshold at the end
)
STREAK_WINDOW = 8  # (liveness off) max seconds between two recognised frames
pending = {}  # emp_id -> {"base": yaw, "start": time, "dev": max turn so far, "fails": n}


def _last_event(con, emp_id):
    today = datetime.now().strftime("%Y-%m-%d")
    return con.execute(
        "SELECT timestamp, event FROM attendance WHERE emp_id = ? AND date = ? AND voided = 0 "
        "ORDER BY timestamp DESC LIMIT 1",
        (emp_id, today),
    ).fetchone()


def _already(name, last_ev, min_gap):
    """Return the 'already marked' reply if the last punch is too recent, else None."""
    if last_ev is None:
        return None
    last_t = datetime.strptime(last_ev["timestamp"], "%Y-%m-%d %H:%M:%S")
    if (datetime.now() - last_t).total_seconds() / 60 < min_gap:
        t = last_ev["timestamp"][11:16]
        return {
            "status": "already",
            "name": name,
            "event": last_ev["event"],
            "time": t,
            "message": f"{name}, already marked {last_ev['event']} at {t}",
        }
    return None


def _mark(emp_id, name, min_gap):
    with write_lock, dbm.db() as con:
        last_ev = _last_event(con, emp_id)
        dup = _already(name, last_ev, min_gap)
        if dup:
            return dup
        event = "IN" if last_ev is None or last_ev["event"] == "OUT" else "OUT"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        con.execute(
            "INSERT INTO attendance (emp_id, name, timestamp, date, event) VALUES (?,?,?,?,?)",
            (emp_id, name, ts, ts[:10], event),
        )
    streaks.pop(emp_id, None)
    return {
        "status": "marked",
        "name": name,
        "event": event,
        "time": ts[11:16],
        "message": f"{name}, checked {event} at {ts[11:16]}",
    }


@app.post("/api/recognize")
def recognize(body: FrameBody):
    img = engine.decode_image(body.image)
    if img is None:
        return {"status": "no_face", "message": MESSAGES["no_face"]}
    with dbm.db() as con:
        s = dbm.get_settings(con)
    thr, min_gap = float(s["threshold"]), int(s["min_gap_minutes"])
    use_liveness = s.get("liveness", "1") == "1" and engine.has_pose()
    now = time.time()
    for k in [k for k, p in pending.items() if now - p["start"] > LIVENESS_WINDOW]:
        pending.pop(k)

    # ---- stage 2: a head turn is in progress. Cheap frames (pose only), identity re-checked at the end.
    if use_liveness and pending:
        emp_id = min(pending, key=lambda k: pending[k]["start"])
        p = pending[emp_id]
        face, err = engine.single_face_light(img)
        if err:
            return {"status": err, "message": MESSAGES[err]}
        p["dev"] = max(p["dev"], abs(float(face.pose[1]) - p["base"]))
        if p["dev"] < LIVENESS_TURN_YAW:
            return {
                "status": "challenge",
                "message": "Slowly turn your head to one side",
            }
        engine.embed(img, face)
        i, score = gallery.best(face.normed_embedding)
        if i is None or gallery.ids[i] != emp_id or score < thr - LIVENESS_RELAX:
            p["fails"] += 1
            if p["fails"] >= 3:  # a different person finished the turn
                pending.pop(emp_id)
                return {"status": "unknown", "message": "Face not recognised"}
            return {"status": "challenge", "message": "Now look back at the camera"}
        pending.pop(emp_id)
        return _mark(emp_id, gallery.names[i], min_gap)

    # ---- stage 1: identify the person
    t0 = time.time()
    face, err = engine.single_face(img)
    if time.time() - t0 > 2:
        print(
            f"Slow frame: {time.time() - t0:.1f}s (the PC is busy or the CPU is slow)"
        )
    if err:
        return {"status": err, "message": MESSAGES[err]}
    i, score = gallery.best(face.normed_embedding)
    if i is None or score < thr:
        return {"status": "unknown", "message": "Face not recognised"}
    emp_id, name = gallery.ids[i], gallery.names[i]

    with dbm.db() as con:
        dup = _already(name, _last_event(con, emp_id), min_gap)
    if dup:
        return dup

    if use_liveness:
        yaw = float(face.pose[1])
        if abs(yaw) > LIVENESS_FRONT_YAW:
            return {"status": "face_front", "message": "Look straight at the camera"}
        pending[emp_id] = {"base": yaw, "start": now, "dev": 0.0, "fails": 0}
        return {"status": "challenge", "message": "Slowly turn your head to one side"}

    count, last = streaks.get(emp_id, (0, 0))
    count = count + 1 if now - last < STREAK_WINDOW else 1
    streaks[emp_id] = (count, now)
    if count < 2:
        return {"status": "verifying", "message": f"Verifying {name}..."}
    return _mark(emp_id, name, min_gap)


# ---------- employees ----------
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")


class EnrollBody(BaseModel):
    emp_id: str
    name: str
    department: str = ""
    consent: bool = False
    replace: bool = False
    images: List[str]


class DepartmentBody(BaseModel):
    department: str = ""


@app.get("/api/admin/employees", dependencies=[Depends(require_admin)])
def list_employees():
    with dbm.db() as con:
        rows = con.execute(
            "SELECT emp_id, name, department, active, created_at FROM employees ORDER BY active DESC, name"
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/admin/employees", dependencies=[Depends(require_admin)])
def enroll(body: EnrollBody):
    emp_id, name = body.emp_id.strip(), body.name.strip()
    if not ID_RE.match(emp_id):
        raise HTTPException(
            400, "Employee ID may use letters, numbers, - and _ (max 20)."
        )
    if not name:
        raise HTTPException(400, "Name is required.")
    if not body.consent:
        raise HTTPException(
            400, "The employee must consent to storing their face data."
        )
    if len(body.images) < 3:
        raise HTTPException(400, "At least 3 photos are needed.")

    embs, problems = [], set()
    for data in body.images[:8]:
        img = engine.decode_image(data)
        if img is None:
            continue
        face, err = engine.single_face(img, min_width=110)
        if err:
            problems.add(err)
        else:
            embs.append(face.normed_embedding)
    if len(embs) < 3:
        hint = (
            "Only one person should be in view and the face should fill more of the frame."
            if problems
            else "Photos could not be read."
        )
        raise HTTPException(400, f"Only {len(embs)} clear photos were captured. {hint}")

    emb = np.mean(embs, axis=0)
    emb = (emb / np.linalg.norm(emb)).astype(np.float32)

    with write_lock, dbm.db() as con:
        exists = con.execute(
            "SELECT 1 FROM employees WHERE emp_id = ?", (emp_id,)
        ).fetchone()
        if exists and not body.replace:
            raise HTTPException(
                409, "This ID already exists. Tick 'Replace existing' to re-enrol."
            )
        i, score = gallery.best(emb, exclude=emp_id)
        if i is not None and score >= DUPLICATE_SIM:
            raise HTTPException(
                409,
                f"This face is already enrolled as {gallery.names[i]} ({gallery.ids[i]}).",
            )
        if exists:
            con.execute(
                "UPDATE employees SET name=?, department=?, embedding=?, active=1 WHERE emp_id=?",
                (name, body.department.strip(), emb.tobytes(), emp_id),
            )
        else:
            con.execute(
                "INSERT INTO employees (emp_id, name, department, embedding, active) VALUES (?,?,?,?,1)",
                (emp_id, name, body.department.strip(), emb.tobytes()),
            )
        gallery.reload(con)
    return {"ok": True, "samples": len(embs)}


@app.patch(
    "/api/admin/employees/{emp_id}/department", dependencies=[Depends(require_admin)]
)
def update_employee_department(emp_id: str, body: DepartmentBody):
    department = body.department.strip()

    with write_lock, dbm.db() as con:
        employee = con.execute(
            "SELECT emp_id FROM employees WHERE emp_id = ?", (emp_id,)
        ).fetchone()

        if not employee:
            raise HTTPException(404, "Employee not found.")

        con.execute(
            "UPDATE employees SET department = ? WHERE emp_id = ?",
            (department, emp_id),
        )

    return {"ok": True, "emp_id": emp_id, "department": department}


@app.delete("/api/admin/employees/{emp_id}", dependencies=[Depends(require_admin)])
def remove_employee(emp_id: str):
    """Deactivates the employee and erases their face data. Attendance history is kept."""
    with write_lock, dbm.db() as con:
        con.execute(
            "UPDATE employees SET active = 0, embedding = x'' WHERE emp_id = ?",
            (emp_id,),
        )
        gallery.reload(con)
    return {"ok": True}


# ---------- reports ----------
def parse_range(start: Optional[str], end: Optional[str]):
    try:
        e = date.fromisoformat(end) if end else date.today()
        s = date.fromisoformat(start) if start else e
    except ValueError:
        raise HTTPException(400, "Dates must look like 2026-11-18.")
    if s > e:
        raise HTTPException(400, "Start date is after the end date.")
    if (e - s).days > 92:
        raise HTTPException(400, "Choose a range of 93 days or less.")
    return s, e


@app.get("/api/admin/dashboard", dependencies=[Depends(require_admin)])
def dashboard():
    with dbm.db() as con:
        s = dbm.get_settings(con)
        rows, _ = reports.build_report(con, date.today(), date.today(), s)
        total = con.execute(
            "SELECT COUNT(*) FROM employees WHERE active = 1"
        ).fetchone()[0]
    count = lambda st: sum(1 for r in rows if r["status"] == st)
    with dbm.db() as con:
        hol = con.execute(
            "SELECT name FROM holidays WHERE day = ?", (date.today().isoformat(),)
        ).fetchone()
    return {
        "holiday": hol["name"] if hol else "",
        "date": date.today().isoformat(),
        "company": s["company_name"],
        "total": total,
        "present": count("Present") + count("Late"),
        "late": count("Late"),
        "absent": count("Absent") + count("Not in yet"),
        "leave": count("Leave"),
        "inside": sum(1 for r in rows if r["note"].startswith("Still in")),
        "rows": rows,
        "default_password": s.get("password_is_default") == "1",
    }


@app.get("/api/admin/report", dependencies=[Depends(require_admin)])
def report(start: Optional[str] = None, end: Optional[str] = None):
    s, e = parse_range(start, end)
    with dbm.db() as con:
        rows, summary = reports.build_report(con, s, e, dbm.get_settings(con))
    return {"rows": rows, "summary": summary}


@app.get("/api/admin/events", dependencies=[Depends(require_admin)])
def events(day: Optional[str] = None):
    day = day or date.today().isoformat()
    with dbm.db() as con:
        rows = con.execute(
            "SELECT id, emp_id, name, timestamp, event, source, note, voided FROM attendance "
            "WHERE date = ? ORDER BY timestamp",
            (day,),
        ).fetchall()
    return [dict(r) for r in rows]


class PunchBody(BaseModel):
    emp_id: str
    day: str
    time: str
    event: str
    reason: str


@app.post("/api/admin/attendance", dependencies=[Depends(require_admin)])
def add_punch(b: PunchBody):
    """Manually add attendance only if the resulting punch sequence is valid."""
    if b.event not in ("IN", "OUT"):
        raise HTTPException(400, "Event must be IN or OUT.")

    if len(b.reason.strip()) < 3:
        raise HTTPException(400, "Please give a short reason for the change.")

    try:
        when = datetime.strptime(f"{b.day} {b.time}", "%Y-%m-%d %H:%M")
    except ValueError:
        raise HTTPException(400, "Use a valid date and a time like 09:30.")

    if when > datetime.now():
        raise HTTPException(400, "That time is in the future.")

    with write_lock, dbm.db() as con:
        emp = con.execute(
            "SELECT name FROM employees WHERE emp_id = ?", (b.emp_id,)
        ).fetchone()

        if not emp:
            raise HTTPException(404, "Unknown employee.")

        # Get existing non-cancelled punches for this employee and date
        existing = con.execute(
            """
            SELECT timestamp, event
            FROM attendance
            WHERE emp_id = ?
              AND date = ?
              AND voided = 0
            ORDER BY timestamp
            """,
            (b.emp_id, b.day),
        ).fetchall()

        # Add proposed punch in memory for validation
        punches = [(r["timestamp"], r["event"]) for r in existing]

        proposed_timestamp = when.strftime("%Y-%m-%d %H:%M:%S")

        # Reject punches with an exact duplicate timestamp
        if any(timestamp == proposed_timestamp for timestamp, event in punches):
            raise HTTPException(409, "A punch already exists at this exact time.")

        punches.append((proposed_timestamp, b.event))

        # Sort chronologically
        punches.sort(key=lambda x: x[0])

        # Validate IN/OUT sequence
        open_in = False

        for timestamp, event in punches:
            if event == "IN":
                if open_in:
                    raise HTTPException(
                        409,
                        "Invalid attendance sequence: duplicate IN. "
                        "An OUT is required before another IN.",
                    )
                open_in = True

            elif event == "OUT":
                if not open_in:
                    raise HTTPException(
                        409, "Invalid attendance sequence: OUT without IN."
                    )
                open_in = False

        # Save only after sequence validation passes
        con.execute(
            """
            INSERT INTO attendance
            (emp_id, name, timestamp, date, event, source, note)
            VALUES (?, ?, ?, ?, ?, 'manual', ?)
            """,
            (
                b.emp_id,
                emp["name"],
                proposed_timestamp,
                b.day,
                b.event,
                b.reason.strip(),
            ),
        )

    return {"ok": True}


class VoidBody(BaseModel):
    reason: str


@app.post(
    "/api/admin/attendance/{punch_id}/void", dependencies=[Depends(require_admin)]
)
def void_punch(punch_id: int, b: VoidBody):
    """Cancels a punch. The row is kept (marked voided) so there is an audit trail."""
    if len(b.reason.strip()) < 3:
        raise HTTPException(400, "Please give a short reason for the change.")
    with write_lock, dbm.db() as con:
        row = con.execute(
            "SELECT note, voided FROM attendance WHERE id = ?", (punch_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Punch not found.")
        if row["voided"]:
            raise HTTPException(409, "Already cancelled.")
        note = (
            (row["note"] + " | " if row["note"] else "")
            + "Cancelled: "
            + b.reason.strip()
        )
        con.execute(
            "UPDATE attendance SET voided = 1, note = ? WHERE id = ?", (note, punch_id)
        )
    return {"ok": True}


@app.get("/api/admin/export", dependencies=[Depends(require_admin)])
def export(start: Optional[str] = None, end: Optional[str] = None):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    s, e = parse_range(start, end)
    with dbm.db() as con:
        rows, summary = reports.build_report(con, s, e, dbm.get_settings(con))

    wb = Workbook()
    ws = wb.active
    ws.title = "Daily"
    ws.append(
        [
            "Date",
            "Day",
            "Employee ID",
            "Name",
            "Department",
            "First IN",
            "Last OUT",
            "Hours",
            "Status",
            "Note",
        ]
    )
    for r in rows:
        ws.append(
            [
                r["date"],
                r["weekday"],
                r["emp_id"],
                r["name"],
                r["department"],
                r["first_in"],
                r["last_out"],
                r["hours"],
                r["status"],
                r["note"],
            ]
        )
    ws2 = wb.create_sheet("Summary")
    ws2.append(
        [
            "Employee ID",
            "Name",
            "Department",
            "Days present",
            "Days late",
            "Days absent",
            "Days on leave",
            "Total hours",
        ]
    )
    for r in summary:
        ws2.append(
            [
                r["emp_id"],
                r["name"],
                r["department"],
                r["present"],
                r["late"],
                r["absent"],
                r["leave"],
                r["hours"],
            ]
        )
    for sheet in (ws, ws2):
        for c in sheet[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="0F5C57")
        for col in sheet.columns:
            sheet.column_dimensions[col[0].column_letter].width = max(
                12, max(len(str(c.value or "")) for c in col) + 2
            )
        sheet.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"attendance_{s}_{e}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ---------- settings ----------
class SettingsBody(BaseModel):
    company_name: str
    office_start: str
    grace_minutes: int
    threshold: float
    min_gap_minutes: int
    weekly_off: List[str]
    liveness: bool = True
    backup_folder: str = ""


@app.get("/api/admin/settings", dependencies=[Depends(require_admin)])
def get_settings():
    with dbm.db() as con:
        s = dbm.get_settings(con)
    return {
        "company_name": s["company_name"],
        "office_start": s["office_start"],
        "grace_minutes": int(s["grace_minutes"]),
        "threshold": float(s["threshold"]),
        "min_gap_minutes": int(s["min_gap_minutes"]),
        "weekly_off": [d for d in s["weekly_off"].split(",") if d],
        "liveness": s.get("liveness", "1") == "1",
        "backup_folder": s.get("backup_folder", ""),
    }


@app.post("/api/admin/settings", dependencies=[Depends(require_admin)])
def save_settings(b: SettingsBody):
    if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", b.office_start):
        raise HTTPException(400, "Office start must look like 09:30.")
    if not 0 <= b.grace_minutes <= 120:
        raise HTTPException(400, "Grace period must be 0 to 120 minutes.")
    if not 0.25 <= b.threshold <= 0.80:
        raise HTTPException(400, "Match threshold must be between 0.25 and 0.80.")
    if not 1 <= b.min_gap_minutes <= 240:
        raise HTTPException(400, "Minimum gap must be 1 to 240 minutes.")
    if any(d not in reports.WEEKDAYS for d in b.weekly_off):
        raise HTTPException(400, "Unknown weekday.")
    folder = b.backup_folder.strip().strip('"')
    if folder:
        problem = backup.check_folder(folder)
        if problem:
            raise HTTPException(400, f"Backup folder: {problem}")
    with dbm.db() as con:
        for k, v in [
            ("company_name", b.company_name.strip() or "FACENEX"),
            ("office_start", b.office_start),
            ("grace_minutes", b.grace_minutes),
            ("threshold", b.threshold),
            ("min_gap_minutes", b.min_gap_minutes),
            ("weekly_off", ",".join(b.weekly_off)),
            ("liveness", "1" if b.liveness else "0"),
            ("backup_folder", folder),
        ]:
            dbm.set_setting(con, k, v)
    return {"ok": True}


class PasswordBody(BaseModel):
    current: str
    new: str


@app.post("/api/admin/password", dependencies=[Depends(require_admin)])
def change_password(b: PasswordBody):
    if len(b.new) < 8:
        raise HTTPException(400, "New password must be at least 8 characters.")
    with dbm.db() as con:
        if not check_password(b.current, dbm.get_settings(con)["admin_password"]):
            raise HTTPException(400, "Current password is wrong.")
        dbm.set_setting(con, "admin_password", hash_password(b.new))
        dbm.set_setting(con, "password_is_default", "0")
    return {"ok": True}


# ---------- backups ----------
@app.post("/api/admin/backup", dependencies=[Depends(require_admin)])
def backup_now():
    with dbm.db() as con:
        extra = dbm.get_settings(con).get("backup_folder", "")
    return backup.make_backup(extra)


@app.get("/api/admin/backups", dependencies=[Depends(require_admin)])
def backups():
    return backup.list_backups()


# ---------- holidays ----------
class HolidayBody(BaseModel):
    day: str
    name: str


@app.get("/api/admin/holidays", dependencies=[Depends(require_admin)])
def list_holidays():
    with dbm.db() as con:
        rows = con.execute("SELECT day, name FROM holidays ORDER BY day").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/admin/holidays", dependencies=[Depends(require_admin)])
def add_holiday(b: HolidayBody):
    try:
        date.fromisoformat(b.day)
    except ValueError:
        raise HTTPException(400, "Choose a valid date.")
    name = b.name.strip()
    if not 1 <= len(name) <= 60:
        raise HTTPException(400, "Give the holiday a name (up to 60 characters).")
    with dbm.db() as con:
        con.execute(
            "INSERT OR REPLACE INTO holidays (day, name) VALUES (?, ?)", (b.day, name)
        )
    return {"ok": True}


@app.delete("/api/admin/holidays/{day}", dependencies=[Depends(require_admin)])
def remove_holiday(day: str):
    with dbm.db() as con:
        con.execute("DELETE FROM holidays WHERE day = ?", (day,))
    return {"ok": True}


# ---------- leave ----------
LEAVE_TYPES = ("Casual", "Sick", "Other")


class LeaveBody(BaseModel):
    emp_id: str
    start: str
    end: str
    type: str = "Casual"
    note: str = ""


@app.get("/api/admin/leaves", dependencies=[Depends(require_admin)])
def list_leaves():
    lo = (date.today() - timedelta(days=30)).isoformat()
    hi = (date.today() + timedelta(days=90)).isoformat()
    with dbm.db() as con:
        rows = con.execute(
            "SELECT l.id, l.emp_id, e.name, l.day, l.type, l.note FROM leaves l "
            "LEFT JOIN employees e ON e.emp_id = l.emp_id WHERE l.day BETWEEN ? AND ? ORDER BY l.day, e.name",
            (lo, hi),
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/admin/leaves", dependencies=[Depends(require_admin)])
def add_leave(b: LeaveBody):
    try:
        s, e = date.fromisoformat(b.start), date.fromisoformat(b.end)
    except ValueError:
        raise HTTPException(400, "Choose valid dates.")
    if s > e:
        raise HTTPException(400, "The end date is before the start date.")
    if (e - s).days > 30:
        raise HTTPException(400, "Add leave in blocks of 31 days or less.")
    if b.type not in LEAVE_TYPES:
        raise HTTPException(400, "Unknown leave type.")
    with dbm.db() as con:
        emp = con.execute(
            "SELECT 1 FROM employees WHERE emp_id = ? AND active = 1", (b.emp_id,)
        ).fetchone()
        if not emp:
            raise HTTPException(404, "Unknown employee.")
        n, d = 0, s
        while d <= e:
            con.execute(
                "INSERT OR REPLACE INTO leaves (emp_id, day, type, note) VALUES (?,?,?,?)",
                (b.emp_id, d.isoformat(), b.type, b.note.strip()[:80]),
            )
            n, d = n + 1, d + timedelta(days=1)
    return {"ok": True, "days": n}


@app.delete("/api/admin/leaves/{leave_id}", dependencies=[Depends(require_admin)])
def remove_leave(leave_id: int):
    with dbm.db() as con:
        con.execute("DELETE FROM leaves WHERE id = ?", (leave_id,))
    return {"ok": True}
