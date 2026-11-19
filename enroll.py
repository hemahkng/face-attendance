import sqlite3
import time
import cv2
import numpy as np
from insightface.app import FaceAnalysis

DB = "attendance.db"
SAMPLES_NEEDED = 5


def init_db():
    con = sqlite3.connect(DB)
    con.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            emp_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            embedding BLOB NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    con.commit()
    return con


def main():
    con = init_db()

    emp_id = input("Employee ID: ").strip()
    name = input("Employee name: ").strip()
    if not emp_id or not name:
        print("ID and name are required.")
        return

    consent = input("Has this employee agreed to face data being stored? (y/n): ").strip().lower()
    if consent != "y":
        print("Enrollment cancelled. Consent is required.")
        return

    exists = con.execute("SELECT 1 FROM employees WHERE emp_id = ?", (emp_id,)).fetchone()
    if exists:
        if input("This ID already exists. Replace it? (y/n): ").strip().lower() != "y":
            print("Cancelled.")
            return

    print("Loading face model...")
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(640, 640))

    cap = cv2.VideoCapture(0)
    samples = []
    last_capture = 0
    message = "Look at the camera. Auto-capturing..."
    print("Look at the camera. Photos are taken automatically. Press Q to quit.")

    while len(samples) < SAMPLES_NEEDED:
        ok, frame = cap.read()
        if not ok:
            print("Cannot read from camera")
            break

        display = frame.copy()
        faces = app.get(frame)
        for f in faces:
            x1, y1, x2, y2 = f.bbox.astype(int)
            cv2.rectangle(display, (x1, y1), (x2, y2), (0, 255, 0), 2)

        now = time.time()
        if len(faces) == 1 and now - last_capture > 1.5:
            samples.append(faces[0].normed_embedding)
            last_capture = now
            message = "Captured! Turn your head slightly."
            print(f"Captured {len(samples)}/{SAMPLES_NEEDED}")
        elif len(faces) == 0:
            message = "No face found."
        elif len(faces) > 1:
            message = "Only one person in the frame, please."

        cv2.putText(display, f"Captured {len(samples)}/{SAMPLES_NEEDED}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.putText(display, message, (10, 65),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)
        cv2.imshow("Enrollment", display)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()

    if len(samples) < SAMPLES_NEEDED:
        print("Not enough samples. Nothing was saved.")
        return

    # Average the samples into one embedding and normalize it
    emb = np.mean(samples, axis=0)
    emb = emb / np.linalg.norm(emb)

    con.execute(
        "INSERT OR REPLACE INTO employees (emp_id, name, embedding) VALUES (?, ?, ?)",
        (emp_id, name, emb.astype(np.float32).tobytes()),
    )
    con.commit()
    print(f"Saved {name} ({emp_id}).")


if __name__ == "__main__":
    main()