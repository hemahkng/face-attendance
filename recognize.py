import time
from datetime import datetime

import cv2
import numpy as np
from insightface.app import FaceAnalysis
from sqlalchemy import text

from db_connection import engine

THRESHOLD = 0.45
COOLDOWN_SECONDS = 60
CONFIRM_FRAMES = 3


def load_employees():
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT emp_id, name, embedding FROM employees")
        ).fetchall()

    ids = [r.emp_id for r in rows]
    names = [r.name for r in rows]

    if not rows:
        return ids, names, np.empty((0, 512), dtype=np.float32)

    embs = np.array([np.frombuffer(bytes(r.embedding), dtype=np.float32) for r in rows])

    return ids, names, embs


def log_attendance(emp_id, name):
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    with engine.begin() as conn:
        count = conn.execute(
            text("""
                SELECT COUNT(*)
                FROM attendance
                WHERE emp_id = :emp_id
                  AND date = :today
            """),
            {
                "emp_id": emp_id,
                "today": today,
            },
        ).scalar()

        event = "IN" if count % 2 == 0 else "OUT"

        conn.execute(
            text("""
                INSERT INTO attendance
                    (emp_id, name, timestamp, date, event)
                VALUES
                    (:emp_id, :name, :timestamp, :date, :event)
            """),
            {
                "emp_id": emp_id,
                "name": name,
                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                "date": today,
                "event": event,
            },
        )

    return event, now.strftime("%H:%M:%S")


def main():
    ids, names, embs = load_employees()

    if len(ids) == 0:
        print("No employees enrolled. Run enroll.py first.")
        return

    print(f"Loaded {len(ids)} employee(s) from PostgreSQL.")

    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(640, 640))

    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("Cannot open camera.")
        return

    last_logged = {}
    streak = {}
    banner = ""
    banner_until = 0

    print("Recognition running. Press Q in the camera window to quit.")

    try:
        while True:
            ok, frame = cap.read()

            if not ok:
                print("Cannot read from camera")
                break

            faces = app.get(frame)
            seen_now = set()

            for f in faces:
                x1, y1, x2, y2 = f.bbox.astype(int)

                sims = embs @ f.normed_embedding
                best = int(np.argmax(sims))
                score = float(sims[best])

                if score >= THRESHOLD:
                    emp_id, name = ids[best], names[best]
                    color = (0, 255, 0)
                    label = f"{name} ({score:.2f})"

                    seen_now.add(emp_id)
                    streak[emp_id] = streak.get(emp_id, 0) + 1

                    now = time.time()

                    if (
                        streak[emp_id] >= CONFIRM_FRAMES
                        and now - last_logged.get(emp_id, 0) > COOLDOWN_SECONDS
                    ):
                        event, t = log_attendance(emp_id, name)

                        last_logged[emp_id] = now
                        banner = f"{name}: {event} at {t}"
                        banner_until = now + 4
                        print(banner)

                else:
                    color = (0, 0, 255)
                    label = f"Unknown ({score:.2f})"

                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(
                    frame,
                    label,
                    (x1, max(y1 - 10, 20)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    color,
                    2,
                )

            # Reset streaks for people not seen in this frame
            for emp_id in list(streak):
                if emp_id not in seen_now:
                    streak[emp_id] = 0

            if time.time() < banner_until:
                cv2.putText(
                    frame,
                    banner,
                    (10, 35),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.9,
                    (0, 255, 0),
                    2,
                )

            cv2.imshow("Attendance", frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
