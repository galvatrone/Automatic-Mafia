import argparse, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QFormLayout, QLabel, QListWidget, QPushButton, QSplitter, QVBoxLayout, QWidget
from shared.capture import CaptureThread
from shared.config import load_json
from shared.observations import HandObservation
from shared.ui import ExperimentWindow, frame_pixmap

class BodyTracks:
    def __init__(self): self.next_id=1; self.centers={}
    def assign(self, poses):
        assigned=[]
        for pose in poses:
            indices=[i for i in (11,12,23,24) if i<len(pose)]; center=(sum(pose[i].x for i in indices)/len(indices),sum(pose[i].y for i in indices)/len(indices))
            candidates=sorted((((center[0]-old[0])**2+(center[1]-old[1])**2)**.5,track_id) for track_id,old in self.centers.items())
            if candidates and candidates[0][0]<.18: track_id=candidates[0][1]
            else: track_id=self.next_id; self.next_id+=1
            self.centers[track_id]=center; assigned.append(track_id)
        return assigned

class GestureAdapter:
    def __init__(self, mode, cfg):
        self.mode = mode; self.hands = None; self.pose = None; self.error = ""; self.cfg = cfg; self.gesture_state = {}; self.body_tracks=BodyTracks()
        if mode.startswith("MediaPipe"):
            try:
                import mediapipe as mp
                self.mp = mp
                # Tasks API needs downloaded .task files; keep the requirement explicit.
                hand = Path(__file__).parent / "models/hand_landmarker.task"
                pose = Path(__file__).parent / "models/pose_landmarker_lite.task"
                if not hand.exists() or not pose.exists(): raise RuntimeError("нет MediaPipe weights. Запустите ../setup_experiments.sh --models")
                from mediapipe.tasks import python
                from mediapipe.tasks.python import vision
                base = python.BaseOptions(model_asset_path=str(hand))
                self.hands = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(base_options=base, running_mode=vision.RunningMode.VIDEO, num_hands=4, min_hand_detection_confidence=cfg.get("min_detection_confidence", .6), min_tracking_confidence=cfg.get("min_tracking_confidence", .6)))
                pbase = python.BaseOptions(model_asset_path=str(pose))
                self.pose = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(base_options=pbase, running_mode=vision.RunningMode.VIDEO, num_poses=4))
            except Exception as exc: raise RuntimeError(f"MediaPipe недоступен: {exc}") from exc
        else:
            raise RuntimeError("MMPose/RTMPose подключается отдельным адаптером после выбора task-моделей")
    def process(self, frame, timestamp_ms):
        import cv2
        mp_image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        result = self.hands.detect_for_video(mp_image, timestamp_ms)
        pose_result = self.pose.detect_for_video(mp_image, timestamp_ms)
        pose_ids=self.body_tracks.assign(pose_result.pose_landmarks); pose_wrists = []
        for body_id, pose in zip(pose_ids,pose_result.pose_landmarks):
            if len(pose) > 16:
                pose_wrists.append((body_id, (pose[15].x, pose[15].y), (pose[16].x, pose[16].y)))
        output = []
        for landmarks, handed in zip(result.hand_landmarks, result.handedness):
            points = [(p.x, p.y, p.z) for p in landmarks]
            extended = self.extended_fingers(points, handed[0].category_name)
            count = sum(extended)
            raw_gesture = "открытая ладонь" if count >= 4 else "кулак" if count == 0 else "указательный жест" if extended[1] and sum(extended[2:]) == 0 else f"поднято пальцев: {count}"
            vector = (points[8][0]-points[5][0], points[8][1]-points[5][1]) if len(points) > 8 else None
            wrist = points[0] if points else (0, 0, 0)
            owner = None
            if pose_wrists:
                distances = sorted((((wrist[0]-point[0])**2+(wrist[1]-point[1])**2) ** .5, body_id) for body_id,left,right in pose_wrists for point in (left,right))
                distance, body_id = distances[0]
                second, second_body_id = distances[1] if len(distances) > 1 else (1.0, body_id)
                cross_body_ambiguous = second_body_id != body_id and second <= self.cfg.get("owner_cross_body_ambiguity", .06)
                if distance <= self.cfg.get("owner_max_distance", .18) and second - distance >= self.cfg.get("owner_ambiguity_margin", .015) and not cross_body_ambiguous: owner = f"body-{body_id}"
            key = f"{handed[0].category_name}:{owner or 'unknown'}"; gesture = self.hold(key, raw_gesture, timestamp_ms)
            output.append(HandObservation(points, handed[0].category_name, owner, gesture, count, vector))
        poses = [[(p.x,p.y,p.z) for p in pose] for pose in pose_result.pose_landmarks]
        return output, poses
    @staticmethod
    def extended_fingers(points, handedness):
        if len(points) < 21: return [False] * 5
        def distance(a,b): return ((points[a][0]-points[b][0])**2+(points[a][1]-points[b][1])**2) ** .5
        fingers = [distance(4,0) > distance(3,0) * 1.08]
        fingers.extend(distance(tip,0) > distance(pip,0) * 1.12 for tip,pip in [(8,6),(12,10),(16,14),(20,18)])
        return fingers
    def hold(self, key, gesture, timestamp_ms):
        state = self.gesture_state.get(key)
        if not state or state["candidate"] != gesture:
            self.gesture_state[key] = {"candidate": gesture, "since": timestamp_ms, "stable": state["stable"] if state else None}
            return state["stable"] if state and state["stable"] else f"{gesture} (удержание)"
        if timestamp_ms - state["since"] >= self.cfg.get("hold_ms", 250): state["stable"] = gesture
        return state["stable"] or f"{gesture} (удержание)"
    def close(self):
        if self.hands:
            self.hands.close(); self.hands = None
        if self.pose:
            self.pose.close(); self.pose = None

class Window(ExperimentWindow):
    def __init__(self, source, cfg):
        super().__init__("Automatic Mafia · эксперимент hands_gestures")
        self.cfg = cfg; self.thread = None; self.adapter = None
        self.canvas = QLabel("Нет кадра"); self.canvas.setAlignment(Qt.AlignCenter); self.canvas.setMinimumSize(760, 480)
        self.list = QListWidget(); self.status = QLabel("Выберите технологию. Жесты не связаны с игрой.")
        self.mode = QComboBox(); self.mode.addItems(["MediaPipe Hand + Pose Landmarker", "MMPose / RTMPose (optional)"])
        self.src = QLabel(source); start = QPushButton("Запустить"); stop = QPushButton("Остановить"); stop.setEnabled(False)
        start.clicked.connect(lambda: self.start(source, start, stop)); stop.clicked.connect(lambda: self.stop(start, stop))
        form = QFormLayout(); form.addRow("Источник", self.src); form.addRow("Технология", self.mode); form.addRow(start, stop)
        side = QWidget(); sl = QVBoxLayout(side); sl.addLayout(form); sl.addWidget(QLabel("Распознанные жесты")); sl.addWidget(self.list); sl.addWidget(self.status)
        split = QSplitter(); split.addWidget(self.canvas); split.addWidget(side); split.setSizes([850, 350]); self.setCentralWidget(split)
    def start(self, source, start, stop):
        try: self.adapter = GestureAdapter(self.mode.currentText(), self.cfg)
        except Exception as exc: self.status.setText(str(exc)); return
        self.thread = CaptureThread(source, processor=self.process); self.thread.packet_ready.connect(self.render); self.thread.status.connect(self.status.setText); self.thread.start(); start.setEnabled(False); stop.setEnabled(True)
    def stop(self, start, stop):
        if self.thread: self.thread.stop(); self.thread = None
        start.setEnabled(True); stop.setEnabled(False)
    def process(self, packet):
        packet.hands, packet.poses = self.adapter.process(packet.frame, packet.timestamp_ns // 1_000_000); return packet
    def render(self, packet):
        import cv2
        frame = packet.frame.copy(); self.list.clear()
        for pose in packet.poses:
            points = [(int(x*frame.shape[1]), int(y*frame.shape[0])) for x,y,_ in pose]
            for a,b in [(11,13),(13,15),(12,14),(14,16),(11,12)]:
                if a < len(points) and b < len(points): cv2.line(frame, points[a], points[b], (217,74,88), 3)
        for hand in packet.hands:
            points = [(int(x*frame.shape[1]), int(y*frame.shape[0])) for x,y,_ in hand.landmarks]
            for x,y in points: cv2.circle(frame, (x,y), 3, (85,168,135), -1)
            for a,b in [(0,1),(1,2),(2,3),(3,4),(0,5),(5,6),(6,7),(7,8),(5,9),(9,10),(10,11),(11,12),(9,13),(13,14),(14,15),(15,16),(13,17),(17,18),(18,19),(19,20),(0,17)]:
                if a < len(points) and b < len(points): cv2.line(frame, points[a], points[b], (201,166,107), 2)
            self.list.addItem(f"{hand.gesture} · {hand.finger_count} · владелец: {hand.owner_person_id or 'не определён'}")
        self.canvas.setPixmap(frame_pixmap(frame, self.canvas.size())); self.status.setText(f"кадр {packet.frame_id} · FPS {packet.metrics['fps']:.1f} · median {packet.metrics.get('inference_median_ms',0):.1f} ms · p95 {packet.metrics.get('inference_p95_ms',0):.1f} ms")
    def closeEvent(self, event):
        if self.thread: self.thread.stop()
        if self.adapter: self.adapter.close()
        event.accept()

def main():
    p=argparse.ArgumentParser(); p.add_argument("--source",default="0"); args=p.parse_args(); app=QApplication(sys.argv); cfg=load_json(Path(__file__).with_name("config.json"),{}); w=Window(args.source,cfg); w.show(); sys.exit(app.exec())
if __name__ == "__main__": main()
