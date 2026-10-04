import multiprocessing as mp
import os
import queue
import threading
import time
from typing import Dict, List, Optional

import cv2
import face_recognition
import numpy as np

from automatic_mafia.camera.source import open_camera
from automatic_mafia.config import (
    DETECTION_FRAME_INTERVAL,
    DETECTION_SCALE,
    MAX_FACES_PER_FRAME,
    POSITION_CENTER_RATIO_THRESHOLD,
    POSITION_IOU_THRESHOLD,
    REGISTER_STABLE_FRAMES,
    TRACK_HOLD_FRAMES,
    TRACK_MAX_MISSING_FRAMES,
    VISIBILITY_LOST_TIMEOUT_SEC,
    WORKER_COUNT_LIMIT,
)
from automatic_mafia.models import BBox, Observation
from automatic_mafia.storage.face_store import FaceStore
from automatic_mafia.storage.session_store import SessionStore
from automatic_mafia.vision.geometry import bbox_iou, center_distance_ratio


def detection_worker(task_queue, result_queue):
    while True:
        task = task_queue.get()
        if task is None:
            break

        frame_id = task["frame_id"]
        small_frame = task["small_frame"]
        rgb_small_frame = small_frame[:, :, ::-1].copy()
        locations = face_recognition.face_locations(rgb_small_frame, model="hog")
        if len(locations) > MAX_FACES_PER_FRAME:
            locations = sorted(
                locations,
                key=lambda box: (box[2] - box[0]) * (box[1] - box[3]),
                reverse=True,
            )[:MAX_FACES_PER_FRAME]
        encodings = face_recognition.face_encodings(rgb_small_frame, locations, num_jitters=1, model="small")
        result_queue.put({"frame_id": frame_id, "locations": locations, "encodings": encodings})


class CameraWorker(threading.Thread):
    def __init__(self, camera_index: int, face_store: FaceStore, session: SessionStore):
        super().__init__(daemon=True)
        self.camera_index = camera_index
        self.face_store = face_store
        self.session = session
        self.registration_active = False
        self.registration_finished = False
        self.stop_event = threading.Event()
        self.frame_queue: "queue.Queue[tuple[np.ndarray, List[Observation], dict]]" = queue.Queue(maxsize=1)
        self.status_queue: "queue.Queue[str]" = queue.Queue(maxsize=4)
        self.cap = None
        self.frame_id = 0
        self.active_observations: List[Observation] = []
        self.recent_tracks: Dict[str, dict] = {}
        self.unknown_tracks: Dict[str, dict] = {}
        self.frame_cache: Dict[int, np.ndarray] = {}
        self.pending_frame_ids = set()
        self.fps = 0.0
        self.task_queue = None
        self.result_queue = None
        self.workers = []
        self.worker_count = max(1, min(WORKER_COUNT_LIMIT, os.cpu_count() or 1))

    def run(self):
        cv2.setNumThreads(os.cpu_count() or 1)
        self.cap = open_camera(self.camera_index)
        if self.cap is None:
            self._status("Камера недоступна или доступ запрещён")
            return

        self.task_queue = mp.Queue(maxsize=self.worker_count)
        self.result_queue = mp.Queue(maxsize=self.worker_count * 2)
        self.workers = [
            mp.Process(target=detection_worker, args=(self.task_queue, self.result_queue), daemon=True)
            for _ in range(self.worker_count)
        ]
        for worker in self.workers:
            worker.start()

        self._status("Камера включена")
        frame_counter = 0
        fps_ts = time.time()

        try:
            while not self.stop_event.is_set():
                ret, frame = self.cap.read()
                if not ret:
                    self._status("Кадры перестали поступать")
                    break

                frame = cv2.flip(frame, 1)
                self._drain_results()

                if self.frame_id % DETECTION_FRAME_INTERVAL == 0 and len(self.pending_frame_ids) < self.worker_count:
                    small_frame = cv2.resize(frame, (0, 0), fx=DETECTION_SCALE, fy=DETECTION_SCALE)
                    try:
                        self.task_queue.put_nowait({"frame_id": self.frame_id, "small_frame": small_frame})
                        self.frame_cache[self.frame_id] = frame.copy()
                        self.pending_frame_ids.add(self.frame_id)
                    except queue.Full:
                        pass

                self._update_player_visibility(time.time())
                display = self._draw_frame(frame.copy(), self.active_observations)
                frame_counter += 1
                now = time.time()
                if now - fps_ts >= 1.0:
                    self.fps = frame_counter / (now - fps_ts)
                    frame_counter = 0
                    fps_ts = now
                self._put_frame(display, self.active_observations, self._metrics())
                self._cleanup_old_tracks()
                self.frame_id += 1
        finally:
            if self.cap is not None:
                self.cap.release()
            self._stop_workers()
            self._status("Камера выключена")

    def _drain_results(self):
        got_result = False
        while True:
            try:
                result = self.result_queue.get_nowait()
            except queue.Empty:
                break
            got_result = True
            frame = self.frame_cache.pop(result["frame_id"], None)
            self.pending_frame_ids.discard(result["frame_id"])
            if frame is None:
                continue
            try:
                self.active_observations = self._process_detection_result(result, frame)
            except Exception as error:
                # A bad registration frame must not terminate the camera thread.
                self._status(f"Ошибка обработки лица: {type(error).__name__}")
                self.active_observations = self._build_held_observations()
        if got_result and not self.active_observations:
            self.active_observations = self._build_held_observations()

    def _process_detection_result(self, result: dict, frame: np.ndarray) -> List[Observation]:
        observations: List[Observation] = []
        used_face_ids = set()
        used_unknown_tracks = set()
        frame_id = int(result["frame_id"])

        for encoding, small_box in zip(result["encodings"], result["locations"]):
            box = self._scale_box(small_box, frame.shape)
            face_img = self._crop_face(frame, box)
            portrait_img = self._crop_portrait(frame, box)
            face_id, distance, kind = self.face_store.recognize(encoding)
            status = kind

            if face_id and face_id in used_face_ids:
                status = "ambiguous"
            elif face_id and status == "known":
                used_face_ids.add(face_id)

            if status == "unknown":
                fallback_id = self._find_recent_id_by_position(box, used_face_ids, frame_id)
                if fallback_id is not None:
                    face_id = fallback_id
                    status = "known"
                    used_face_ids.add(face_id)
                    self.face_store.try_add_encoding(face_id, encoding, face_img, frame_id)

            unknown_track_id = None
            if status == "unknown":
                unknown_track_id = self._match_unknown_track(box, used_unknown_tracks, encoding, face_img, portrait_img)
                used_unknown_tracks.add(unknown_track_id)
                track_info = self.unknown_tracks[unknown_track_id]
                if self.registration_active and track_info["stable_count"] >= REGISTER_STABLE_FRAMES:
                    face_id = self.face_store.add_face(encoding, face_img)
                    saved_portrait = track_info.get("portrait_img")
                    if saved_portrait is None or saved_portrait.size == 0:
                        saved_portrait = portrait_img
                    self.session.add_player(face_id, saved_portrait)
                    used_face_ids.add(face_id)
                    status = "known"
                    del self.unknown_tracks[unknown_track_id]
            elif status == "known" and face_id and self.registration_active and face_id not in self.session.players:
                self.session.add_player(face_id, portrait_img)
                self.face_store.try_add_encoding(face_id, encoding, face_img, frame_id)

            if face_id and status == "known":
                self.recent_tracks[face_id] = {
                    "bbox": box,
                    "last_seen_frame": frame_id,
                    "last_seen_ts": time.time(),
                }

            observations.append(
                Observation(
                    track_id=face_id or unknown_track_id or "",
                    source_id=f"camera:{self.camera_index}",
                    bbox=box,
                    face_id=face_id if status == "known" else None,
                    distance=distance,
                    status=status,
                    label=self._observation_label(face_id, status),
                    face_image=face_img,
                    encoding=encoding,
                    held=False,
                )
            )

        return observations or self._build_held_observations()

    def _build_held_observations(self) -> List[Observation]:
        held = []
        for face_id, info in self.recent_tracks.items():
            if self.frame_id - info["last_seen_frame"] > TRACK_HOLD_FRAMES:
                continue
            if face_id not in self.session.players:
                continue
            held.append(
                Observation(
                    track_id=face_id,
                    source_id=f"camera:{self.camera_index}",
                    bbox=info["bbox"],
                    face_id=face_id,
                    distance=None,
                    status="known",
                    label=self._observation_label(face_id, "known"),
                    held=True,
                )
            )
        return held

    def _find_recent_id_by_position(self, box: BBox, used_ids: set, frame_id: int) -> Optional[str]:
        best_id = None
        best_score = -1.0
        for face_id, info in self.recent_tracks.items():
            if face_id in used_ids:
                continue
            if frame_id - info["last_seen_frame"] > TRACK_MAX_MISSING_FRAMES:
                continue
            iou = bbox_iou(box, info["bbox"])
            center_ratio = center_distance_ratio(box, info["bbox"])
            if iou >= POSITION_IOU_THRESHOLD or center_ratio <= POSITION_CENTER_RATIO_THRESHOLD:
                score = iou - center_ratio * 0.1
                if score > best_score:
                    best_score = score
                    best_id = face_id
        return best_id

    def _match_unknown_track(self, box: BBox, used_tracks: set, encoding, face_img, portrait_img) -> str:
        best_id = None
        best_score = 0.0
        for track_id, info in self.unknown_tracks.items():
            if track_id in used_tracks:
                continue
            score = bbox_iou(box, info["bbox"])
            if score > best_score:
                best_score = score
                best_id = track_id
        if best_id and best_score >= 0.15:
            info = self.unknown_tracks[best_id]
            info["bbox"] = box
            info["stable_count"] += 1
            info["last_seen_frame"] = self.frame_id
            info["encoding"] = encoding
            info["face_img"] = face_img
            info["portrait_img"] = portrait_img
            return best_id
        track_id = f"unknown:{self.frame_id}:{len(self.unknown_tracks)}"
        self.unknown_tracks[track_id] = {
            "bbox": box,
            "stable_count": 1,
            "last_seen_frame": self.frame_id,
            "encoding": encoding,
            "face_img": face_img,
            "portrait_img": portrait_img,
        }
        return track_id

    def _update_player_visibility(self, now: float):
        visible = {obs.face_id for obs in self.active_observations if obs.face_id and obs.status == "known"}
        for face_id, player in self.session.players.items():
            if face_id in visible:
                player.status = "В кадре"
                player.last_seen = now
            elif player.last_seen and now - player.last_seen < VISIBILITY_LOST_TIMEOUT_SEC:
                player.status = "В кадре"
            else:
                player.status = "Временно не виден"

    def _observation_label(self, face_id: Optional[str], status: str) -> str:
        if status == "ambiguous":
            return "Needs confirm"
        if face_id and face_id in self.session.players:
            player = self.session.players[face_id]
            return f"Player {player.number}" + (f" / {player.name}" if player.name else "")
        if status == "known":
            return "Known, not in game"
        if self.registration_finished:
            return "Unknown, locked"
        return "Unknown"

    def _draw_frame(self, frame: np.ndarray, observations: List[Observation]) -> np.ndarray:
        for obs in observations:
            top, right, bottom, left = obs.bbox
            color = (70, 220, 110)
            if obs.status == "ambiguous":
                color = (0, 210, 255)
            elif obs.status == "unknown":
                color = (90, 90, 255)
            elif obs.held:
                color = (120, 160, 220)
            cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
            cv2.rectangle(frame, (left, max(0, top - 32)), (min(frame.shape[1], left + 300), top), color, -1)
            cv2.putText(frame, obs.label, (left + 8, max(22, top - 9)), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (10, 14, 20), 2)
        return frame

    def _scale_box(self, box, shape) -> BBox:
        top, right, bottom, left = box
        scale = 1.0 / DETECTION_SCALE
        height, width = shape[:2]
        return (
            max(0, int(top * scale)),
            min(width, int(right * scale)),
            min(height, int(bottom * scale)),
            max(0, int(left * scale)),
        )

    def _crop_face(self, frame: np.ndarray, box: BBox) -> np.ndarray:
        top, right, bottom, left = box
        pad = 24
        top = max(0, top - pad)
        left = max(0, left - pad)
        bottom = min(frame.shape[0], bottom + pad)
        right = min(frame.shape[1], right + pad)
        return frame[top:bottom, left:right].copy()

    def _crop_portrait(self, frame: np.ndarray, box: BBox) -> np.ndarray:
        top, right, bottom, left = box
        face_width = max(1, right - left)
        face_height = max(1, bottom - top)
        portrait_top = max(0, int(top - face_height * 0.65))
        portrait_bottom = min(frame.shape[0], int(bottom + face_height * 1.75))
        portrait_left = max(0, int(left - face_width * 0.90))
        portrait_right = min(frame.shape[1], int(right + face_width * 0.90))
        return frame[portrait_top:portrait_bottom, portrait_left:portrait_right].copy()

    def _cleanup_old_tracks(self):
        stale_faces = [
            face_id
            for face_id, info in self.recent_tracks.items()
            if self.frame_id - info["last_seen_frame"] > TRACK_MAX_MISSING_FRAMES
        ]
        for face_id in stale_faces:
            del self.recent_tracks[face_id]
        stale_unknown = [
            track_id
            for track_id, info in self.unknown_tracks.items()
            if self.frame_id - info["last_seen_frame"] > TRACK_MAX_MISSING_FRAMES
        ]
        for track_id in stale_unknown:
            del self.unknown_tracks[track_id]

    def _metrics(self) -> dict:
        visible_registered = len({obs.face_id for obs in self.active_observations if obs.face_id in self.session.players})
        unknown = len([obs for obs in self.active_observations if obs.status == "unknown"])
        ambiguous = len([obs for obs in self.active_observations if obs.status == "ambiguous"])
        return {
            "registered": len(self.session.players),
            "visible_registered": visible_registered,
            "unknown": unknown,
            "ambiguous": ambiguous,
            "fps": self.fps,
        }

    def _put_frame(self, frame: np.ndarray, observations: List[Observation], metrics: dict):
        item = (frame, observations, metrics)
        try:
            if self.frame_queue.full():
                self.frame_queue.get_nowait()
            self.frame_queue.put_nowait(item)
        except queue.Empty:
            pass

    def _status(self, text: str):
        try:
            if self.status_queue.full():
                self.status_queue.get_nowait()
            self.status_queue.put_nowait(text)
        except queue.Empty:
            pass

    def stop(self):
        self.stop_event.set()

    def assign_track_to_player(self, track_id: str, face_id: str) -> bool:
        if track_id in self.unknown_tracks:
            track = self.unknown_tracks[track_id]
            self.face_store.try_add_encoding(face_id, track["encoding"], track["face_img"], self.frame_id)
            self.recent_tracks[face_id] = {
                "bbox": track["bbox"],
                "last_seen_frame": self.frame_id,
                "last_seen_ts": time.time(),
            }
            del self.unknown_tracks[track_id]
        elif face_id not in self.recent_tracks:
            return False
        if face_id in self.session.players:
            self.session.players[face_id].status = "В кадре"
            self.session.players[face_id].last_seen = time.time()
            self.session.save()
        return True

    def _stop_workers(self):
        if self.task_queue is not None:
            for _ in self.workers:
                sent_stop = False
                while not sent_stop:
                    try:
                        self.task_queue.put_nowait(None)
                        sent_stop = True
                    except queue.Full:
                        try:
                            self.task_queue.get_nowait()
                        except queue.Empty:
                            sent_stop = True
        for worker in self.workers:
            worker.join(timeout=2.0)
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=1.0)
