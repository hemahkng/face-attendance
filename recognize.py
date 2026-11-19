import sqlite3
import time
from datetime import datetime

import cv2
import numpy as np
from insightface.app import FaceAnalysis

DB = "attendance.db"
THRESHOLD = 0.45        # similarity needed to accept a match (higher = stricter)
COOLDOWN_SECONDS = 60   # don't log the same person again within this time
CONFIRM_FRAMES = 3      # must be recognised in this many frames in a row


def init_db():
    con = sqlite3.connect(DB)
    con.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_id TEXT NOT NULL,
            name TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            date TEXT NOT NULL,
            event TEXT NOT NULL
        )
    """)
    con.commit()
    return con


def load_employees(con):
    rows = con.execute("SELECT emp_id, name, embedding FROM employees").fetchall()
    ids = [r[0] for r in rows]
    names = [r[1] for r in rows]
    embs = np.array([np.frombuffer(r[2], dtype=np.float32) for r in rows])
    return ids, names, embs


def log_attendance(con, emp_id, name):
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    # First scan of the day = IN, next scans alternate OUT, IN, OUT...
    count = con.execute(
        "SELECT COUNT(*) FROM attendance WHERE emp_id = ? AND date = ?",
        (emp_id, today),
    ).fetchone()[0]
    event = "IN" if count % 2 == 0 else "OUT"
    con.execute(
        "INSERT INTO attendance (emp_id, name, timestamp, date, event) VALUES (?, ?, ?, ?, ?)",
        (emp_id, name, now.strftime("%Y-%m-%d %H:%M:%S"), today, event),
    )
    con.commit()
    return event, now.strftime("%H:%M:%S")


def main():
    con = init_db()
    ids, names, embs = load_employees(con)
    if len(ids) == 0:
        print("No employees enrolled. Run enroll.py first.")
        return
    print(f"Loaded {len(ids)} employee(s).")

    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(640, 640))

    cap = cv2.VideoCapture(0)
    last_logged = {}     # emp_id -> time of last log
    streak = {}          # emp_id -> consecutive frames matched
    banner = ""
    banner_until = 0
    print("Recognition running. Press Q in the camera window to quit.")

    while True:
        ok, frame = cap.read()
        if not ok:
            print("Cannot read from camera")
            break

        faces = app.get(frame)
        seen_now = set()

        for f in faces:
            x1, y1, x2, y2 = f.bbox.astype(int)
            sims = embs @ f.normed_embedding      # cosine similarity to each employee
            best = int(np.argmax(sims))
            score = float(sims[best])

            if score >= THRESHOLD:
                emp_id, name = ids[best], names[best]
                color = (0, 255, 0)
                label = f"{name} ({score:.2f})"
                seen_now.add(emp_id)
                streak[emp_id] = streak.get(emp_id, 0) + 1

                now = time.time()
                if (streak[emp_id] >= CONFIRM_FRAMES
                        and now - last_logged.get(emp_id, 0) > COOLDOWN_SECONDS):
                    event, t = log_attendance(con, emp_id, name)
                    last_logged[emp_id] = now
                    banner = f"{name}: {event} at {t}"
                    banner_until = now + 4
                    print(banner)
            else:
                color = (0, 0, 255)
                label = f"Unknown ({score:.2f})"

            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, label, (x1, max(y1 - 10, 20)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

        # reset streaks for people not seen this frame
        for emp_id in list(streak):
            if emp_id not in seen_now:
                streak[emp_id] = 0

        if time.time() < banner_until:
            cv2.putText(frame, banner, (10, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)

        cv2.imshow("Attendance", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()