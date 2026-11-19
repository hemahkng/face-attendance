import base64
import threading

import cv2
import numpy as np

_app = None
_lock = threading.Lock()


def _get_app():
    global _app
    if _app is None:
        from insightface.app import FaceAnalysis
        # Only the three models we use (skips age/gender and 106-point landmarks) and a smaller
        # detection size: about a third faster per frame on a CPU, same recognition results.
        _app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"],
                            allowed_modules=["detection", "recognition", "landmark_3d_68"])
        _app.prepare(ctx_id=0, det_size=(320, 320))
    return _app


def has_pose():
    """True when the model pack provides head pose (needed for the liveness check)."""
    return _app is not None and "landmark_3d_68" in _app.models


def warm_up():
    with _lock:
        _get_app()


def decode_image(data_url: str):
    if len(data_url) > 3_000_000:
        return None
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]
    try:
        raw = base64.b64decode(data_url)
    except Exception:
        return None
    return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)


def analyze(img):
    with _lock:
        return _get_app().get(img)


def face_area(f):
    x1, y1, x2, y2 = f.bbox
    return float((x2 - x1) * (y2 - y1))


def _pick(faces, min_width):
    faces = [x for x in faces if float(x.det_score) >= 0.5]
    if not faces:
        return None, "no_face"
    faces.sort(key=face_area, reverse=True)
    if len(faces) > 1 and face_area(faces[1]) > 0.5 * face_area(faces[0]):
        return None, "multiple"
    best = faces[0]
    if (best.bbox[2] - best.bbox[0]) < min_width:
        return None, "too_far"
    return best, None


def single_face(img, min_width=90):
    """Detection + pose + identity vector. Returns (face, error_code); error_code is None when OK."""
    return _pick(analyze(img), min_width)


def single_face_light(img, min_width=90):
    """Detection + head pose only (no identity vector): about 3x cheaper, used during the head turn."""
    from insightface.app.common import Face
    with _lock:
        app = _get_app()
        bboxes, kpss = app.det_model.detect(img, max_num=0, metric="default")
        faces = []
        for i in range(bboxes.shape[0]):
            fc = Face(bbox=bboxes[i, 0:4], kps=kpss[i] if kpss is not None else None, det_score=bboxes[i, 4])
            app.models["landmark_3d_68"].get(img, fc)
            faces.append(fc)
    return _pick(faces, min_width)


def embed(img, face):
    """Add the identity vector to a face found by single_face_light."""
    with _lock:
        _get_app().models["recognition"].get(img, face)
    return face
