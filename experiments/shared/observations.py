from dataclasses import dataclass, field
from typing import Any, Optional

@dataclass
class Box:
    x1: float
    y1: float
    x2: float
    y2: float
    def as_int(self):
        return tuple(int(v) for v in (self.x1, self.y1, self.x2, self.y2))
    @property
    def center(self):
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

@dataclass
class FaceObservation:
    box: Box
    score: float = 0.0
    track_id: Optional[int] = None
    person_id: Optional[str] = None
    embedding: Any = None
    source: str = "unknown"

@dataclass
class PersonObservation:
    box: Box
    score: float = 0.0
    track_id: Optional[int] = None
    person_id: Optional[str] = None
    source: str = "unknown"

@dataclass
class HandObservation:
    landmarks: list[tuple[float, float, float]] = field(default_factory=list)
    handedness: str = "unknown"
    owner_person_id: Optional[str] = None
    gesture: str = "unknown"
    finger_count: int = 0
    pointing_vector: Optional[tuple[float, float]] = None

@dataclass
class FramePacket:
    camera_id: str
    frame_id: int
    timestamp_ns: int
    frame: Any
    faces: list[FaceObservation] = field(default_factory=list)
    people: list[PersonObservation] = field(default_factory=list)
    hands: list[HandObservation] = field(default_factory=list)
    poses: list[list[tuple[float, float, float]]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
