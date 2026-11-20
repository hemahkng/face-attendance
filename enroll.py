import time
import cv2
import numpy as np
from insightface.app import FaceAnalysis
from sqlalchemy import text

from db_connection import engine

SAMPLES_NEEDED = 5


def main():
    emp_id = input("Employee ID: ").strip()
    name = input("Employee name: ").strip()

    if not emp_id or not name:
        print("ID and name are required.")
        return

    consent = (
        input("Has this employee agreed to face data being stored? (y/n): ")
        .strip()
        .lower()
    )

    if consent != "y":
        print("Enrollment cancelled. Consent is required.")
        return

    # Check whether employee already exists in PostgreSQL
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM employees WHERE emp_id = :emp_id"),
            {"emp_id": emp_id},
        ).fetchone()

    if exists:
        if input("This ID already exists. Replace it? (y/n): ").strip().lower() != "y":
            print("Cancelled.")
            return

    print("Loading face model...")
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(640, 640))

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Cannot open camera.")
        return

    samples = []
    last_capture = 0
    message = "Look at the camera. Auto-capturing..."

    print("Look at the camera. Photos are taken automatically. Press Q to quit.")

    try:
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
                samples.append(faces[0].normed_embedding.copy())
                last_capture = now
                message = "Captured! Turn your head slightly."
                print(f"Captured {len(samples)}/{SAMPLES_NEEDED}")

            elif len(faces) == 0:
                message = "No face found."

            elif len(faces) > 1:
                message = "Only one person in the frame, please."

            cv2.putText(
                display,
                f"Captured {len(samples)}/{SAMPLES_NEEDED}",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2,
            )

            cv2.putText(
                display,
                message,
                (10, 65),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 200, 255),
                2,
            )

            cv2.imshow("Enrollment", display)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:
        cap.release()
        cv2.destroyAllWindows()

    if len(samples) < SAMPLES_NEEDED:
        print("Not enough samples. Nothing was saved.")
        return

    # Average the samples into one embedding and normalize it
    emb = np.mean(samples, axis=0)
    emb = emb / np.linalg.norm(emb)

    embedding_bytes = emb.astype(np.float32).tobytes()

    # Insert or update employee in Neon PostgreSQL
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO employees (emp_id, name, embedding)
                    VALUES (:emp_id, :name, :embedding)
                    ON CONFLICT (emp_id)
                    DO UPDATE SET
                        name = EXCLUDED.name,
                        embedding = EXCLUDED.embedding
                """),
                {
                    "emp_id": emp_id,
                    "name": name,
                    "embedding": embedding_bytes,
                },
            )

        print(f"✅ Saved {name} ({emp_id}) to PostgreSQL.")

    except Exception as e:
        print("❌ Failed to save employee:")
        print(e)


if __name__ == "__main__":
    main()
