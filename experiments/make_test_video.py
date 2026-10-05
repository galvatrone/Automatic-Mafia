import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent; sys.path.insert(0,str(ROOT))
import cv2

def main():
    assets=ROOT/"shared/test_assets"; images=[]
    for name in ["lena.jpg","woman_hands.jpg","bus.jpg"]:
        image=cv2.imread(str(assets/name))
        if image is None: raise SystemExit(f"Не прочитан {name}")
        scale=min(960/image.shape[1],540/image.shape[0]); resized=cv2.resize(image,(int(image.shape[1]*scale),int(image.shape[0]*scale))); canvas=cv2.copyMakeBorder(resized,(540-resized.shape[0])//2,540-resized.shape[0]-(540-resized.shape[0])//2,(960-resized.shape[1])//2,960-resized.shape[1]-(960-resized.shape[1])//2,cv2.BORDER_CONSTANT,value=(21,21,21)); images.append(canvas)
    target=assets/"common_test.mp4"; writer=cv2.VideoWriter(str(target),cv2.VideoWriter_fourcc(*"mp4v"),15,(960,540))
    for image in images:
        for _ in range(30): writer.write(image)
    writer.release(); print(target)
if __name__=="__main__": main()
