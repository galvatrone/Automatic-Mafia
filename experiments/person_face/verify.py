import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import cv2
from app import IdentityGallery, PersonAdapter, YuNetAdapter
from shared.config import load_json

def timed(values, callback):
    started = time.perf_counter(); result = callback(); values.append((time.perf_counter()-started)*1000); return result

def summary(values):
    ordered=sorted(values); return {"median_ms":statistics.median(ordered),"p95_ms":ordered[min(len(ordered)-1,int(len(ordered)*.95))]}

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--face-image",default=str(ROOT/"shared/test_assets/lena.jpg")); parser.add_argument("--person-image",default=str(ROOT/"shared/test_assets/bus.jpg")); parser.add_argument("--video"); parser.add_argument("--max-frames",type=int,default=180); args=parser.parse_args()
    cfg=load_json(Path(__file__).with_name("config.json"),{}); base=Path(__file__).parent
    face_adapter=YuNetAdapter(str(base/cfg["yunet_model"]),str(base/cfg["sface_model"])); person_adapter=PersonAdapter("YOLO + ByteTrack","ByteTrack",cfg)
    gallery=IdentityGallery(base/"results/verification"); face_image=cv2.imread(args.face_image); person_image=cv2.imread(args.person_image)
    if face_image is None or person_image is None: raise SystemExit("Тестовые изображения не прочитаны. Запустите ../setup_experiments.sh --models")
    face_times=[]; person_times=[]; faces=timed(face_times,lambda:face_adapter.process(face_image)); people=timed(person_times,lambda:person_adapter.process(person_image))
    if not faces or faces[0].embedding is None: raise SystemExit("YuNet обнаружил 0 лиц или SFace не создал embedding")
    first,_=gallery.resolve(1,faces[0].embedding); gallery.track_map.clear(); second,_=gallery.resolve(2,faces[0].embedding)
    if first!=second: raise SystemExit("SFace не восстановил устойчивый person_id на повторном embedding")
    gallery.observe(first,face_image,faces[0].box,time.time_ns()); gallery.save("official-test-assets")
    for person in people:
        person.person_id=f"track-{person.track_id}"; gallery.observe_person(person,person_image,time.time_ns())
    gallery.save("official-test-assets")
    video_frames=0
    if args.video:
        cap=cv2.VideoCapture(args.video)
        while video_frames<args.max_frames:
            ok,frame=cap.read()
            if not ok: break
            timed(face_times,lambda f=frame:face_adapter.process(f)); timed(person_times,lambda f=frame:person_adapter.process(f)); video_frames+=1
        cap.release()
    report={"adapter":"YuNet + SFace + YOLO11n + ByteTrack","weights_available":True,"models_loaded":True,"inference_completed":True,"live_camera_tested":False,"face_count":len(faces),"embedding_size":int(faces[0].embedding.size),"stable_tag":first,"person_count":len(people),"video_frames":video_frames,"face_timing":summary(face_times),"person_timing":summary(person_times)}
    target=base/"results/verification.json"; target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
