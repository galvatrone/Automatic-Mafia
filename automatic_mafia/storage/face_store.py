import pickle
import uuid
from typing import Dict, List, Optional, Tuple

import cv2
import face_recognition
import numpy as np

from automatic_mafia.config import (
    BASE_FILE,
    DATA_DIR,
    ENCODING_ADD_AMBIGUOUS_MARGIN,
    ENCODING_ADD_COOLDOWN_FRAMES,
    ENCODING_ADD_MAX_DISTANCE,
    ENCODING_ADD_MIN_DISTANCE,
    FACE_MATCH_THRESHOLD,
    FACES_DIR,
    MAX_ENCODINGS_PER_FACE,
    MIN_FACE_CROP_SIZE,
    UNKNOWN_MARGIN,
)


class FaceStore:
    """Self-contained copy of the FaceReg face database logic."""

    def __init__(self):
        DATA_DIR.mkdir(exist_ok=True)
        FACES_DIR.mkdir(exist_ok=True)
        self.known_faces: Dict[str, dict] = {}
        self.known_encodings: List[np.ndarray] = []
        self.known_ids: List[str] = []
        self.last_add_frame: Dict[str, int] = {}
        self.load()

    def load(self):
        if BASE_FILE.exists():
            with BASE_FILE.open("rb") as face_file:
                self.known_faces = pickle.load(face_file)
        else:
            self.known_faces = {}
        self.rebuild_index()

    def save(self):
        with BASE_FILE.open("wb") as face_file:
            pickle.dump(self.known_faces, face_file)
        self.rebuild_index()

    def rebuild_index(self):
        self.known_encodings = []
        self.known_ids = []
        for face_id, data in self.known_faces.items():
            for encoding in data.get("encodings", []):
                self.known_encodings.append(encoding)
                self.known_ids.append(face_id)

    def recognize(self, encoding: np.ndarray) -> Tuple[Optional[str], Optional[float], str]:
        if not self.known_encodings:
            return None, None, "unknown"
        distances = face_recognition.face_distance(self.known_encodings, encoding)
        ordered = np.argsort(distances)
        best_index = int(ordered[0])
        best_distance = float(distances[best_index])
        if best_distance >= FACE_MATCH_THRESHOLD:
            return None, best_distance, "unknown"
        if len(ordered) > 1:
            second_distance = float(distances[int(ordered[1])])
            if second_distance - best_distance < UNKNOWN_MARGIN:
                return self.known_ids[best_index], best_distance, "ambiguous"
        return self.known_ids[best_index], best_distance, "known"

    def add_face(self, encoding: np.ndarray, face_image: np.ndarray) -> str:
        face_id = str(uuid.uuid4())
        self.known_faces[face_id] = {
            "name": f"Mafia participant {len(self.known_faces) + 1}",
            "encodings": [encoding],
        }
        face_dir = FACES_DIR / face_id
        face_dir.mkdir(exist_ok=True)
        cv2.imwrite(str(face_dir / "main.jpg"), face_image)
        self.save()
        return face_id

    def add_encoding(self, face_id: str, encoding: np.ndarray):
        if face_id not in self.known_faces:
            return
        encodings = self.known_faces[face_id].setdefault("encodings", [])
        if encodings:
            min_distance = float(np.min(face_recognition.face_distance(encodings, encoding)))
            if min_distance < ENCODING_ADD_MIN_DISTANCE:
                return
        encodings.append(encoding)
        self.save()

    def try_add_encoding(self, face_id: str, encoding: np.ndarray, face_image: np.ndarray, frame_id: int) -> bool:
        if face_id not in self.known_faces:
            return False
        if not self._face_crop_is_good(face_image):
            return False
        encodings = self.known_faces[face_id].setdefault("encodings", [])
        min_distance = 1.0
        if encodings:
            min_distance = float(np.min(face_recognition.face_distance(encodings, encoding)))
        if min_distance <= ENCODING_ADD_MIN_DISTANCE:
            return False
        if min_distance >= ENCODING_ADD_MAX_DISTANCE:
            return False
        if self._too_close_to_other_identity(face_id, encoding):
            return False
        frame_gap = frame_id - self.last_add_frame.get(face_id, -10**9)
        if frame_gap < ENCODING_ADD_COOLDOWN_FRAMES:
            return False
        encodings.append(encoding)
        self._limit_encodings(encodings)
        face_dir = FACES_DIR / face_id
        face_dir.mkdir(exist_ok=True)
        cv2.imwrite(str(face_dir / f"{uuid.uuid4().hex[:8]}.jpg"), face_image)
        self.last_add_frame[face_id] = frame_id
        self.save()
        return True

    def _too_close_to_other_identity(self, face_id: str, encoding: np.ndarray) -> bool:
        own_distances = []
        other_distances = []
        for known_id, known_encoding in zip(self.known_ids, self.known_encodings):
            distance = float(face_recognition.face_distance([known_encoding], encoding)[0])
            if known_id == face_id:
                own_distances.append(distance)
            else:
                other_distances.append(distance)
        if not own_distances or not other_distances:
            return False
        own_best = min(own_distances)
        other_best = min(other_distances)
        return other_best < FACE_MATCH_THRESHOLD and other_best - own_best < ENCODING_ADD_AMBIGUOUS_MARGIN

    def _limit_encodings(self, encodings: List[np.ndarray]):
        if len(encodings) <= MAX_ENCODINGS_PER_FACE:
            return
        keep = [encodings[0]]
        rest = encodings[1:]
        step = max(1, len(rest) // max(1, MAX_ENCODINGS_PER_FACE - 1))
        keep.extend(rest[::step][: MAX_ENCODINGS_PER_FACE - 1])
        encodings[:] = keep

    def _face_crop_is_good(self, face_image: np.ndarray) -> bool:
        if face_image is None or face_image.size == 0:
            return False
        height, width = face_image.shape[:2]
        return height >= MIN_FACE_CROP_SIZE and width >= MIN_FACE_CROP_SIZE
