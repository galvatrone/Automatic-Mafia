import json
from datetime import datetime, timezone
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Set

from automatic_mafia.config import DATA_DIR, GAME_FILE
from automatic_mafia.storage.session_store import SessionStore


ROLE_CIVILIAN = "мирный"
ROLE_MAFIA = "мафия"
ROLE_DON = "дон"
ROLE_COMMISSAR = "комиссар"
ROLE_DOCTOR = "доктор"
ROLES = [ROLE_CIVILIAN, ROLE_MAFIA, ROLE_DON, ROLE_COMMISSAR, ROLE_DOCTOR]
ROLE_ASSIGNMENT_STAGES = [ROLE_MAFIA, ROLE_DON, ROLE_COMMISSAR, ROLE_DOCTOR, ROLE_CIVILIAN]

PHASE_SETUP = "setup"
PHASE_HIDDEN = "hidden"
PHASE_MAFIA = "mafia"
PHASE_DON = "don"
PHASE_DON_RESULT = "don_result"
PHASE_COMMISSAR = "commissar"
PHASE_COMMISSAR_RESULT = "commissar_result"
PHASE_DOCTOR = "doctor"
PHASE_DAY = "day"
PHASES = [PHASE_SETUP, PHASE_HIDDEN, PHASE_DON, PHASE_DON_RESULT, PHASE_MAFIA, PHASE_COMMISSAR, PHASE_COMMISSAR_RESULT, PHASE_DOCTOR, PHASE_DAY]

ELIMINATED_NIGHT = "Убит ночью"
ELIMINATED_VOTE = "Выгнан голосованием"


@dataclass
class GameState:
    phase: str = PHASE_SETUP
    night_number: int = 1
    day_number: int = 1
    roles: Dict[str, str] = field(default_factory=dict)
    current_selection: Optional[str] = None
    mafia_target: Optional[str] = None
    mafia_no_action: bool = False
    mafia_done: bool = False
    don_target: Optional[str] = None
    don_no_action: bool = False
    don_done: bool = False
    don_checks: List[dict] = field(default_factory=list)
    commissar_target: Optional[str] = None
    commissar_no_action: bool = False
    commissar_done: bool = False
    doctor_target: Optional[str] = None
    doctor_no_action: bool = False
    doctor_done: bool = False
    commissar_checks: List[dict] = field(default_factory=list)
    previous_doctor_target: Optional[str] = None
    last_night_doctor_target: Optional[str] = None
    night_resolved: bool = False
    day_message: str = ""
    allow_self_heal: bool = True
    role_assignment_index: int = 0
    night_role_index: int = -1
    role_deck: Dict[str, int] = field(default_factory=dict)
    role_assignment_pending: List[str] = field(default_factory=list)
    role_assignment_history: List[dict] = field(default_factory=list)
    night_history: List[dict] = field(default_factory=list)
    party_history: List[dict] = field(default_factory=list)
    winner: Optional[str] = None
    winner_at: Optional[str] = None
    roles_revealed: bool = False


class GameStore:
    def __init__(self, session: SessionStore):
        self.session = session
        self.state = GameState()
        self.load()
        if not self.state.role_deck:
            self.state.role_deck = self.default_role_deck(len(self.session.players))
            self.save()
        if self.state.phase != PHASE_DAY:
            self.state.phase = PHASE_HIDDEN
            self.state.current_selection = None
            self.save()

    def load(self):
        if not GAME_FILE.exists():
            return
        with GAME_FILE.open("r", encoding="utf-8") as game_file:
            data = json.load(game_file)
        for field_name in GameState.__dataclass_fields__:
            data.setdefault(field_name, getattr(GameState(), field_name))
        self.state = GameState(**data)

    def save(self):
        DATA_DIR.mkdir(exist_ok=True)
        with GAME_FILE.open("w", encoding="utf-8") as game_file:
            json.dump(asdict(self.state), game_file, ensure_ascii=False, indent=2)

    def new_game(self):
        allow_self_heal = self.state.allow_self_heal
        self.state = GameState(
            allow_self_heal=allow_self_heal,
            role_deck=self.default_role_deck(len(self.session.players)),
        )
        self.session.reset_game_statuses()
        self.save()

    @staticmethod
    def _moment() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def set_phase(self, phase: str):
        if phase not in PHASES:
            raise ValueError(f"Unknown phase: {phase}")
        self.state.phase = phase
        self.state.current_selection = None
        if phase in {PHASE_DON, PHASE_MAFIA, PHASE_COMMISSAR, PHASE_DOCTOR}:
            role_order = []
            if self._living_roles({ROLE_DON}):
                role_order.append(PHASE_DON)
            if self._living_roles({ROLE_MAFIA, ROLE_DON}):
                role_order.append(PHASE_MAFIA)
            if self._living_roles({ROLE_COMMISSAR}):
                role_order.append(PHASE_COMMISSAR)
            if self._living_roles({ROLE_DOCTOR}):
                role_order.append(PHASE_DOCTOR)
            if phase in role_order:
                self.state.night_role_index = role_order.index(phase)
        if phase != PHASE_DAY:
            self.state.day_message = ""
        self.save()

    def check_winner(self) -> Optional[str]:
        if self.state.winner:
            return self.state.winner
        mafia_alive = sum(
            1 for face_id, player in self.session.players.items()
            if player.game_status == "В игре" and self.state.roles.get(face_id) in {ROLE_MAFIA, ROLE_DON}
        )
        civilian_alive = sum(
            1 for face_id, player in self.session.players.items()
            if player.game_status == "В игре" and self.state.roles.get(face_id, ROLE_CIVILIAN) not in {ROLE_MAFIA, ROLE_DON}
        )
        if mafia_alive == 0 and self.session.players:
            self.state.winner = "мирные"
        elif mafia_alive >= civilian_alive and mafia_alive > 0:
            self.state.winner = "мафия"
        if self.state.winner:
            self.state.phase = PHASE_DAY
            self.state.current_selection = None
            self.state.day_message = "Победа мирных" if self.state.winner == "мирные" else "Победа мафии"
            if not self.state.winner_at:
                self.state.winner_at = self._moment()
                self.state.party_history.append({
                    "type": "game_finished",
                    "night": self.state.night_number,
                    "day": self.state.day_number,
                    "winner": self.state.winner,
                    "at": self.state.winner_at,
                })
            self.save()
        return self.state.winner

    def reveal_roles(self):
        if not self.state.winner:
            raise ValueError("Роли можно раскрыть только после завершения партии")
        if self.state.roles_revealed:
            return
        self.state.roles_revealed = True
        self.state.party_history.append({
            "type": "roles_revealed",
            "night": self.state.night_number,
            "day": self.state.day_number,
            "at": self._moment(),
        })
        self.save()

    def start_night_sequence(self):
        self._require_game_active()
        if self.state.phase == PHASE_DAY:
            if not self.state.night_resolved:
                raise ValueError("Сначала завершите текущую ночь")
            self.start_next_night()
        self.state.night_role_index = -1
        self.state.current_selection = None
        self._advance_to_next_role()

    def advance_night_step(self):
        if self.state.phase not in {PHASE_HIDDEN, PHASE_DON_RESULT, PHASE_COMMISSAR_RESULT}:
            raise ValueError("Сначала завершите текущий ход роли")
        if self.state.phase in {PHASE_DON_RESULT, PHASE_COMMISSAR_RESULT}:
            self.state.phase = PHASE_HIDDEN
            self.state.current_selection = None
            self.save()
            return
        self._advance_to_next_role()

    def _advance_to_next_role(self):
        role_order = []
        if self._living_roles({ROLE_DON}):
            role_order.append(PHASE_DON)
        if self._living_roles({ROLE_MAFIA, ROLE_DON}):
            role_order.append(PHASE_MAFIA)
        if self._living_roles({ROLE_COMMISSAR}):
            role_order.append(PHASE_COMMISSAR)
        if self._living_roles({ROLE_DOCTOR}):
            role_order.append(PHASE_DOCTOR)
        next_index = self.state.night_role_index + 1
        if next_index >= len(role_order):
            self.resolve_night()
            return
        self.state.night_role_index = next_index
        self.state.phase = role_order[next_index]
        self.state.current_selection = None
        self.save()

    def assign_role(self, face_id: str, role: str):
        self._require_player(face_id)
        if role not in ROLES:
            raise ValueError(f"Unknown role: {role}")
        self.state.roles[face_id] = role
        self.save()

    @staticmethod
    def default_role_deck(player_count: int) -> Dict[str, int]:
        mafia_count = max(1, player_count // 4) if player_count else 0
        return {
            ROLE_MAFIA: mafia_count,
            ROLE_DON: 1 if player_count >= 5 else 0,
            ROLE_COMMISSAR: 1 if player_count >= 4 else 0,
            ROLE_DOCTOR: 1 if player_count >= 5 else 0,
            ROLE_CIVILIAN: max(0, player_count - mafia_count - (1 if player_count >= 5 else 0) - (1 if player_count >= 4 else 0) - (1 if player_count >= 5 else 0)),
        }

    def current_role_assignment(self) -> Optional[str]:
        if self.state.role_assignment_index >= len(ROLE_ASSIGNMENT_STAGES):
            return None
        return ROLE_ASSIGNMENT_STAGES[self.state.role_assignment_index]

    def role_assignment_expected(self) -> int:
        role = self.current_role_assignment()
        if role is None:
            return 0
        if role == ROLE_CIVILIAN:
            return sum(1 for face_id in self.session.players if face_id not in self.state.roles)
        return self.state.role_deck.get(role, 0)

    def role_assignment_selected(self) -> int:
        return len(self.state.role_assignment_pending)

    def select_role_candidate(self, face_id: str):
        role = self.current_role_assignment()
        if role is None:
            raise ValueError("Знакомство уже завершено")
        self._require_player(face_id)
        if face_id in self.state.roles:
            if role == ROLE_DON and self.state.roles.get(face_id) == ROLE_MAFIA:
                pass
            else:
                raise ValueError("Игрок уже получил роль")
        if role == ROLE_DON and self.state.roles.get(face_id) != ROLE_MAFIA:
            raise ValueError("Дона можно выбрать только среди мафии")
        if role != ROLE_MAFIA and role != ROLE_CIVILIAN and len(self.state.role_assignment_pending) >= 1 and face_id not in self.state.role_assignment_pending:
            raise ValueError("Для этой роли выбирается один игрок")
        if face_id in self.state.role_assignment_pending:
            self.state.role_assignment_pending.remove(face_id)
        else:
            if len(self.state.role_assignment_pending) >= self.role_assignment_expected():
                raise ValueError("Выбрано максимальное количество игроков")
            self.state.role_assignment_pending.append(face_id)
        self.state.current_selection = face_id
        self.save()

    def confirm_role_assignment(self):
        role = self.current_role_assignment()
        if role is None:
            raise ValueError("Знакомство уже завершено")
        expected = self.role_assignment_expected()
        if role == ROLE_CIVILIAN:
            assigned = [face_id for face_id in self.session.players if face_id not in self.state.roles]
        else:
            if len(self.state.role_assignment_pending) != expected:
                raise ValueError(f"Нужно выбрать: {expected}, сейчас выбрано: {len(self.state.role_assignment_pending)}")
            assigned = list(self.state.role_assignment_pending)
        for face_id in assigned:
            self.state.roles[face_id] = role
        self.state.role_assignment_history.append({"role": role, "face_ids": assigned})
        self.state.role_assignment_pending = []
        self.state.current_selection = None
        self.state.role_assignment_index += 1
        self.save()

    def back_role_assignment(self):
        if not self.state.role_assignment_history:
            raise ValueError("Это первый этап знакомства")
        previous = self.state.role_assignment_history.pop()
        for face_id in previous.get("face_ids", []):
            self.state.roles.pop(face_id, None)
        self.state.role_assignment_index = max(0, self.state.role_assignment_index - 1)
        self.state.role_assignment_pending = []
        self.state.current_selection = None
        self.save()

    def assign_current_role(self, face_id: str):
        role = self.current_role_assignment()
        if role is None:
            raise ValueError("Назначение ролей уже завершено")
        self._require_player(face_id)
        previous_role = self.state.roles.get(face_id)
        if previous_role in {ROLE_DON, ROLE_MAFIA, ROLE_COMMISSAR, ROLE_DOCTOR} and previous_role != role:
            raise ValueError("Этому игроку уже назначена роль")
        self.state.roles[face_id] = role
        self.state.current_selection = face_id
        self.save()

    def advance_role_assignment(self):
        if self.current_role_assignment() is None:
            raise ValueError("Назначение ролей уже завершено")
        self.state.role_assignment_index += 1
        self.state.current_selection = None
        self.save()

    def set_allow_self_heal(self, value: bool):
        self.state.allow_self_heal = bool(value)
        self.save()

    def select_player(self, face_id: str):
        self._require_game_active()
        self._require_live_player(face_id)
        self.state.current_selection = face_id
        self.save()

    def select_any_player(self, face_id: str):
        self._require_player(face_id)
        self.state.current_selection = face_id
        self.save()

    def clear_selection(self):
        self.state.current_selection = None
        self.save()

    def choose_mafia_target(self, face_id: str):
        self._require_game_active()
        self._require_phase(PHASE_MAFIA)
        self._require_live_player(face_id)
        self.state.mafia_target = face_id
        self.state.mafia_no_action = False
        self.state.mafia_done = False
        self.state.current_selection = face_id
        self.save()

    def choose_don_check(self, face_id: str):
        self._require_game_active()
        self._require_phase(PHASE_DON)
        self._require_live_player(face_id)
        self.state.don_target = face_id
        self.state.don_no_action = False
        self.state.don_done = False
        self.state.current_selection = face_id
        self.save()

    def cancel_don_check(self):
        self.state.don_target = None
        self.state.don_no_action = False
        self.state.don_done = False
        self.state.current_selection = None
        self.save()

    def finish_don_turn(self, no_action: bool = False):
        self._require_phase(PHASE_DON)
        if no_action:
            self.state.don_target = None
            self.state.don_no_action = True
        elif not self.state.don_target:
            raise ValueError("Не выбрана цель проверки дона")
        else:
            result = self.state.roles.get(self.state.don_target, ROLE_CIVILIAN) == ROLE_COMMISSAR
            event = {
                "type": "don_check",
                "night": self.state.night_number,
                "day": self.state.day_number,
                "face_id": self.state.don_target,
                "is_commissar": result,
                "result": "комиссар" if result else "не комиссар",
                "at": self._moment(),
            }
            self.state.don_checks.append(event)
            self.state.party_history.append(event)
        self.state.don_done = True
        self.state.phase = PHASE_DON_RESULT
        self.state.current_selection = None
        self.save()

    def cancel_mafia_target(self):
        self.state.mafia_target = None
        self.state.mafia_no_action = False
        self.state.mafia_done = False
        self.state.don_target = None
        self.state.don_no_action = False
        self.state.don_done = False
        self.state.current_selection = None
        self.save()

    def finish_mafia_turn(self, no_action: bool = False):
        self._require_phase(PHASE_MAFIA)
        if no_action:
            self.state.mafia_target = None
            self.state.mafia_no_action = True
        elif not self.state.mafia_target:
            raise ValueError("Не выбрана цель мафии")
        self.state.mafia_done = True
        self.set_phase(PHASE_HIDDEN)

    def choose_commissar_check(self, face_id: str):
        self._require_game_active()
        self._require_phase(PHASE_COMMISSAR)
        self._require_live_player(face_id)
        self.state.commissar_target = face_id
        self.state.commissar_no_action = False
        self.state.commissar_done = False
        self.state.current_selection = face_id
        self.save()

    def cancel_commissar_check(self):
        self.state.commissar_target = None
        self.state.commissar_no_action = False
        self.state.commissar_done = False
        self.state.current_selection = None
        self.save()

    def finish_commissar_turn(self, no_action: bool = False):
        self._require_phase(PHASE_COMMISSAR)
        if no_action:
            self.state.commissar_target = None
            self.state.commissar_no_action = True
        elif not self.state.commissar_target:
            raise ValueError("Не выбрана цель проверки")
        else:
            existing = [
                item
                for item in self.state.commissar_checks
                if item.get("night") == self.state.night_number
            ]
            result = self.is_mafia(self.state.commissar_target)
            entry = {
                "night": self.state.night_number,
                "day": self.state.day_number,
                "face_id": self.state.commissar_target,
                "is_mafia": result,
                "result": "мафия" if result else "не мафия",
                "at": self._moment(),
            }
            if existing:
                for item in self.state.commissar_checks:
                    if item.get("night") == self.state.night_number:
                        item.update(entry)
                        break
            else:
                self.state.commissar_checks.append(entry)
        self.state.commissar_done = True
        self.state.phase = PHASE_COMMISSAR_RESULT
        self.state.current_selection = None
        self.save()

    def choose_doctor_target(self, face_id: str):
        self._require_game_active()
        self._require_phase(PHASE_DOCTOR)
        self._require_live_player(face_id)
        if face_id == self.state.previous_doctor_target:
            raise ValueError("Этого игрока лечили прошлой ночью")
        if not self.state.allow_self_heal and self.state.roles.get(face_id, ROLE_CIVILIAN) == ROLE_DOCTOR:
            raise ValueError("Самолечение запрещено правилами")
        self.state.doctor_target = face_id
        self.state.doctor_no_action = False
        self.state.doctor_done = False
        self.state.current_selection = face_id
        self.save()

    def cancel_doctor_target(self):
        self.state.doctor_target = None
        self.state.doctor_no_action = False
        self.state.doctor_done = False
        self.state.current_selection = None
        self.save()

    def finish_doctor_turn(self, no_action: bool = False):
        self._require_phase(PHASE_DOCTOR)
        if no_action:
            self.state.doctor_target = None
            self.state.doctor_no_action = True
        elif not self.state.doctor_target:
            raise ValueError("Не выбрана цель лечения")
        elif self.state.doctor_target == self.state.previous_doctor_target:
            raise ValueError("Этого игрока лечили прошлой ночью")
        self.state.doctor_done = True
        self.set_phase(PHASE_HIDDEN)

    def resolve_night(self):
        if self.state.night_resolved:
            self.state.phase = PHASE_DAY
            self.save()
            return self.state.day_message or "Результат этой ночи уже применён"
        missing = self.missing_required_actions()
        if missing:
            raise ValueError("Не завершены ходы: " + ", ".join(missing))
        message = "Этой ночью никто не погиб"
        killed_face_id = None
        if self.state.mafia_target and self.state.mafia_target != self.state.doctor_target:
            self.session.eliminate_player(self.state.mafia_target, ELIMINATED_NIGHT)
            killed_face_id = self.state.mafia_target
            message = "Этой ночью погиб игрок"
        event = {
            "type": "night_resolved",
            "night": self.state.night_number,
            "day": self.state.day_number,
            "mafia_target": self.state.mafia_target,
            "doctor_target": self.state.doctor_target,
            "killed_face_id": killed_face_id,
            "saved": bool(self.state.mafia_target and self.state.mafia_target == self.state.doctor_target),
            "outcome": "killed" if killed_face_id else ("saved" if self.state.mafia_target else "no_kill"),
            "at": self._moment(),
        }
        self.state.night_history.append(event)
        self.state.party_history.append(event)
        self.state.previous_doctor_target = self.state.doctor_target
        self.state.last_night_doctor_target = self.state.doctor_target
        self.state.night_resolved = True
        self.state.day_message = message
        self.state.phase = PHASE_DAY
        self.state.current_selection = None
        winner = self.check_winner()
        if winner is None:
            self.save()
        else:
            return self.state.day_message
        return message

    def start_next_night(self):
        self._require_game_active()
        if not self.state.night_resolved:
            raise ValueError("Сначала завершите текущую ночь")
        self.state.night_number += 1
        self.state.day_number += 1
        self.state.phase = PHASE_HIDDEN
        self.state.current_selection = None
        self.state.mafia_target = None
        self.state.mafia_no_action = False
        self.state.mafia_done = False
        self.state.commissar_target = None
        self.state.commissar_no_action = False
        self.state.commissar_done = False
        self.state.doctor_target = None
        self.state.doctor_no_action = False
        self.state.doctor_done = False
        self.state.night_resolved = False
        self.state.day_message = ""
        self.save()

    def eliminate_by_vote(self, face_id: str):
        self._require_phase(PHASE_DAY)
        self._require_game_active()
        self._require_live_player(face_id)
        self.session.eliminate_player(face_id, ELIMINATED_VOTE)
        self.state.current_selection = None
        self.state.party_history.append({
            "type": "vote_elimination",
            "night": self.state.night_number,
            "day": self.state.day_number,
            "face_id": face_id,
            "reason": ELIMINATED_VOTE,
            "at": self._moment(),
        })
        if self.check_winner() is None:
            self.save()

    def restore_eliminated_player(self, face_id: str):
        self._require_player(face_id)
        self.session.restore_player(face_id)
        self.state.party_history.append({
            "type": "elimination_corrected",
            "night": self.state.night_number,
            "day": self.state.day_number,
            "face_id": face_id,
            "at": self._moment(),
        })
        if self.state.winner:
            self.state.winner = None
            self.state.winner_at = None
            self.state.roles_revealed = False
            self.state.phase = PHASE_DAY
            self.state.day_message = "Игрок восстановлен, партия продолжается"
        self.check_winner()
        self.save()

    def missing_required_actions(self) -> List[str]:
        missing = []
        if self._living_roles({ROLE_DON}) and not self.state.don_done:
            missing.append("дон")
        if self._living_roles({ROLE_MAFIA, ROLE_DON}) and not self.state.mafia_done:
            missing.append("мафия")
        if self._living_roles({ROLE_COMMISSAR}) and not self.state.commissar_done:
            missing.append("комиссар")
        if self._living_roles({ROLE_DOCTOR}) and not self.state.doctor_done:
            missing.append("доктор")
        return missing

    def is_mafia(self, face_id: str) -> bool:
        return self.state.roles.get(face_id, ROLE_CIVILIAN) in {ROLE_MAFIA, ROLE_DON}

    def current_view(self) -> dict:
        phase = self.state.phase
        highlights = {}
        disabled = {}
        day_message = self.state.day_message if phase == PHASE_DAY else ""
        if phase == PHASE_MAFIA:
            for face_id, role in self.state.roles.items():
                if role in {ROLE_MAFIA, ROLE_DON} and self._is_live(face_id):
                    highlights[face_id] = {
                        "kind": "role_don" if role == ROLE_DON else "role_mafia",
                        "label": "Дон" if role == ROLE_DON else "Мафия",
                    }
            if self.state.mafia_target:
                highlights[self.state.mafia_target] = {"kind": "selected", "label": "Выбор мафии"}
        elif phase in {PHASE_DON, PHASE_DON_RESULT}:
            for face_id, role in self.state.roles.items():
                if role == ROLE_DON and self._is_live(face_id):
                    highlights[face_id] = {"kind": "role_don", "label": "Дон"}
            if phase == PHASE_DON and self.state.don_target:
                highlights[self.state.don_target] = {"kind": "selected", "label": "Выбор проверки"}
            elif phase == PHASE_DON_RESULT and self.state.don_target:
                is_commissar = self.state.roles.get(self.state.don_target) == ROLE_COMMISSAR
                highlights[self.state.don_target] = {
                    "kind": "don_check",
                    "label": "Комиссар" if is_commissar else "Не комиссар",
                }
        elif phase in {PHASE_COMMISSAR, PHASE_COMMISSAR_RESULT}:
            for face_id, role in self.state.roles.items():
                if role == ROLE_COMMISSAR and self._is_live(face_id):
                    highlights[face_id] = {"kind": "role_commissar", "label": "Комиссар"}
            for item in self.state.commissar_checks:
                face_id = item.get("face_id")
                if phase == PHASE_COMMISSAR_RESULT or item.get("night") != self.state.night_number:
                    highlights[face_id] = {
                        "kind": "mafia_check" if item.get("is_mafia") else "not_mafia_check",
                        "label": "Мафия" if item.get("is_mafia") else "Не мафия",
                    }
            if phase == PHASE_COMMISSAR_RESULT and self.state.commissar_target:
                highlights[self.state.commissar_target] = {
                    "kind": "mafia_check" if self.is_mafia(self.state.commissar_target) else "not_mafia_check",
                    "label": "Мафия" if self.is_mafia(self.state.commissar_target) else "Не мафия",
                }
            elif phase == PHASE_COMMISSAR and self.state.commissar_target:
                highlights[self.state.commissar_target] = {"kind": "selected", "label": "Выбор проверки"}
        elif phase == PHASE_DOCTOR:
            for face_id, role in self.state.roles.items():
                if role == ROLE_DOCTOR and self._is_live(face_id):
                    highlights[face_id] = {"kind": "role_doctor", "label": "Доктор"}
            if self.state.previous_doctor_target:
                disabled[self.state.previous_doctor_target] = "Лечили прошлой ночью"
            if self.state.doctor_target:
                highlights[self.state.doctor_target] = {"kind": "doctor", "label": "Выбор доктора"}
        return {
            "phase": phase,
            "night_number": self.state.night_number,
            "highlights": highlights,
            "disabled": disabled,
            "day_message": day_message,
            "current_selection": self.state.current_selection,
            "role_assignment": self.current_role_assignment(),
        }

    def _is_live(self, face_id: str) -> bool:
        player = self.session.players.get(face_id)
        return bool(player and player.game_status == "В игре")

    def _living_roles(self, roles: Set[str]) -> bool:
        for face_id, player in self.session.players.items():
            if player.game_status == "В игре" and self.state.roles.get(face_id, ROLE_CIVILIAN) in roles:
                return True
        return False

    def _require_phase(self, phase: str):
        if self.state.phase != phase:
            raise ValueError("Действие недоступно в текущей фазе")

    def _require_game_active(self):
        if self.state.winner:
            raise ValueError("Партия завершена: победа " + ("мафии" if self.state.winner == "мафия" else "мирных"))

    def _require_player(self, face_id: str):
        if face_id not in self.session.players:
            raise ValueError("Игрок не найден")

    def _require_live_player(self, face_id: str):
        self._require_player(face_id)
        if self.session.players[face_id].game_status != "В игре":
            raise ValueError("Выбывшего игрока нельзя выбрать")
