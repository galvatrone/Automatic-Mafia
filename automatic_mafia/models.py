from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np


BBox = Tuple[int, int, int, int]


@dataclass
class Observation:
    track_id: str
    source_id: str
    bbox: BBox
    face_id: Optional[str]
    distance: Optional[float]
    status: str
    label: str
    face_image: Optional[np.ndarray] = None
    encoding: Optional[np.ndarray] = None
    held: bool = False


@dataclass
class Track:
    track_id: str
    bbox: BBox
    first_seen: float
    last_seen: float
    stable_count: int = 1
    candidate_face_id: Optional[str] = None
    last_encoding: Optional[np.ndarray] = None
    face_image: Optional[np.ndarray] = None


@dataclass
class Player:
    participant_id: str
    face_id: str
    number: int
    name: str = ""
    photo_path: str = ""
    status: str = "Временно не виден"
    game_status: str = "В игре"
    hidden_role: str = "не определена"
    elimination_reason: str = ""
    eliminated_at: str = ""
    last_seen: float = 0.0
