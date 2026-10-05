import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QFormLayout, QHBoxLayout, QLabel, QListWidget, QPushButton, QSplitter, QVBoxLayout, QWidget
from shared.capture import CaptureThread
from shared.config import load_json
from shared.exchange import write_participants
from shared.observations import Box, FaceObservation, PersonObservation
from shared.ui import ExperimentWindow, frame_pixmap

class IoUTracks:
    def __init__(self):
        self.next_id = 1
        self.last = {}
    def assign(self, boxes):
        result = []
        for box in boxes:
            best, score = None, 0
            for tid, old in self.last.items():
                ox, oy = old.center; x, y = box.center
                d = ((ox - x) ** 2 + (oy - y) ** 2) ** .5
                limit = max(box.x2 - box.x1, box.y2 - box.y1) * 1.5
                if d < limit and (best is None or d < score): best, score = tid, d
            if best is None:
                best = self.next_id; self.next_id += 1
            self.last[best] = box
            result.append(best)
        return result

class FaceAdapter:
    name = "base"
    def __init__(self): self.error = ""
    def process(self, frame): return []

class HaarAdapter(FaceAdapter):
    name = "OpenCV Haar (smoke test)"
    def __init__(self):
        import cv2
        if not hasattr(cv2, "CascadeClassifier"):
            raise RuntimeError("текущий OpenCV 5.0.0 собран без legacy CascadeClassifier; используйте YuNet или отдельный OpenCV 4.x")
        self.detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    def process(self, frame):
        import cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.detector.detectMultiScale(gray, 1.1, 5, minSize=(45, 45))
        return [FaceObservation(Box(x, y, x+w, y+h), 1.0, source="opencv-haar") for x, y, w, h in faces]

class DlibAdapter(FaceAdapter):
    name = "face_recognition / dlib"
    def __init__(self):
        try: import face_recognition
        except ImportError as exc: raise RuntimeError("установите face-recognition и dlib") from exc
        self.fr = face_recognition
    def process(self, frame):
        import cv2
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        locations = self.fr.face_locations(rgb, model="hog")
        output = []
        for top, right, bottom, left in locations:
            emb = None
            try: emb = self.fr.face_encodings(rgb, [(top, right, bottom, left)], num_jitters=1)[0]
            except Exception: pass
            output.append(FaceObservation(Box(left, top, right, bottom), 1.0, embedding=emb, source="dlib"))
        return output

class YuNetAdapter(FaceAdapter):
    name = "OpenCV YuNet + SFace"
    def __init__(self, detector_path, recognizer_path):
        import cv2
        if not Path(detector_path).exists(): raise RuntimeError(f"нет веса YuNet: {detector_path}. Запустите ../setup_experiments.sh --models")
        if not Path(recognizer_path).exists(): raise RuntimeError(f"нет веса SFace: {recognizer_path}. Запустите ../setup_experiments.sh --models")
        self.detector = cv2.FaceDetectorYN.create(detector_path, "", (320, 320), 0.8, 0.3, 5000)
        self.recognizer = cv2.FaceRecognizerSF.create(recognizer_path, "")
    def process(self, frame):
        self.detector.setInputSize((frame.shape[1], frame.shape[0]))
        _, faces = self.detector.detect(frame)
        output = []
        for row in faces if faces is not None else []:
            x, y, w, h = row[:4]
            aligned = self.recognizer.alignCrop(frame, row)
            embedding = self.recognizer.feature(aligned).reshape(-1)
            output.append(FaceObservation(Box(x, y, x+w, y+h), float(row[14]), embedding=embedding, source="yunet+sface"))
        return output

class OptionalAdapter(FaceAdapter):
    name = "InsightFace SCRFD + ArcFace"
    def __init__(self, pack):
        try:
            import onnxruntime as ort
            from insightface.app import FaceAnalysis
        except ImportError as exc: raise RuntimeError("нужны insightface и onnxruntime") from exc
        providers = ort.get_available_providers()
        provider = "CPUExecutionProvider" if "CPUExecutionProvider" in providers else providers[0]
        self.app = FaceAnalysis(name=pack, providers=[provider])
        self.app.prepare(ctx_id=0, det_size=(640, 640))
        self.provider = provider
    def process(self, frame):
        faces = self.app.get(frame)
        return [FaceObservation(Box(*f.bbox), float(f.det_score), embedding=getattr(f, "embedding", None), source=f"insightface/{self.provider}") for f in faces]

def make_adapter(name, cfg):
    if name == HaarAdapter.name: return HaarAdapter()
    if name == DlibAdapter.name: return DlibAdapter()
    if name == YuNetAdapter.name:
        return YuNetAdapter(str(Path(__file__).parent / cfg["yunet_model"]), str(Path(__file__).parent / cfg["sface_model"]))
    return OptionalAdapter(cfg.get("insightface_pack", "buffalo_sc"))

class PersonAdapter:
    def __init__(self, name, tracker, cfg):
        try:
            from ultralytics import YOLO
        except ImportError as exc: raise RuntimeError("для YOLO/RT-DETR установите ultralytics отдельно") from exc
        model_path = cfg.get("rtdetr_model") if name.startswith("RT-DETR") else cfg.get("yolo_model")
        path = Path(__file__).parent / model_path
        if not path.exists(): raise RuntimeError(f"нет локального веса детектора людей: {path}. Запустите ../setup_experiments.sh --models")
        self.model = YOLO(str(path)); self.name = name; self.tracker = "botsort.yaml" if tracker == "BoT-SORT" else "bytetrack.yaml"
    def process(self, frame):
        observations=[]
        result=self.model.track(frame, persist=True, tracker=self.tracker, verbose=False, classes=[0], device="cpu")[0]
        ids = result.boxes.id.int().cpu().tolist() if result.boxes.id is not None else [None] * len(result.boxes)
        for box, conf, track_id in zip(result.boxes.xyxy.cpu().tolist(), result.boxes.conf.cpu().tolist(), ids):
            observations.append(PersonObservation(Box(*box), float(conf), track_id=track_id, source=f"{self.name}/{self.tracker}"))
        return observations

class IdentityGallery:
    def __init__(self, results_dir, threshold=0.363, ambiguity_margin=0.04):
        self.results_dir = Path(results_dir); self.results_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.results_dir / "identity_gallery.json"; self.exchange_path = self.results_dir / "participants.json"
        self.threshold = threshold; self.ambiguity_margin = ambiguity_margin; self.entries = {}; self.temporary = {}; self.track_map = {}
        if self.path.exists():
            try: self.entries = json.loads(self.path.read_text(encoding="utf-8")).get("identities", {})
            except (OSError, ValueError): self.entries = {}
    @staticmethod
    def normalize(value):
        import numpy as np
        vector = np.asarray(value, dtype="float32").reshape(-1); norm = float(np.linalg.norm(vector))
        return vector / norm if norm else vector
    def resolve(self, track_id, embedding):
        import numpy as np
        if embedding is None: return None, "embedding отсутствует"
        vector = self.normalize(embedding); ranked = []
        if track_id in self.track_map:
            cached_id = self.track_map[track_id]
            cached = self.entries.get(cached_id)
            cached_score = float(np.dot(vector, self.normalize(cached["embedding"]))) if cached else -1.0
            if cached_score >= self.threshold: return cached_id, f"track cache cos={cached_score:.3f}"
            self.track_map.pop(track_id, None)
        for person_id, data in self.entries.items(): ranked.append((float(np.dot(vector, self.normalize(data["embedding"]))), person_id))
        ranked.sort(reverse=True)
        if ranked and ranked[0][0] >= self.threshold:
            if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < self.ambiguity_margin:
                return None, f"неоднозначно: {ranked[0][0]:.3f}/{ranked[1][0]:.3f}"
            person_id = ranked[0][1]
            old = self.normalize(self.entries[person_id]["embedding"]); samples = int(self.entries[person_id].get("samples", 1))
            merged = self.normalize((old * samples + vector) / (samples + 1)); self.entries[person_id]["embedding"] = merged.tolist(); self.entries[person_id]["samples"] = min(samples + 1, 100)
            self.track_map[track_id] = person_id; return person_id, f"cos={ranked[0][0]:.3f}"
        person_id = f"P{len(self.entries)+1:03d}"
        self.entries[person_id] = {"embedding": vector.tolist(), "samples": 1, "label": person_id, "photo_path": "", "last_seen_ns": 0}
        self.track_map[track_id] = person_id; return person_id, "новая экспериментальная личность"
    def observe(self, person_id, frame, box, timestamp_ns):
        import cv2
        if not person_id: return
        data = self.entries[person_id]; data["last_seen_ns"] = timestamp_ns
        photo = self.results_dir / "participants" / f"{person_id}.jpg"
        if not photo.exists():
            photo.parent.mkdir(parents=True, exist_ok=True); x1,y1,x2,y2=box.as_int(); h,w=frame.shape[:2]; crop=frame[max(0,y1):min(h,y2),max(0,x1):min(w,x2)]
            if crop.size: cv2.imwrite(str(photo), crop); data["photo_path"] = str(photo.resolve())
    def observe_person(self, person, frame, timestamp_ns):
        import cv2
        if not person.person_id or person.person_id in self.entries: return
        data = self.temporary.setdefault(person.person_id, {"label":person.person_id,"photo_path":"","last_seen_ns":0})
        data["last_seen_ns"] = timestamp_ns; photo = self.results_dir / "participants" / f"{person.person_id}.jpg"
        if not photo.exists():
            photo.parent.mkdir(parents=True, exist_ok=True); x1,y1,x2,y2=person.box.as_int(); h,w=frame.shape[:2]; crop=frame[max(0,y1):min(h,y2),max(0,x1):min(w,x2)]
            if crop.size: cv2.imwrite(str(photo),crop); data["photo_path"] = str(photo.resolve())
    def save(self, source):
        self.path.write_text(json.dumps({"model":"OpenCV SFace 2021dec","threshold":self.threshold,"identities":self.entries}, ensure_ascii=False, indent=2), encoding="utf-8")
        combined = {**self.temporary, **self.entries}
        participants = [{"person_id":pid,"label":data.get("label",pid),"photo_path":data.get("photo_path", ""),"last_seen_ns":data.get("last_seen_ns",0)} for pid,data in combined.items()]
        write_participants(self.exchange_path, participants, source)

class Window(ExperimentWindow):
    def __init__(self, source, cfg):
        super().__init__("Automatic Mafia · эксперимент person_face")
        self.cfg = cfg; self.thread = None; self.face_tracks = IoUTracks(); self.source_value = source; self.gallery = IdentityGallery(Path(__file__).parent / "results")
        self.canvas = QLabel("Нет кадра"); self.canvas.setAlignment(Qt.AlignCenter); self.canvas.setMinimumSize(700, 450)
        self.people = QListWidget(); self.status = QLabel("Готово. Выберите адаптер и источник.")
        self.source = QLabel(source); self.source.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.face = QComboBox(); self.face.addItems([YuNetAdapter.name, DlibAdapter.name, OptionalAdapter.name, HaarAdapter.name]); self.face.setCurrentText(cfg.get("face_model", YuNetAdapter.name))
        self.person = QComboBox(); self.person.addItems(["YOLO + ByteTrack", "None", "RT-DETR (optional)"]); self.person.setCurrentText(cfg.get("person_detector", "YOLO + ByteTrack"))
        self.tracker = QComboBox(); self.tracker.addItems(["ByteTrack", "BoT-SORT"]); self.tracker.setCurrentText(cfg.get("tracker", "ByteTrack"))
        start = QPushButton("Запустить"); stop = QPushButton("Остановить"); stop.setEnabled(False)
        start.clicked.connect(lambda: self.start(source, start, stop)); stop.clicked.connect(lambda: self.stop(stop, start))
        form = QFormLayout(); form.addRow("Источник", self.source); form.addRow("Лица", self.face); form.addRow("Люди", self.person); form.addRow("Трекер", self.tracker); form.addRow(start, stop)
        side = QWidget(); side_l = QVBoxLayout(side); side_l.addLayout(form); side_l.addWidget(QLabel("Наблюдения")); side_l.addWidget(self.people); side_l.addWidget(self.status)
        split = QSplitter(); split.addWidget(self.canvas); split.addWidget(side); split.setSizes([850, 350]); self.setCentralWidget(split)
    def start(self, source, start, stop):
        try: adapter = make_adapter(self.face.currentText(), self.cfg)
        except Exception as exc: self.status.setText(str(exc)); return
        try: self.person_adapter = None if self.person.currentText() == "None" else PersonAdapter(self.person.currentText(), self.tracker.currentText(), self.cfg)
        except Exception as exc: self.status.setText(str(exc)); return
        self.adapter = adapter
        self.thread = CaptureThread(source, processor=self.process)
        self.thread.packet_ready.connect(self.render); self.thread.status.connect(self.status.setText); self.thread.start(); start.setEnabled(False); stop.setEnabled(True)
    def stop(self, stop, start):
        if self.thread: self.thread.stop(); self.thread = None
        start.setEnabled(True); stop.setEnabled(False)
    def process(self, packet):
        packet.faces = self.adapter.process(packet.frame)
        if self.person_adapter:
            packet.people = self.person_adapter.process(packet.frame)
            for p in packet.people: p.person_id = f"track-{p.track_id}" if p.track_id is not None else None
        ids = self.face_tracks.assign([f.box for f in packet.faces])
        for f, tid in zip(packet.faces, ids):
            f.track_id = tid; f.person_id, _ = self.gallery.resolve(tid, f.embedding); self.gallery.observe(f.person_id, packet.frame, f.box, packet.timestamp_ns)
            for person in packet.people:
                cx, cy = f.box.center
                if person.box.x1 <= cx <= person.box.x2 and person.box.y1 <= cy <= person.box.y2: person.person_id = f.person_id
        for person in packet.people: self.gallery.observe_person(person,packet.frame,packet.timestamp_ns)
        if packet.frame_id % 30 == 1: self.gallery.save(self.source_value)
        return packet
    def render(self, packet):
        import cv2
        frame = packet.frame.copy()
        for face in packet.faces:
            x1, y1, x2, y2 = face.box.as_int(); cv2.rectangle(frame, (x1, y1), (x2, y2), (201, 166, 107), 2); cv2.putText(frame, f"person_id={face.person_id} track_id={face.track_id}", (x1, max(20, y1-8)), cv2.FONT_HERSHEY_SIMPLEX, .5, (201,166,107), 1)
        for person in packet.people:
            x1, y1, x2, y2 = person.box.as_int(); cv2.rectangle(frame, (x1, y1), (x2, y2), (135, 95, 190), 2); cv2.putText(frame, f"{person.person_id} track_id={person.track_id}", (x1, min(frame.shape[0]-8, y2+18)), cv2.FONT_HERSHEY_SIMPLEX, .5, (135,95,190), 1)
        self.canvas.setPixmap(frame_pixmap(frame, self.canvas.size())); self.people.clear()
        for f in packet.faces: self.people.addItem(f"лицо {f.person_id} · track {f.track_id} · {f.source}")
        for p in packet.people: self.people.addItem(f"человек {p.person_id} · track {p.track_id} · {p.source}")
        m = packet.metrics; cpu = "n/a" if m.get("cpu_percent") is None else f"{m['cpu_percent']:.0f}%"
        self.status.setText(f"FPS {m['fps']:.1f} · inference median {m.get('inference_median_ms',0):.1f} ms / p95 {m.get('inference_p95_ms',0):.1f} ms · CPU {cpu} · память {m.get('memory_mb') or 0:.0f} MB")
    def closeEvent(self, event):
        if self.thread: self.thread.stop()
        self.gallery.save(self.source_value)
        event.accept()

def main():
    p = argparse.ArgumentParser(); p.add_argument("--source", default="0"); args = p.parse_args()
    app = QApplication(sys.argv); cfg = load_json(Path(__file__).with_name("config.json"), {}); w = Window(args.source, cfg); w.show(); sys.exit(app.exec())
if __name__ == "__main__": main()
