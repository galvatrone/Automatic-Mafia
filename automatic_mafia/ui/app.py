import queue
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import tkinter as tk
from PIL import Image, ImageTk
from tkinter import messagebox, ttk

from automatic_mafia.camera.source import detect_cameras
from automatic_mafia.models import Player
from automatic_mafia.storage.face_store import FaceStore
from automatic_mafia.storage.game_store import (
    ELIMINATED_NIGHT,
    ELIMINATED_VOTE,
    PHASE_COMMISSAR,
    PHASE_COMMISSAR_RESULT,
    PHASE_DAY,
    PHASE_DOCTOR,
    PHASE_HIDDEN,
    PHASE_MAFIA,
    ROLE_CIVILIAN,
    ROLE_COMMISSAR,
    ROLE_DON,
    ROLE_DOCTOR,
    ROLE_MAFIA,
    ROLES,
    GameStore,
)
from automatic_mafia.storage.session_store import SessionStore
from automatic_mafia.vision.worker import CameraWorker


class MafiaApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Мафия — регистрация участников")
        self.geometry("1280x780")
        self.minsize(980, 620)
        self.configure(bg="#151515")

        self.face_store = FaceStore()
        self.session = SessionStore()
        self.game = GameStore(self.session)
        self.worker: Optional[CameraWorker] = None
        self.camera_devices = detect_cameras()
        self.current_photo_refs = []
        self.video_photo = None
        self.latest_ambiguous_track_id: Optional[str] = None
        self.day_started_at: Optional[float] = None
        self.session_name = f"Сессия {time.strftime('%Y-%m-%d %H:%M')}"
        self.players_signature = None
        self.table_window: Optional[tk.Frame] = None
        self.table_photo_refs = []
        self.role_service_mode = tk.BooleanVar(value=False)
        self.registration_widgets = []

        self._build_style()
        self._build_ui()
        if self.session.players:
            self.table_button.configure(state="normal")
        self._refresh_players()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(50, self._poll_worker)

    def _build_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TButton", padding=8, background="#43232b", foreground="#f3e8d0", borderwidth=0)
        style.map("TButton", background=[("active", "#64313c")])
        style.configure("TCombobox", fieldbackground="#222222", background="#222222", foreground="#f3e8d0")

    def _build_ui(self):
        header = tk.Frame(self, bg="#10131a")
        header.pack(fill="x", padx=18, pady=(14, 8))
        tk.Label(header, text="Автоматический ведущий мафии", bg="#10131a", fg="#f7f9ff", font=("Arial", 20, "bold")).pack(side="left")
        tk.Label(header, text=self.session_name, bg="#10131a", fg="#9ba8bd", font=("Arial", 11)).pack(side="left", padx=(18, 0))
        self.phase_label = tk.Label(header, text="Подготовка · Регистрация участников", bg="#253044", fg="#f7f9ff", font=("Arial", 11, "bold"), padx=12, pady=5)
        self.phase_label.pack(side="left", padx=12)
        self.state_label = tk.Label(header, text="камера выключена", bg="#10131a", fg="#9ba8bd", font=("Arial", 11))
        self.state_label.pack(side="left", padx=16)

        self.camera_box = ttk.Combobox(header, values=[str(i) for i in self.camera_devices], width=6, state="readonly")
        self.camera_box.set(str(self.camera_devices[0]))
        self.camera_box.pack(side="right", padx=(8, 0))
        tk.Label(header, text="Камера", bg="#10131a", fg="#9ba8bd").pack(side="right")

        buttons = tk.Frame(self, bg="#10131a")
        buttons.pack(fill="x", padx=18, pady=(0, 10))
        self.camera_button = ttk.Button(buttons, text="Включить камеру", command=self._toggle_camera)
        self.camera_button.pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Начать регистрацию", command=self._start_registration).pack(side="left", padx=8)
        ttk.Button(buttons, text="Завершить регистрацию", command=self._finish_registration).pack(side="left", padx=8)
        self.table_button = ttk.Button(buttons, text="Показать таблицу", command=self._toggle_main_view, state="disabled")
        self.table_button.pack(side="left", padx=8)
        ttk.Button(buttons, text="Новая сессия", command=self._new_session).pack(side="left", padx=8)

        self.stage_bar = tk.Frame(self, bg="#10131a")
        self.stage_bar.pack(fill="x", padx=18, pady=(0, 10))
        self.hidden_button = ttk.Button(self.stage_bar, text="Ночной экран скрыт", command=lambda: self._set_game_phase(PHASE_HIDDEN))
        self.hidden_button.pack(side="left", padx=(0, 8))
        ttk.Button(self.stage_bar, text="Ход мафии", command=lambda: self._set_game_phase(PHASE_MAFIA)).pack(side="left", padx=(0, 8))
        ttk.Button(self.stage_bar, text="Ход комиссара", command=lambda: self._set_game_phase(PHASE_COMMISSAR)).pack(side="left", padx=(0, 8))
        ttk.Button(self.stage_bar, text="Ход доктора", command=lambda: self._set_game_phase(PHASE_DOCTOR)).pack(side="left", padx=(0, 8))
        ttk.Button(self.stage_bar, text="День", command=lambda: self._set_game_phase(PHASE_DAY)).pack(side="left", padx=(0, 8))
        ttk.Button(self.stage_bar, text="Следующая ночь", command=self._start_next_night).pack(side="left", padx=(16, 8))
        ttk.Button(self.stage_bar, text="Завершить ночь / Наступает день", command=self._resolve_night).pack(side="left", padx=(0, 8))

        body = tk.PanedWindow(self, orient=tk.HORIZONTAL, bg="#10131a", sashwidth=8)
        body.pack(fill="both", expand=True, padx=18)
        video_panel = tk.Frame(body, bg="#151a24")
        side_panel = tk.Frame(body, bg="#151a24")
        body.add(video_panel, minsize=620, stretch="always")
        body.add(side_panel, minsize=300)

        self.video_label = tk.Label(video_panel, text="Камера выключена", bg="#080b10", fg="#778399", font=("Arial", 16))
        self.video_label.pack(fill="both", expand=True, padx=10, pady=10)

        conductor = tk.Frame(video_panel, bg="#1b2230")
        conductor.pack(fill="x", padx=10, pady=(0, 10))
        tk.Label(conductor, text="Шаг ведущего", bg="#1b2230", fg="#9ba8bd", font=("Arial", 10)).pack(anchor="w", padx=12, pady=(10, 0))
        self.conductor_title = tk.Label(conductor, text="Регистрация участников", bg="#1b2230", fg="#ffffff", font=("Arial", 16, "bold"))
        self.conductor_title.pack(anchor="w", padx=12)
        self.game_phase_banner = tk.Label(conductor, text="", bg="#253044", fg="#ffffff", font=("Arial", 18, "bold"), padx=14, pady=8)
        self.game_phase_banner.pack(fill="x", padx=12, pady=(8, 0))
        self.instruction_label = tk.Label(
            conductor,
            text="Включите камеру и нажмите «Начать регистрацию». Участники по одному или вместе смотрят в камеру.",
            bg="#1b2230",
            fg="#c6d0e1",
            wraplength=760,
            justify="left",
        )
        self.instruction_label.pack(anchor="w", padx=12, pady=(2, 10))

        tk.Label(side_panel, text="Участники", bg="#151a24", fg="#f7f9ff", font=("Arial", 16, "bold")).pack(anchor="w", padx=12, pady=(12, 6))
        self.cards_canvas = tk.Canvas(side_panel, bg="#151a24", highlightthickness=0)
        self.cards_scroll = ttk.Scrollbar(side_panel, orient="vertical", command=self.cards_canvas.yview)
        self.cards_frame = tk.Frame(self.cards_canvas, bg="#151a24")
        self.cards_frame.bind("<Configure>", lambda e: self.cards_canvas.configure(scrollregion=self.cards_canvas.bbox("all")))
        self.cards_canvas.create_window((0, 0), window=self.cards_frame, anchor="nw")
        self.cards_canvas.configure(yscrollcommand=self.cards_scroll.set)
        self.cards_canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(0, 10))
        self.cards_scroll.pack(side="right", fill="y", pady=(0, 10))

        equipment = tk.Frame(self, bg="#10131a")
        equipment.pack(fill="x", padx=18, pady=(10, 0))
        self.equipment_label = tk.Label(equipment, text="Камера ноутбука — не подключена", bg="#10131a", fg="#c6d0e1", anchor="w")
        self.equipment_label.pack(side="left")
        tk.Label(equipment, text="Будущие боковые камеры — следующий этап", bg="#10131a", fg="#657186", anchor="w").pack(side="left", padx=16)

        self.status_label = tk.Label(self, text="Зарегистрировано: 0 · В кадре: 0 · Неизвестных: 0 · FPS: 0.0", bg="#10131a", fg="#c6d0e1", anchor="w")
        self.status_label.pack(fill="x", padx=18, pady=10)
        self.registration_widgets = [header, buttons, self.stage_bar, body, equipment, self.status_label]
        self.registration_header = header
        self.registration_buttons = buttons
        self.registration_body = body
        self.registration_equipment = equipment
        self._sync_game_ui()

    def _toggle_camera(self):
        if self.worker and self.worker.is_alive():
            self.worker.stop()
            self.worker = None
            self.camera_button.configure(text="Включить камеру")
            self.state_label.configure(text="камера выключается")
            return
        camera_index = int(self.camera_box.get())
        self.worker = CameraWorker(camera_index, self.face_store, self.session)
        self.worker.start()
        self.camera_button.configure(text="Выключить камеру")
        self.state_label.configure(text="камера включается")
        self.equipment_label.configure(text=f"Камера ноутбука {camera_index} — подключение")

    def _start_registration(self):
        if self.worker:
            self.worker.registration_active = True
            self.worker.registration_finished = False
        self.state_label.configure(text="регистрация участников")
        self.phase_label.configure(text="Подготовка · Регистрация участников")
        self.conductor_title.configure(text="Регистрация участников")
        self.instruction_label.configure(text="Посмотрите в камеру для регистрации. Новые лица получают стабильные номера только сейчас.")

    def _finish_registration(self):
        if self.worker:
            self.worker.registration_active = False
            self.worker.registration_finished = True
        self.game.set_phase(PHASE_HIDDEN)
        self.state_label.configure(text="регистрация завершена, идёт отслеживание")
        self.phase_label.configure(text="Подготовка · Состав зафиксирован")
        self.conductor_title.configure(text="Состав участников зафиксирован")
        self.instruction_label.configure(text="Новые лица больше не добавляются в партию. Можно проверить карточки, имена и видимость.")
        self.table_button.configure(state="normal", text="Вернуться к регистрации")
        self._sync_game_ui()
        self._open_players_table()

    def _new_session(self):
        self.session.new_session()
        self.game.new_game()
        if self.worker:
            self.worker.registration_active = False
            self.worker.registration_finished = False
        self._close_players_table()
        self.table_button.configure(state="disabled")
        self.state_label.configure(text="новая сессия, камера не регистрирует")
        self.phase_label.configure(text="Подготовка · Регистрация участников")
        self.conductor_title.configure(text="Регистрация участников")
        self.instruction_label.configure(text="Новая партия создана. Включите регистрацию, чтобы заново набрать состав игроков.")
        self._refresh_players()
        self._sync_game_ui()

    def _poll_worker(self):
        if self.worker:
            while not self.worker.status_queue.empty():
                status = self.worker.status_queue.get_nowait()
                self.state_label.configure(text=status)
                if status == "Камера включена":
                    self.equipment_label.configure(text=f"Камера ноутбука {self.worker.camera_index} — подключена")
                elif status == "Камера выключена":
                    self.equipment_label.configure(text="Камера ноутбука — не подключена")
                elif "Камера недоступна" in status or "Кадры перестали" in status:
                    self.equipment_label.configure(text=f"Камера ноутбука {self.worker.camera_index} — ошибка")
            try:
                frame, observations, metrics = self.worker.frame_queue.get_nowait()
                ambiguous = [obs for obs in observations if obs.status == "ambiguous"]
                self.latest_ambiguous_track_id = ambiguous[-1].track_id if ambiguous else None
                self._show_frame(frame)
                self._show_metrics(metrics)
                self._refresh_players_if_needed()
            except queue.Empty:
                pass
            if not self.worker.is_alive() and self.camera_button.cget("text") == "Выключить камеру":
                self.camera_button.configure(text="Включить камеру")
        self.after(50, self._poll_worker)

    def _show_frame(self, frame: np.ndarray):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        width = max(320, self.video_label.winfo_width())
        height = max(220, self.video_label.winfo_height())
        image.thumbnail((width, height), Image.Resampling.LANCZOS)
        self.video_photo = ImageTk.PhotoImage(image)
        self.video_label.configure(image=self.video_photo, text="")

    def _show_metrics(self, metrics: dict):
        self.status_label.configure(
            text=(
                f"Зарегистрировано: {metrics['registered']} · "
                f"В кадре: {metrics['visible_registered']} · "
                f"Неизвестных: {metrics['unknown']} · "
                f"Неоднозначных: {metrics['ambiguous']} · "
                f"FPS: {metrics['fps']:.1f}"
            )
        )

    def _refresh_players(self):
        for child in self.cards_frame.winfo_children():
            child.destroy()
        self.current_photo_refs = []
        for player in sorted(self.session.players.values(), key=lambda p: p.number):
            self._add_player_card(player)
        self.players_signature = self._players_signature()

    def _refresh_players_if_needed(self):
        signature = self._players_signature()
        if signature != self.players_signature:
            self._refresh_players()

    def _players_signature(self):
        view = self.game.current_view()
        game_screen = bool(self.table_window and self.table_window.winfo_exists())
        return tuple(
            (
                player.face_id,
                player.number,
                player.name,
                player.game_status,
                player.elimination_reason,
                player.photo_path,
                None if game_screen else player.status,
                view["phase"],
                view["highlights"].get(player.face_id),
                view["disabled"].get(player.face_id),
            )
            for player in sorted(self.session.players.values(), key=lambda p: p.number)
        )

    def _add_player_card(self, player: Player):
        view = self.game.current_view()
        highlight = view["highlights"].get(player.face_id)
        disabled_reason = view["disabled"].get(player.face_id)
        border_color = self._highlight_color(highlight)
        card_bg = "#1b2230" if player.game_status == "В игре" else "#171a20"
        card = tk.Frame(self.cards_frame, bg=border_color or card_bg, padx=2, pady=2)
        card.pack(fill="x", padx=4, pady=6)
        inner = tk.Frame(card, bg=card_bg, padx=10, pady=10)
        inner.pack(fill="x")
        inner.bind("<Button-1>", lambda _e, fid=player.face_id: self._card_clicked(fid))
        photo = self._load_player_photo(player.photo_path)
        if photo:
            self.current_photo_refs.append(photo)
            tk.Label(inner, image=photo, bg=card_bg).grid(row=0, column=0, rowspan=5, padx=(0, 10))
        tk.Label(inner, text=f"Игрок {player.number}", bg=card_bg, fg="#ffffff", font=("Arial", 15, "bold")).grid(row=0, column=1, sticky="w")
        status_text = f"{player.status} · {player.game_status}"
        if player.elimination_reason:
            status_text = f"{player.status} · {player.elimination_reason}"
        tk.Label(inner, text=status_text, bg=card_bg, fg="#9fe3b1" if player.status == "В кадре" else "#d7b56d").grid(row=1, column=1, sticky="w")
        if highlight:
            tk.Label(inner, text=highlight["label"], bg=card_bg, fg=border_color, font=("Arial", 11, "bold")).grid(row=2, column=1, sticky="w")
        elif disabled_reason:
            tk.Label(inner, text=disabled_reason, bg=card_bg, fg="#d7b56d", font=("Arial", 11, "bold")).grid(row=2, column=1, sticky="w")
        elif player.elimination_reason:
            tk.Label(inner, text=player.elimination_reason, bg=card_bg, fg="#ff6b6b", font=("Arial", 11, "bold")).grid(row=2, column=1, sticky="w")
        name_var = tk.StringVar(value=player.name)
        entry = tk.Entry(inner, textvariable=name_var, bg="#121722", fg="#f7f9ff", insertbackground="#f7f9ff", relief="flat")
        entry.grid(row=3, column=1, sticky="ew", pady=6)
        entry.bind("<FocusOut>", lambda _e, fid=player.face_id, var=name_var: self._rename(fid, var.get()))
        entry.bind("<Return>", lambda _e, fid=player.face_id, var=name_var: self._rename(fid, var.get()))
        ttk.Button(inner, text="Удалить", command=lambda fid=player.face_id: self._delete_player(fid)).grid(row=4, column=1, sticky="w")
        ttk.Button(inner, text="Назначить неоднозначное", command=lambda fid=player.face_id: self._assign_ambiguous(fid)).grid(row=4, column=1, sticky="e")
        inner.columnconfigure(1, weight=1)

    def _load_player_photo(self, path: str):
        if not path or not Path(path).exists():
            return None
        image = Image.open(path)
        if self._photo_is_eliminated(path):
            image = image.convert("L").convert("RGB")
            overlay = Image.new("RGB", image.size, "#000000")
            image = Image.blend(image, overlay, 0.45)
            self._draw_red_cross(image)
        image.thumbnail((92, 92), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(image)

    def _photo_is_eliminated(self, path: str) -> bool:
        for player in self.session.players.values():
            if player.photo_path == path:
                return player.game_status != "В игре"
        return False

    def _draw_red_cross(self, image: Image.Image):
        import PIL.ImageDraw

        draw = PIL.ImageDraw.Draw(image)
        width, height = image.size
        line_width = max(6, min(width, height) // 12)
        draw.line((8, 8, width - 8, height - 8), fill="#ff3131", width=line_width)
        draw.line((width - 8, 8, 8, height - 8), fill="#ff3131", width=line_width)

    def _highlight_color(self, highlight):
        if not highlight:
            return None
        return {
            "mafia": "#ff4d4d",
            "selected": "#d6af57",
            "role_mafia": "#b92d3d",
            "role_don": "#8e1d2c",
            "role_commissar": "#3e8cff",
            "role_doctor": "#45d483",
            "role_civilian": "#536174",
            "mafia_check": "#ff4d4d",
            "not_mafia_check": "#f4f7fb",
            "doctor": "#45d483",
        }.get(highlight["kind"], "#f4f7fb")

    def _phase_title(self, phase: str) -> str:
        return {
            PHASE_HIDDEN: "Ночной экран скрыт",
            PHASE_MAFIA: "Ход мафии",
            PHASE_COMMISSAR: "Ход комиссара",
            PHASE_COMMISSAR_RESULT: "Результат проверки",
            PHASE_DOCTOR: "Ход доктора",
            PHASE_DAY: "День",
        }.get(phase, "Подготовка")

    def _sync_game_ui(self):
        view = self.game.current_view()
        phase = view["phase"]
        title = self._phase_title(phase)
        self.phase_label.configure(text=f"Ночь {view['night_number']} · {title}" if phase != PHASE_DAY else "День")
        self.game_phase_banner.configure(text=title)
        if phase == PHASE_HIDDEN:
            self.conductor_title.configure(text="Ожидание следующей роли")
            self.instruction_label.configure(text="Нейтральный экран без тайных отметок. Выберите, какую роль разбудить дальше.")
        elif phase == PHASE_MAFIA:
            self.conductor_title.configure(text="Ход мафии")
            self.instruction_label.configure(text="Нажмите карточку цели, подтвердите выбор, затем нажмите «Дальше».")
        elif phase == PHASE_COMMISSAR:
            self.conductor_title.configure(text="Ход комиссара")
            self.instruction_label.configure(text="Нажмите карточку, подтвердите выбор, затем нажмите «Дальше».")
        elif phase == PHASE_COMMISSAR_RESULT:
            self.conductor_title.configure(text="Результат проверки")
            self.instruction_label.configure(text="Результат виден комиссару. Нажмите «Дальше», чтобы убрать его и разбудить следующую роль.")
        elif phase == PHASE_DOCTOR:
            self.conductor_title.configure(text="Ход доктора")
            self.instruction_label.configure(text="Нажмите карточку цели, подтвердите выбор, затем нажмите «Дальше». Прошлая цель недоступна.")
        elif phase == PHASE_DAY:
            self.conductor_title.configure(text="День")
            self.instruction_label.configure(text=view["day_message"] or "Открытое обсуждение и голосование. Тайные ночные сведения скрыты.")
        if self.table_window and self.table_window.winfo_exists():
            if phase == PHASE_DAY and self.day_started_at is None:
                self.day_started_at = time.time()
            elif phase != PHASE_DAY:
                self.day_started_at = None
            phase_names = {
                PHASE_HIDDEN: "СКРЫТЫЙ ЭКРАН",
                PHASE_MAFIA: "МАФИЯ",
                PHASE_COMMISSAR: "КОМИССАР",
                PHASE_COMMISSAR_RESULT: "РЕЗУЛЬТАТ ПРОВЕРКИ",
                PHASE_DOCTOR: "ДОКТОР",
                PHASE_DAY: "ДЕНЬ",
            }
            phase_name = phase_names.get(phase, "ПОДГОТОВКА")
            night_text = "ДЕНЬ" if phase == PHASE_DAY else f"НОЧЬ {self._roman_numeral(view['night_number'])} · {phase_name}"
            instruction = {
                PHASE_HIDDEN: "",
                PHASE_MAFIA: "Выберите игрока для убийства",
                PHASE_COMMISSAR: "Выберите игрока для проверки",
                PHASE_COMMISSAR_RESULT: "Результат проверки доступен комиссару",
                PHASE_DOCTOR: "Выберите игрока для лечения",
                PHASE_DAY: view["day_message"] or "Открытое обсуждение",
            }.get(phase, "")
            self.game_phase_label.configure(text=night_text)
            self.game_instruction_label.configure(text=instruction)
            if phase != PHASE_DAY:
                self.day_timer_label.configure(text="")
            primary_text = {
                PHASE_MAFIA: "Выбрать жертву",
                PHASE_COMMISSAR: "Проверить",
                PHASE_DOCTOR: "Лечить",
                PHASE_DAY: "Выгнать",
            }.get(phase, "Подтвердить")
            self.primary_action_button.configure(text=primary_text)
            for button_phase, button in self.phase_buttons.items():
                active = button_phase == phase or (button_phase == PHASE_COMMISSAR and phase == PHASE_COMMISSAR_RESULT)
                button.configure(bg="#8f6c32" if active else "#2b1d21", fg="#151515" if active else "#d5bd8a")
        self._refresh_players()
        self._refresh_players_table()

    def _roman_numeral(self, number: int) -> str:
        values = ((10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))
        result = ""
        for value, numeral in values:
            while number >= value:
                result += numeral
                number -= value
        return result

    def _primary_game_action(self):
        if self.game.state.phase == PHASE_DAY:
            self._vote_out_selected()
        else:
            self._confirm_phase_action()

    def _set_game_phase(self, phase: str):
        self.game.set_phase(phase)
        self.latest_ambiguous_track_id = None
        self.state_label.configure(text="")
        self._sync_game_ui()

    def _start_next_night(self):
        try:
            self.game.start_next_night()
            self.state_label.configure(text="началась следующая ночь")
            self._sync_game_ui()
        except ValueError as error:
            messagebox.showwarning("Нельзя начать ночь", str(error))

    def _start_night_sequence(self):
        try:
            self.game.start_night_sequence()
            self.state_label.configure(text="ночь началась")
            self._sync_game_ui()
        except ValueError as error:
            messagebox.showwarning("Нельзя начать ночь", str(error))

    def _next_night_step(self):
        phase = self.game.state.phase
        try:
            if phase == PHASE_COMMISSAR:
                self.game.finish_commissar_turn()
                self.state_label.configure(text="результат проверки показан")
            elif phase == PHASE_MAFIA:
                self.game.finish_mafia_turn()
                self.state_label.configure(text="ход мафии завершён")
            elif phase == PHASE_DOCTOR:
                self.game.finish_doctor_turn()
                self.state_label.configure(text="ход доктора завершён")
            elif phase in {PHASE_COMMISSAR_RESULT, PHASE_HIDDEN}:
                self.game.advance_night_step()
                self.state_label.configure(text="следующая роль разбужена")
            else:
                self.state_label.configure(text="сейчас переход не требуется")
            self._sync_game_ui()
        except ValueError as error:
            messagebox.showwarning("Нельзя продолжить ночь", str(error))

    def _resolve_night(self):
        missing = self.game.missing_required_actions()
        if missing:
            text = "Не завершены ходы: " + ", ".join(missing) + ". Вернуться к ним или отметить «Без действия»?"
            messagebox.showwarning("Ночь не завершена", text)
            return
        try:
            message = self.game.resolve_night()
            self.state_label.configure(text=message)
            self._sync_game_ui()
        except ValueError as error:
            messagebox.showwarning("Нельзя завершить ночь", str(error))

    def _card_clicked(self, face_id: str):
        if self.role_service_mode.get():
            try:
                role = self.game.current_role_assignment()
                self.game.assign_current_role(face_id)
                self.state_label.configure(text=f"назначено: {role}")
                if role in {ROLE_DON, ROLE_COMMISSAR, ROLE_DOCTOR}:
                    self.game.advance_role_assignment()
                self._sync_game_ui()
            except ValueError as error:
                messagebox.showwarning("Роль не назначена", str(error))
            return
        phase = self.game.state.phase
        selected = False
        try:
            if phase == PHASE_MAFIA:
                self.game.choose_mafia_target(face_id)
                selected = True
            elif phase == PHASE_COMMISSAR:
                self.game.choose_commissar_check(face_id)
                selected = True
            elif phase == PHASE_DOCTOR:
                self.game.choose_doctor_target(face_id)
                selected = True
            elif phase == PHASE_DAY:
                self.game.select_any_player(face_id)
                self.state_label.configure(text="игрок выбран для дневного действия")
            else:
                self.game.select_any_player(face_id)
                self.state_label.configure(text="игрок выбран")
            if selected and not messagebox.askyesno("Подтвердить выбор", "Оставить этого игрока целью?"):
                if phase == PHASE_MAFIA:
                    self.game.cancel_mafia_target()
                elif phase == PHASE_COMMISSAR:
                    self.game.cancel_commissar_check()
                elif phase == PHASE_DOCTOR:
                    self.game.cancel_doctor_target()
            self._sync_game_ui()
        except ValueError as error:
            messagebox.showwarning("Действие недоступно", str(error))

    def _rename(self, face_id: str, name: str):
        self.session.rename_player(face_id, name)

    def _delete_player(self, face_id: str):
        self.session.remove_player(face_id)
        self._refresh_players()
        self._refresh_players_table()

    def _assign_ambiguous(self, face_id: str):
        if not self.worker or not self.latest_ambiguous_track_id:
            self.state_label.configure(text="нет неоднозначного лица для назначения")
            return
        if self.worker.assign_track_to_player(self.latest_ambiguous_track_id, face_id):
            self.state_label.configure(text="неоднозначное лицо назначено выбранному игроку")
            self.latest_ambiguous_track_id = None
            self._refresh_players()
        else:
            self.state_label.configure(text="не удалось назначить: трек уже устарел")

    def _toggle_main_view(self):
        if self.table_window and self.table_window.winfo_exists():
            self._close_players_table()
        else:
            self._open_players_table()

    def _open_players_table(self):
        if self.table_window and self.table_window.winfo_exists():
            self._refresh_players_table()
            return
        for widget in self.registration_widgets:
            widget.pack_forget()
        self.table_window = tk.Frame(self, bg="#151515")
        self.table_window.pack(fill="both", expand=True)

        header = tk.Frame(self.table_window, bg="#151515")
        header.pack(fill="x", padx=18, pady=(16, 10))
        header.columnconfigure(1, weight=1)
        tk.Button(header, text="Выйти из таблицы", command=self._toggle_main_view, bg="#43232b", fg="#f3e8d0", activebackground="#64313c", activeforeground="#ffffff", relief="flat", padx=10, pady=6).grid(row=0, column=0, sticky="w")
        self.game_title_label = tk.Label(header, text="МАФИЯ", bg="#151515", fg="#f0dfb0", font=("Georgia", 28, "bold"))
        self.game_title_label.grid(row=0, column=1)
        self.table_count_label = tk.Label(header, text="", bg="#151515", fg="#8e7560", font=("Arial", 10))
        self.table_count_label.grid(row=0, column=2, sticky="e")
        self.role_mode_button = tk.Button(header, text="Назначить роли", command=self._toggle_role_service_mode, bg="#43232b", fg="#f3e8d0", activebackground="#64313c", activeforeground="#ffffff", relief="flat", padx=10, pady=6)
        self.role_mode_button.grid(row=0, column=3, sticky="e", padx=(12, 0))
        tk.Button(header, text="Начать ночь", command=self._start_night_sequence, bg="#8f6c32", fg="#151515", activebackground="#b38b45", relief="flat", padx=10, pady=6).grid(row=0, column=4, sticky="e", padx=(7, 0))
        self.game_phase_label = tk.Label(header, text="", bg="#151515", fg="#f0dfb0", font=("Arial", 16, "bold"))
        self.game_phase_label.grid(row=1, column=1, pady=(3, 0))
        self.game_instruction_label = tk.Label(header, text="", bg="#151515", fg="#b9a68a", font=("Arial", 11))
        self.game_instruction_label.grid(row=2, column=1, pady=(2, 0))
        self.day_timer_label = tk.Label(header, text="", bg="#151515", fg="#d6af57", font=("Arial", 11, "bold"))
        self.day_timer_label.grid(row=3, column=1, pady=(2, 0))

        stage_bar = tk.Frame(self.table_window, bg="#151515")
        stage_bar.pack(side="bottom", fill="x", padx=18, pady=(0, 10))
        self.phase_buttons = {}
        for phase, title in ((PHASE_MAFIA, "Мафия"), (PHASE_COMMISSAR, "Комиссар"), (PHASE_DOCTOR, "Доктор"), (PHASE_DAY, "День"), (PHASE_HIDDEN, "Скрыть экран")):
            button = tk.Button(stage_bar, text=title, command=lambda value=phase: self._set_game_phase(value), bg="#2b1d21", fg="#d5bd8a", activebackground="#5a3038", activeforeground="#ffffff", relief="flat", padx=12, pady=6)
            button.pack(side="left", padx=(0, 7))
            self.phase_buttons[phase] = button

        actions = tk.Frame(self.table_window, bg="#151515")
        actions.pack(side="bottom", fill="x", padx=18, pady=(0, 10))
        self.primary_action_button = tk.Button(actions, text="Подтвердить", command=self._primary_game_action, bg="#8f6c32", fg="#151515", activebackground="#b38b45", relief="flat", padx=14, pady=7)
        self.primary_action_button.pack(side="right", padx=(7, 0))
        tk.Button(actions, text="Отменить", command=self._cancel_phase_action, bg="#43232b", fg="#f3e8d0", activebackground="#64313c", relief="flat", padx=12, pady=7).pack(side="right", padx=7)
        self.end_turn_button = tk.Button(actions, text="Завершить ход", command=self._next_night_step, bg="#43232b", fg="#f3e8d0", activebackground="#64313c", relief="flat", padx=12, pady=7)
        self.end_turn_button.pack(side="right", padx=7)
        tk.Button(actions, text="Отменить исключение", command=self._restore_selected, bg="#2b1d21", fg="#d5bd8a", activebackground="#5a3038", relief="flat", padx=10, pady=7).pack(side="left", padx=7)
        self.role_stage_label = tk.Label(actions, text="", bg="#151515", fg="#b9a68a", font=("Arial", 11, "bold"))
        self.role_stage_label.pack(side="right", padx=(0, 12))
        self.next_role_button = ttk.Button(actions, text="Следующая роль", command=self._advance_role_assignment)
        self.next_role_button.pack(side="right", padx=(0, 8))
        self.next_role_button.configure(state="disabled")
        container = tk.Frame(self.table_window, bg="#151515")
        container.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        self.table_canvas = tk.Canvas(container, bg="#151515", highlightthickness=0)
        self.table_scroll = ttk.Scrollbar(container, orient="vertical", command=self.table_canvas.yview)
        self.table_frame = tk.Frame(self.table_canvas, bg="#151515")
        self.table_frame.bind("<Configure>", lambda _e: self.table_canvas.configure(scrollregion=self.table_canvas.bbox("all")))
        self.table_canvas_window_id = self.table_canvas.create_window((0, 0), window=self.table_frame, anchor="n")
        self.table_canvas.bind("<Configure>", self._center_table_grid)
        self.table_canvas.configure(yscrollcommand=self.table_scroll.set)
        self.table_canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        self.table_scroll.pack(side="right", fill="y", pady=10)
        self.hidden_screen = tk.Frame(self.table_window, bg="#151515")
        tk.Label(self.hidden_screen, text="ГОРОД СПИТ", bg="#151515", fg="#f0dfb0", font=("Georgia", 32, "bold")).place(relx=0.5, rely=0.44, anchor="center")
        tk.Label(self.hidden_screen, text="Ожидание следующей роли", bg="#151515", fg="#b9a68a", font=("Arial", 14)).place(relx=0.5, rely=0.54, anchor="center")
        self.hidden_screen.place_forget()
        self._sync_game_ui()
        self.after(1000, self._tick_day_timer)

    def _center_table_grid(self, event):
        if hasattr(self, "table_canvas_window_id"):
            self.table_canvas.coords(self.table_canvas_window_id, event.width / 2, 0)

    def _tick_day_timer(self):
        if self.table_window and self.table_window.winfo_exists() and self.game.state.phase == PHASE_DAY and self.day_started_at:
            elapsed = int(time.time() - self.day_started_at)
            self.day_timer_label.configure(text=f"Время выступления  {elapsed // 60:02d}:{elapsed % 60:02d}")
        self.after(1000, self._tick_day_timer)

    def _close_players_table(self):
        if self.table_window and self.table_window.winfo_exists():
            self.table_window.destroy()
        self.table_window = None
        self.table_photo_refs = []
        self.role_service_mode.set(False)
        self.registration_header.pack(fill="x", padx=18, pady=(14, 8))
        self.registration_buttons.pack(fill="x", padx=18, pady=(0, 10))
        self.stage_bar.pack(fill="x", padx=18, pady=(0, 10))
        self.registration_body.pack(fill="both", expand=True, padx=18)
        self.registration_equipment.pack(fill="x", padx=18, pady=(10, 0))
        self.status_label.pack(fill="x", padx=18, pady=10)
        if self.session.players:
            self.table_button.configure(text="Показать таблицу", state="normal")

    def _refresh_players_table(self):
        if not self.table_window or not self.table_window.winfo_exists():
            return
        if self.game.state.phase == PHASE_HIDDEN and self.game.state.night_role_index >= 0:
            self.hidden_screen.place(relx=0, rely=0, relwidth=1, relheight=1)
            return
        self.hidden_screen.place_forget()
        for child in self.table_frame.winfo_children():
            child.destroy()
        self.table_photo_refs = []
        players = sorted(self.session.players.values(), key=lambda p: p.number)
        self.table_count_label.configure(text=f"{len(players)} игроков")
        role_stage = self.game.current_role_assignment()
        self.role_stage_label.configure(
            text=f"Назначается: {role_stage}" if self.role_service_mode.get() and role_stage else ""
        )
        self.next_role_button.configure(
            state="normal" if self.role_service_mode.get() and role_stage else "disabled"
        )
        if not players:
            tk.Label(
                self.table_frame,
                text="Состав пуст",
                bg="#151515",
                fg="#778399",
                font=("Arial", 16),
                pady=28,
            ).pack(fill="x")
            return
        columns = min(5, max(1, len(players)))
        for index, player in enumerate(players):
            self._add_table_row(player, index, columns)

    def _add_table_row(self, player: Player, index: int, columns: int):
        view = self.game.current_view()
        highlight = view["highlights"].get(player.face_id)
        if self.role_service_mode.get():
            role = self.game.state.roles.get(player.face_id)
            role_highlights = {
                ROLE_DON: {"kind": "role_don", "label": "Дон"},
                ROLE_MAFIA: {"kind": "role_mafia", "label": "Мафия"},
                ROLE_COMMISSAR: {"kind": "role_commissar", "label": "Комиссар"},
                ROLE_DOCTOR: {"kind": "role_doctor", "label": "Доктор"},
                ROLE_CIVILIAN: {"kind": "role_civilian", "label": "Мирный"},
            }
            highlight = role_highlights.get(role, highlight)
        disabled_reason = view["disabled"].get(player.face_id)
        border_color = self._highlight_color(highlight)
        row_bg = "#222222" if player.game_status == "В игре" else "#181818"
        card_bg = row_bg
        card_width = max(170, min(238, (max(self.winfo_width(), 980) - 100) // columns))
        row = tk.Frame(self.table_frame, bg=border_color or "#51453a", padx=2, pady=2, width=card_width, height=card_width)
        row.grid(row=index // columns, column=index % columns, padx=7, pady=7, sticky="nsew")
        row.grid_propagate(False)
        self.table_frame.grid_columnconfigure(index % columns, weight=1, uniform="player-card")
        inner = tk.Frame(row, bg=card_bg, padx=10, pady=10)
        inner.pack(fill="both", expand=True)
        tk.Label(row, text=f"{player.number:02d}", bg="#b08a43", fg="#151515", font=("Arial", 10, "bold"), padx=6, pady=2).place(x=8, y=8)
        photo = self._load_table_photo(player.photo_path, max_size=max(120, card_width - 34))
        if photo:
            self.table_photo_refs.append(photo)
            tk.Label(inner, image=photo, bg=card_bg).pack(pady=(12, 5))
        tk.Label(inner, text=player.name or "Без имени", bg=card_bg, fg="#f3e8d0", font=("Arial", 14, "bold"), wraplength=max(120, card_width - 25)).pack()
        label = ""
        color = "#d6af57"
        if highlight:
            label = highlight["label"]
            color = border_color
        elif disabled_reason:
            label = f"🔒 {disabled_reason}"
            color = "#d7b56d"
        elif player.elimination_reason:
            label = player.elimination_reason
            color = "#ff6b6b"
        tk.Label(inner, text=label, bg=card_bg, fg=color, font=("Arial", 11, "bold")).pack(pady=(3, 0))
        self._bind_card_action(row, player.face_id)

    def _bind_card_action(self, widget, face_id: str):
        if isinstance(widget, (tk.Entry, ttk.Button, ttk.Combobox)):
            return
        widget.bind("<Button-1>", lambda _e, fid=face_id: self._card_clicked(fid), add="+")
        for child in widget.winfo_children():
            self._bind_card_action(child, face_id)

    def _load_table_photo(self, path: str, max_size: int = 132):
        if not path or not Path(path).exists():
            return None
        image = Image.open(path)
        if self._photo_is_eliminated(path):
            image = image.convert("L").convert("RGB")
            overlay = Image.new("RGB", image.size, "#000000")
            image = Image.blend(image, overlay, 0.45)
            self._draw_red_cross(image)
        image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(image)

    def _rename_from_table(self, face_id: str, name: str):
        self.session.rename_player(face_id, name)
        self._refresh_players()

    def _assign_role(self, face_id: str, role: str):
        try:
            self.game.assign_role(face_id, role)
            self.state_label.configure(text="роль назначена")
        except ValueError as error:
            messagebox.showwarning("Роль не назначена", str(error))

    def _toggle_self_heal(self):
        self.game.set_allow_self_heal(self.self_heal_var.get())

    def _toggle_role_service_mode(self):
        self.role_service_mode.set(not self.role_service_mode.get())
        if self.role_service_mode.get():
            self.role_mode_button.configure(text="Скрыть роли")
            self.state_label.configure(text="служебный режим: роли видны только ведущему на этом экране")
        else:
            self.role_mode_button.configure(text="Назначить роли")
            self.state_label.configure(text="роли скрыты")
        self._refresh_players_table()

    def _advance_role_assignment(self):
        if not self.role_service_mode.get():
            return
        try:
            current = self.game.current_role_assignment()
            self.game.advance_role_assignment()
            next_role = self.game.current_role_assignment()
            self.state_label.configure(text=f"этап {current} завершён" if next_role else "назначение ролей завершено")
            if next_role is None:
                self.role_service_mode.set(False)
                self.role_mode_button.configure(text="Назначить роли")
            self._sync_game_ui()
        except ValueError as error:
            messagebox.showwarning("Нельзя перейти дальше", str(error))

    def _confirm_phase_action(self):
        phase = self.game.state.phase
        try:
            if phase == PHASE_MAFIA:
                self.game.finish_mafia_turn()
                self.state_label.configure(text="ход мафии завершён")
            elif phase == PHASE_COMMISSAR:
                self.game.finish_commissar_turn()
                self.state_label.configure(text="ход комиссара завершён")
            elif phase == PHASE_DOCTOR:
                self.game.finish_doctor_turn()
                self.state_label.configure(text="ход доктора завершён")
            else:
                self.state_label.configure(text="в этой фазе нечего подтверждать")
            self._sync_game_ui()
        except ValueError as error:
            messagebox.showwarning("Нельзя подтвердить", str(error))

    def _cancel_phase_action(self):
        phase = self.game.state.phase
        if phase == PHASE_MAFIA:
            self.game.cancel_mafia_target()
        elif phase == PHASE_COMMISSAR:
            self.game.cancel_commissar_check()
        elif phase == PHASE_DOCTOR:
            self.game.cancel_doctor_target()
        else:
            self.game.clear_selection()
        self.state_label.configure(text="выбор очищен")
        self._sync_game_ui()

    def _mark_no_action(self):
        phase = self.game.state.phase
        try:
            if phase == PHASE_MAFIA:
                self.game.finish_mafia_turn(no_action=True)
                self.state_label.configure(text="мафия без действия")
            elif phase == PHASE_COMMISSAR:
                self.game.finish_commissar_turn(no_action=True)
                self.state_label.configure(text="комиссар без действия")
            elif phase == PHASE_DOCTOR:
                self.game.finish_doctor_turn(no_action=True)
                self.state_label.configure(text="доктор без действия")
            else:
                self.state_label.configure(text="без действия доступно только ночью")
            self._sync_game_ui()
        except ValueError as error:
            messagebox.showwarning("Нельзя отметить", str(error))

    def _vote_out_selected(self):
        face_id = self.game.state.current_selection
        if not face_id:
            messagebox.showwarning("Не выбран игрок", "Сначала нажмите карточку живого игрока днём.")
            return
        try:
            self.game.eliminate_by_vote(face_id)
            self.state_label.configure(text="игрок выгнан голосованием")
            self._sync_game_ui()
        except ValueError as error:
            messagebox.showwarning("Нельзя исключить", str(error))

    def _restore_selected(self):
        face_id = self.game.state.current_selection
        if not face_id:
            messagebox.showwarning("Не выбран игрок", "Сначала нажмите карточку выбывшего игрока.")
            return
        player = self.session.players.get(face_id)
        if not player or player.game_status == "В игре":
            messagebox.showwarning("Отмена недоступна", "Выбранный игрок не выбыл.")
            return
        self.game.restore_eliminated_player(face_id)
        self.state_label.configure(text="игрок возвращён в игру")
        self._sync_game_ui()

    def _close(self):
        if self.worker:
            self.worker.stop()
            self.worker.join(timeout=2.0)
        if self.table_window and self.table_window.winfo_exists():
            self.table_window.destroy()
        self.destroy()
