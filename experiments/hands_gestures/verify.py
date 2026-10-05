import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
import cv2
from app import GestureAdapter
from shared.config import load_json

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--input",default=str(ROOT/"shared/test_assets/woman_hands.jpg")); parser.add_argument("--fist",default=str(ROOT/"shared/test_assets/closed_fist.jpg")); parser.add_argument("--pointing",default=str(ROOT/"shared/test_assets/pointing_person.jpg")); parser.add_argument("--video"); parser.add_argument("--max-frames",type=int,default=180); args=parser.parse_args()
    cfg=load_json(Path(__file__).with_name("config.json"),{}); adapter=GestureAdapter("MediaPipe Hand + Pose Landmarker",cfg); timings=[]; cases={}; timestamp=0
    for label,path in [("open_palm",args.input),("fist",args.fist),("pointing",args.pointing)]:
        image=cv2.imread(path)
        if image is None: raise SystemExit(f"Тестовое изображение не прочитано: {path}. Запустите ../setup_experiments.sh --models")
        hands=[]; poses=[]
        for _ in range(6):
            started=time.perf_counter(); hands,poses=adapter.process(image,timestamp); timings.append((time.perf_counter()-started)*1000); timestamp+=100
        cases[label]={"hands":len(hands),"landmarks":[len(h.landmarks) for h in hands],"gestures":[h.gesture for h in hands],"finger_counts":[h.finger_count for h in hands],"owners":[h.owner_person_id for h in hands],"poses":len(poses)}
    if not cases["open_palm"]["hands"] or any(count!=21 for count in cases["open_palm"]["landmarks"]): raise SystemExit("Hand Landmarker не вернул 21 landmark для ладони")
    video_frames=0
    if args.video:
        cap=cv2.VideoCapture(args.video)
        while video_frames<args.max_frames:
            ok,frame=cap.read()
            if not ok: break
            started=time.perf_counter(); adapter.process(frame,timestamp+video_frames*34); timings.append((time.perf_counter()-started)*1000); video_frames+=1
        cap.release()
    adapter.close(); ordered=sorted(timings); report={"adapter":"MediaPipe Hand Landmarker + Pose Landmarker Lite","weights_available":True,"models_loaded":True,"inference_completed":True,"live_camera_tested":False,"cases":cases,"ambiguous_owner_policy":"owner remains null unless wrist distance and margin pass","video_frames":video_frames,"timing":{"median_ms":statistics.median(ordered),"p95_ms":ordered[min(len(ordered)-1,int(len(ordered)*.95))]}}
    target=Path(__file__).parent/"results/verification.json"; target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
