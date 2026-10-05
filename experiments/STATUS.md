# Experimental stands status

## Verified on 2026-10-05

| Path | Adapter | Weights | Loaded | Inference | Live camera |
|---|---:|---:|---:|---:|---:|
| YuNet + SFace | yes | yes | yes | yes, 128D embedding and stable `P001` | no `/dev/video*` |
| YOLO11n + ByteTrack | yes | yes | yes | yes, 4 people on official sample | no `/dev/video*` |
| MediaPipe Hand + Pose | yes | yes | yes | yes, palm/fist/pointing | no `/dev/video*` |
| person_face exchange -> table | yes | n/a | yes | yes, 5 tags -> one cycle -> numbers | n/a |

All three Qt windows were opened together by `launcher.py` in the real Wayland/X11 session for 15 seconds while both vision stands read the same test video. No live camera device was available.

## Measurements

The common 90-frame video is a smoke/load sequence made from official static images, not an accuracy dataset.

- YuNet + SFace: median 105.18 ms, p95 126.75 ms.
- YOLO11n + ByteTrack: median 34.93 ms, p95 55.23 ms.
- Hand + Pose Landmarker: median 55.61 ms, p95 94.58 ms.

## Compatibility decisions

- Python 3.11.14 for all stands; host Python 3.14 is not used.
- PySide6 Essentials 6.11.2; unused Addons removed to save about 1.2 GB.
- OpenCV 4.14 headless for person/face and 4.11 for MediaPipe.
- PyTorch 2.14.1+cpu; no CUDA provider.
- MediaPipe 0.10.35. Version 0.10.21 was rejected because import hung on this system.
- `sounddevice` removed from the gesture venv because PortAudio import hangs; no experiment uses audio.

## Adversarial review

- Exchange parsing rejects unknown schemas, duplicate/empty IDs and an empty participant list.
- No experiment imports `automatic_mafia` or writes under the main `data/` directory.
- Model downloads use fixed HTTPS URLs and a SHA-256 manifest. Existing files are hashed instead of silently replaced.
- `track-N` is explicitly temporary and cannot silently become a final player number until the table cycle is confirmed.
- Identity matching rejects close competing SFace candidates; hand ownership rejects cross-body ambiguity.
- Remaining risk: local ONNX/PT/task files are executable model inputs. Reproduce the integrity check with `sha256sum` and compare it with `MODEL_MANIFEST.json` before replacing weights.

## Repair prompt

On the laptop, run both vision stands against camera `0`, record a multi-person session with turns, occlusions and returns, then compare ID switches and tune SFace/owner thresholds from labelled observations. Do not integrate into the main game until that test is recorded.
