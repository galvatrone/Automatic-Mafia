import json
import time
import uuid
from datetime import datetime, timezone
from typing import Dict

import cv2
import numpy as np

from automatic_mafia.config import DATA_DIR, PLAYERS_DIR, SESSION_FILE
from automatic_mafia.models import Player


class SessionStore:
    def __init__(self):
        self.players: Dict[str, Player] = {}
        self.next_number = 1
        self.load()

    def load(self):
        if not SESSION_FILE.exists():
            return
        with SESSION_FILE.open("r", encoding="utf-8") as session_file:
            data = json.load(session_file)
        self.next_number = int(data.get("next_number", 1))
        self.players = {}
        for item in data.get("players", []):
            item.setdefault("game_status", "В игре")
            item.setdefault("hidden_role", "не определена")
            item.setdefault("elimination_reason", "")
            item.setdefault("eliminated_at", "")
            player = Player(**item)
            player.status = "Временно не виден"
            player.last_seen = 0.0
            self.players[player.face_id] = player

    def save(self):
        DATA_DIR.mkdir(exist_ok=True)
        payload = {
            "next_number": self.next_number,
            "players": [player.__dict__ for player in sorted(self.players.values(), key=lambda p: p.number)],
        }
        with SESSION_FILE.open("w", encoding="utf-8") as session_file:
            json.dump(payload, session_file, ensure_ascii=False, indent=2)

    def new_session(self):
        self.players = {}
        self.next_number = 1
        self.save()

    def reset_game_statuses(self):
        for player in self.players.values():
            player.game_status = "В игре"
            player.elimination_reason = ""
            player.eliminated_at = ""
        self.save()

    def add_player(self, face_id: str, face_image: np.ndarray) -> Player:
        if face_id in self.players:
            return self.players[face_id]
        PLAYERS_DIR.mkdir(exist_ok=True)
        photo_path = PLAYERS_DIR / f"player_{self.next_number}.jpg"
        cv2.imwrite(str(photo_path), face_image)
        player = Player(
            participant_id=str(uuid.uuid4()),
            face_id=face_id,
            number=self.next_number,
            photo_path=str(photo_path),
            status="В кадре",
            last_seen=time.time(),
        )
        self.players[face_id] = player
        self.next_number += 1
        self.save()
        return player

    def remove_player(self, face_id: str):
        if face_id in self.players:
            del self.players[face_id]
            self.save()

    def rename_player(self, face_id: str, name: str):
        if face_id in self.players:
            self.players[face_id].name = name.strip()
            self.save()

    def eliminate_player(self, face_id: str, reason: str):
        if face_id in self.players:
            self.players[face_id].game_status = "Выбыл"
            self.players[face_id].elimination_reason = reason
            self.players[face_id].eliminated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self.save()

    def restore_player(self, face_id: str):
        if face_id in self.players:
            self.players[face_id].game_status = "В игре"
            self.players[face_id].elimination_reason = ""
            self.players[face_id].eliminated_at = ""
            self.save()
