from automatic_mafia.models import BBox
import numpy as np


def bbox_iou(box_a: BBox, box_b: BBox) -> float:
    at, ar, ab, al = box_a
    bt, br, bb, bl = box_b
    inter_left, inter_top = max(al, bl), max(at, bt)
    inter_right, inter_bottom = min(ar, br), min(ab, bb)
    inter_area = max(0, inter_right - inter_left) * max(0, inter_bottom - inter_top)
    area_a = max(0, ar - al) * max(0, ab - at)
    area_b = max(0, br - bl) * max(0, bb - bt)
    union = area_a + area_b - inter_area
    return inter_area / union if union > 0 else 0.0


def center_distance_ratio(box_a: BBox, box_b: BBox) -> float:
    a_top, a_right, a_bottom, a_left = box_a
    b_top, b_right, b_bottom, b_left = box_b
    ax = (a_left + a_right) / 2.0
    ay = (a_top + a_bottom) / 2.0
    bx = (b_left + b_right) / 2.0
    by = (b_top + b_bottom) / 2.0
    distance = np.sqrt((ax - bx) ** 2 + (ay - by) ** 2)
    norm = max(
        1.0,
        max(a_right - a_left, a_bottom - a_top, b_right - b_left, b_bottom - b_top),
    )
    return distance / norm
