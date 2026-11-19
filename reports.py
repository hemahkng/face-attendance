
from datetime import date, datetime, timedelta

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _format_duration(seconds):
    """Convert seconds into HH:MM format."""
    total_minutes = round(seconds / 60)
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours:02d}:{minutes:02d}"


def build_report(con, start: date, end: date, s: dict):
    start_min = _minutes(s["office_start"])
    limit_min = start_min + int(s["grace_minutes"])
    off_days = {d.strip() for d in s["weekly_off"].split(",") if d.strip()}
    today = date.today()
    now_min = datetime.now().hour * 60 + datetime.now().minute

    emps = con.execute(
        "SELECT emp_id, name, department, active, created_at FROM employees ORDER BY name").fetchall()

    events = con.execute(
        "SELECT emp_id, timestamp, date, event, source FROM attendance WHERE date BETWEEN ? AND ? AND voided = 0 ORDER BY timestamp",
        (start.isoformat(), end.isoformat())).fetchall()

    holidays = {h["day"] for h in con.execute(
        "SELECT day FROM holidays WHERE day BETWEEN ? AND ?", (start.isoformat(), end.isoformat()))}

    leaves = {(l["emp_id"], l["day"]): l for l in con.execute(
        "SELECT emp_id, day, type, note FROM leaves WHERE day BETWEEN ? AND ?", (start.isoformat(), end.isoformat()))}

    by = {}
    for e in events:
        by.setdefault((e["emp_id"], e["date"]), []).append(e)

    rows, summary = [], {}

    for e in emps:
        summary[e["emp_id"]] = {
            "emp_id": e["emp_id"],
            "name": e["name"],
            "department": e["department"] or "",
            "present": 0,
            "late": 0,
            "absent": 0,
            "leave": 0,
            "hours": 0
        }

    d = start
    while d <= end:
        dstr, wd = d.isoformat(), WEEKDAYS[d.weekday()]

        for e in emps:
            evs = by.get((e["emp_id"], dstr), [])

            base = {
                "date": dstr,
                "weekday": wd[:3],
                "emp_id": e["emp_id"],
                "name": e["name"],
                "department": e["department"] or ""
            }

            sm = summary[e["emp_id"]]

            if not evs:
                if not e["active"] or d > today or wd in off_days or dstr in holidays:
                    continue

                if dstr < (e["created_at"] or "")[:10]:
                    continue

                lv = leaves.get((e["emp_id"], dstr))

                if lv:
                    sm["leave"] += 1
                    rows.append({
                        **base,
                        "first_in": "",
                        "last_out": "",
                        "hours": "00:00",
                        "status": "Leave",
                        "note": lv["type"] + (f": {lv['note']}" if lv["note"] else ""),
                        "scans": 0
                    })
                    continue

                if d == today and now_min <= limit_min:
                    status = "Not in yet"
                else:
                    status = "Absent"
                    sm["absent"] += 1

                rows.append({
                    **base,
                    "first_in": "",
                    "last_out": "",
                    "hours": "00:00",
                    "status": status,
                    "note": "",
                    "scans": 0
                })
                continue

            # Calculate completed IN/OUT sessions in seconds
            total_seconds = 0
            open_t, last_out = None, ""

            for ev in evs:
                t = datetime.strptime(ev["timestamp"], "%Y-%m-%d %H:%M:%S")

                if ev["event"] == "IN":
                    open_t = open_t or t

                elif open_t:
                    total_seconds += (t - open_t).total_seconds()
                    open_t = None
                    last_out = ev["timestamp"][11:16]

            first_in = evs[0]["timestamp"]
            fm = int(first_in[11:13]) * 60 + int(first_in[14:16])
            late = fm > limit_min

            note = ""

            if open_t:
                note = "Still in" if d == today else "No OUT recorded"

            if any(ev["source"] == "manual" for ev in evs):
                note = (note + "; " if note else "") + "Includes manual entry"

            # Daily hours in HH:MM format
            hours = _format_duration(total_seconds)

            sm["present"] += 1
            sm["late"] += 1 if late else 0

            # Keep summary internally in seconds
            sm["hours"] += total_seconds

            rows.append({
                **base,
                "first_in": first_in[11:16],
                "last_out": last_out,
                "hours": hours,
                "status": "Late" if late else "Present",
                "note": note,
                "scans": len(evs),
                "late_by": fm - start_min if late else 0
            })

        d += timedelta(days=1)

    summary_rows = [
        v for v in summary.values()
        if v["present"] or v["absent"] or v["leave"]
    ]

    # Convert summary total seconds into HH:MM format
    for v in summary_rows:
        v["hours"] = _format_duration(v["hours"])

    return rows, summary_rows
