from datetime import date, datetime, timedelta

WEEKDAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


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
        "SELECT emp_id, name, department, active, created_at "
        "FROM employees ORDER BY name"
    ).fetchall()

    events = con.execute(
        "SELECT emp_id, timestamp, date, event, source "
        "FROM attendance "
        "WHERE date BETWEEN ? AND ? AND voided = 0 "
        "ORDER BY timestamp",
        (start.isoformat(), end.isoformat()),
    ).fetchall()

    holidays = {
        h["day"]
        for h in con.execute(
            "SELECT day FROM holidays WHERE day BETWEEN ? AND ?",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
    }

    leaves = {
        (l["emp_id"], l["day"]): l
        for l in con.execute(
            "SELECT emp_id, day, type, note FROM leaves WHERE day BETWEEN ? AND ?",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
    }

    # Group attendance events by employee and date
    by = {}

    for e in events:
        by.setdefault((e["emp_id"], e["date"]), []).append(e)

    rows, summary = [], {}

    # Initialize employee summary
    for e in emps:
        summary[e["emp_id"]] = {
            "emp_id": e["emp_id"],
            "name": e["name"],
            "department": e["department"] or "",
            "present": 0,
            "late": 0,
            "absent": 0,
            "leave": 0,
            "hours": 0,
        }

    d = start

    while d <= end:
        dstr = d.isoformat()
        wd = WEEKDAYS[d.weekday()]

        for e in emps:
            evs = by.get((e["emp_id"], dstr), [])

            base = {
                "date": dstr,
                "weekday": wd[:3],
                "emp_id": e["emp_id"],
                "name": e["name"],
                "department": e["department"] or "",
            }

            sm = summary[e["emp_id"]]

            # --------------------------------------------------
            # No attendance events
            # --------------------------------------------------
            if not evs:
                # Skip inactive, future, weekly off and holidays
                if not e["active"] or d > today or wd in off_days or dstr in holidays:
                    continue

                # Skip dates before employee joined
                if dstr < (e["created_at"] or "")[:10]:
                    continue

                lv = leaves.get((e["emp_id"], dstr))

                # Leave day
                if lv:
                    sm["leave"] += 1

                    rows.append(
                        {
                            **base,
                            "first_in": "",
                            "last_out": "",
                            "hours": "00:00",
                            "completed_hours": "00:00",
                            "ongoing_hours": "00:00",
                            "total_work_hours": "00:00",
                            "status": "Leave",
                            "note": lv["type"]
                            + (f": {lv['note']}" if lv["note"] else ""),
                            "scans": 0,
                        }
                    )
                    continue

                # Determine Absent / Not in yet
                if d == today and now_min <= limit_min:
                    status = "Not in yet"
                else:
                    status = "Absent"
                    sm["absent"] += 1

                rows.append(
                    {
                        **base,
                        "first_in": "",
                        "last_out": "",
                        "hours": "00:00",
                        "completed_hours": "00:00",
                        "ongoing_hours": "00:00",
                        "total_work_hours": "00:00",
                        "status": status,
                        "note": "",
                        "scans": 0,
                    }
                )

                continue

            # --------------------------------------------------
            # Punch sequence validation + completed hours
            # --------------------------------------------------
            total_seconds = 0
            open_t = None
            first_in = None
            last_out = ""
            validation_errors = []

            for ev in evs:
                event_type = ev["event"]

                t = datetime.strptime(
                    ev["timestamp"],
                    "%Y-%m-%d %H:%M:%S",
                )

                if event_type == "IN":
                    # Capture first IN for late calculation
                    if first_in is None:
                        first_in = ev["timestamp"]

                    if open_t is not None:
                        # IN received while already checked IN
                        validation_errors.append("Duplicate IN")

                        # Ignore duplicate IN; keep original open session
                        continue

                    # Start a new session
                    open_t = t

                elif event_type == "OUT":
                    if open_t is None:
                        # OUT without a matching IN
                        validation_errors.append("OUT without IN")
                        continue

                    # Valid IN -> OUT pair
                    session_seconds = (t - open_t).total_seconds()

                    if session_seconds >= 0:
                        total_seconds += session_seconds
                    else:
                        validation_errors.append("Invalid punch time")

                    open_t = None
                    last_out = ev["timestamp"][11:16]

            # --------------------------------------------------
            # First IN and late calculation
            # --------------------------------------------------
            first_in_time = first_in or ""

            late = False
            fm = 0

            if first_in:
                fm = int(first_in[11:13]) * 60 + int(first_in[14:16])
                late = fm > limit_min

            # --------------------------------------------------
            # Leave lookup
            # --------------------------------------------------
            lv = leaves.get((e["emp_id"], dstr))

            # --------------------------------------------------
            # Notes
            # --------------------------------------------------
            note = ""

            # Ongoing session note
            if open_t:
                note = "Still in" if d == today else "No OUT recorded"

            # Add validation warnings
            if validation_errors:
                warning_text = ", ".join(validation_errors)
                note = (note + "; " if note else "") + "WARNING: " + warning_text

            # Preserve manual attendance note
            if any(ev["source"] == "manual" for ev in evs):
                note = (note + "; " if note else "") + "Includes manual entry"

            # Add leave information to note when attendance exists
            if lv:
                leave_note = lv["type"] + (f": {lv['note']}" if lv["note"] else "")
                note = (note + "; " if note else "") + leave_note

            # --------------------------------------------------
            # Completed working hours
            # --------------------------------------------------
            hours = _format_duration(total_seconds)

            # --------------------------------------------------
            # Ongoing working hours (today only)
            # --------------------------------------------------
            ongoing_seconds = 0

            if open_t and d == today:
                ongoing_seconds = max(
                    0,
                    (datetime.now() - open_t).total_seconds(),
                )

            ongoing_hours = _format_duration(ongoing_seconds)

            # --------------------------------------------------
            # Total working hours = completed + ongoing
            # --------------------------------------------------
            total_work_seconds = total_seconds + ongoing_seconds
            total_work_hours = _format_duration(total_work_seconds)

            # --------------------------------------------------
            # Update employee summary
            # --------------------------------------------------
            # Hours are retained even on leave days.
            # Leave days are not counted as Present or Late.
            if lv:
                sm["leave"] += 1
            else:
                sm["present"] += 1
                sm["late"] += 1 if late else 0

            sm["hours"] += total_work_seconds

            # --------------------------------------------------
            # Daily report row
            # --------------------------------------------------
            rows.append(
                {
                    **base,
                    "first_in": first_in[11:16] if first_in else "",
                    "last_out": last_out,
                    "hours": hours,
                    "completed_hours": hours,
                    "ongoing_hours": ongoing_hours,
                    "total_work_hours": total_work_hours,
                    "status": "Leave" if lv else ("Late" if late else "Present"),
                    "note": note,
                    "scans": len(evs),
                    "late_by": fm - start_min if late else 0,
                }
            )

        d += timedelta(days=1)

    # --------------------------------------------------
    # Final employee summary
    # --------------------------------------------------
    summary_rows = [
        v for v in summary.values() if v["present"] or v["absent"] or v["leave"]
    ]

    # Convert summary total seconds into HH:MM
    for v in summary_rows:
        v["hours"] = _format_duration(v["hours"])

    return rows, summary_rows
