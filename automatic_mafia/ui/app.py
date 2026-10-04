import queue
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import tkinter as tk
from PIL import Image, ImageTk
from tkinter import ttk

from automatic_mafia.camera.source import detect_cameras
from automatic_mafia.models import Player
from automatic_mafia.storage.face_store import FaceStore
from automatic_mafia.storage.session_store import SessionStore
from automatic_mafia.vision.worker import CameraWorker


class MafiaApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Мафия — регистрация участников")
        self.geometry("1280x780")
        self.minsize(980, 620)
        self.configure(bg="#10131a")

        self.face_store = FaceStore()
        self.session = SessionStore()
        self.worker: Optional[CameraWorker] = None
        self.camera_devices = detect_cameras()
        self.current_photo_refs = []
        self.video_photo = None
        self.latest_ambiguous_track_id: Optional[str] = None
        self.session_name = f"Сессия {time.strftime('%Y-%m-%d %H:%M')}"
        self.players_signature = None
        self.table_window: Optional[tk.Toplevel] = None
        self.table_photo_refs = []

        self._build_style()
        self._build_ui()
        self._refresh_players()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(50, self._poll_worker)

    def _build_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TButton", padding=8, background="#283142", foreground="#f2f5fb", borderwidth=0)
        style.map("TButton", background=[("active", "#33415a")])
        style.configure("TCombobox", fieldbackground="#171d28", background="#171d28", foreground="#f2f5fb")

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
        self.table_button = ttk.Button(buttons, text="Открыть таблицу", command=self._open_players_table, state="disabled")
        self.table_button.pack(side="left", padx=8)
        ttk.Button(buttons, text="Новая сессия", command=self._new_session).pack(side="left", padx=8)

        stages = tk.Frame(self, bg="#10131a")
        stages.pack(fill="x", padx=18, pady=(0, 10))
        for index, title in enumerate(["Подготовка", "Первая ночь", "День", "Ночь", "Завершение"]):
            active = index == 0
            label = tk.Label(
                stages,
                text=title if active else f"{title} · следующий этап",
                bg="#2d3a52" if active else "#171d28",
                fg="#ffffff" if active else "#778399",
                padx=12,
                pady=6,
                font=("Arial", 10, "bold" if active else "normal"),
            )
            label.pack(side="left", padx=(0, 8))

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
        self.state_label.configure(text="регистрация завершена, идёт отслеживание")
        self.phase_label.configure(text="Подготовка · Состав зафиксирован")
        self.conductor_title.configure(text="Состав участников зафиксирован")
        self.instruction_label.configure(text="Новые лица больше не добавляются в партию. Можно проверить карточки, имена и видимость.")
        self.table_button.configure(state="normal")
        self._open_players_table()

    def _new_session(self):
        self.session.new_session()
        if self.worker:
            self.worker.registration_active = False
            self.worker.registration_finished = False
        if self.table_window and self.table_window.winfo_exists():
            self.table_window.destroy()
        self.table_window = None
        self.table_button.configure(state="disabled")
        self.state_label.configure(text="новая сессия, камера не регистрирует")
        self.phase_label.configure(text="Подготовка · Регистрация участников")
        self.conductor_title.configure(text="Регистрация участников")
        self.instruction_label.configure(text="Новая партия создана. Включите регистрацию, чтобы заново набрать состав игроков.")
        self._refresh_players()

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
        return tuple(
            (player.face_id, player.number, player.name, player.status, player.game_status, player.photo_path)
            for player in sorted(self.session.players.values(), key=lambda p: p.number)
        )

    def _add_player_card(self, player: Player):
        card = tk.Frame(self.cards_frame, bg="#1b2230", padx=10, pady=10)
        card.pack(fill="x", padx=4, pady=6)
        photo = self._load_player_photo(player.photo_path)
        if photo:
            self.current_photo_refs.append(photo)
            tk.Label(card, image=photo, bg="#1b2230").grid(row=0, column=0, rowspan=4, padx=(0, 10))
        tk.Label(card, text=f"Игрок {player.number}", bg="#1b2230", fg="#ffffff", font=("Arial", 15, "bold")).grid(row=0, column=1, sticky="w")
        status_text = f"{player.status} · {player.game_status}"
        tk.Label(card, text=status_text, bg="#1b2230", fg="#9fe3b1" if player.status == "В кадре" else "#d7b56d").grid(row=1, column=1, sticky="w")
        name_var = tk.StringVar(value=player.name)
        entry = tk.Entry(card, textvariable=name_var, bg="#121722", fg="#f7f9ff", insertbackground="#f7f9ff", relief="flat")
        entry.grid(row=2, column=1, sticky="ew", pady=6)
        entry.bind("<FocusOut>", lambda _e, fid=player.face_id, var=name_var: self._rename(fid, var.get()))
        entry.bind("<Return>", lambda _e, fid=player.face_id, var=name_var: self._rename(fid, var.get()))
        ttk.Button(card, text="Удалить", command=lambda fid=player.face_id: self._delete_player(fid)).grid(row=3, column=1, sticky="w")
        ttk.Button(card, text="Назначить неоднозначное", command=lambda fid=player.face_id: self._assign_ambiguous(fid)).grid(row=3, column=1, sticky="e")
        card.columnconfigure(1, weight=1)

    def _load_player_photo(self, path: str):
        if not path or not Path(path).exists():
            return None
        image = Image.open(path)
        image.thumbnail((92, 92), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(image)

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

    def _open_players_table(self):
        if self.table_window and self.table_window.winfo_exists():
            self.table_window.lift()
            self._refresh_players_table()
            return
        self.table_window = tk.Toplevel(self)
        self.table_window.title("Состав партии")
        self.table_window.geometry("980x680")
        self.table_window.minsize(760, 520)
        self.table_window.configure(bg="#10131a")
        self.table_window.protocol("WM_DELETE_WINDOW", self._close_players_table)

        header = tk.Frame(self.table_window, bg="#10131a")
        header.pack(fill="x", padx=18, pady=(16, 10))
        tk.Label(header, text="Состав партии", bg="#10131a", fg="#f7f9ff", font=("Arial", 22, "bold")).pack(side="left")
        self.table_count_label = tk.Label(header, text="", bg="#10131a", fg="#9ba8bd", font=("Arial", 12))
        self.table_count_label.pack(side="left", padx=14)
        ttk.Button(header, text="Обновить", command=self._refresh_players_table).pack(side="right")

        container = tk.Frame(self.table_window, bg="#151a24")
        container.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        self.table_canvas = tk.Canvas(container, bg="#151a24", highlightthickness=0)
        self.table_scroll = ttk.Scrollbar(container, orient="vertical", command=self.table_canvas.yview)
        self.table_frame = tk.Frame(self.table_canvas, bg="#151a24")
        self.table_frame.bind("<Configure>", lambda _e: self.table_canvas.configure(scrollregion=self.table_canvas.bbox("all")))
        self.table_canvas.create_window((0, 0), window=self.table_frame, anchor="nw")
        self.table_canvas.configure(yscrollcommand=self.table_scroll.set)
        self.table_canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        self.table_scroll.pack(side="right", fill="y", pady=10)
        self._refresh_players_table()

    def _close_players_table(self):
        if self.table_window and self.table_window.winfo_exists():
            self.table_window.destroy()
        self.table_window = None
        self.table_photo_refs = []

    def _refresh_players_table(self):
        if not self.table_window or not self.table_window.winfo_exists():
            return
        for child in self.table_frame.winfo_children():
            child.destroy()
        self.table_photo_refs = []
        players = sorted(self.session.players.values(), key=lambda p: p.number)
        self.table_count_label.configure(text=f"{len(players)} игроков")
        if not players:
            tk.Label(
                self.table_frame,
                text="Состав пуст",
                bg="#151a24",
                fg="#778399",
                font=("Arial", 16),
                pady=28,
            ).pack(fill="x")
            return
        for player in players:
            self._add_table_row(player)

    def _add_table_row(self, player: Player):
        row = tk.Frame(self.table_frame, bg="#1b2230", padx=12, pady=10)
        row.pack(fill="x", padx=4, pady=6)
        photo = self._load_table_photo(player.photo_path)
        if photo:
            self.table_photo_refs.append(photo)
            tk.Label(row, image=photo, bg="#1b2230").grid(row=0, column=0, rowspan=3, padx=(0, 14))
        tk.Label(row, text=f"#{player.number}", bg="#1b2230", fg="#ffffff", font=("Arial", 18, "bold"), width=5).grid(row=0, column=1, rowspan=3, sticky="n")
        name_var = tk.StringVar(value=player.name)
        name_entry = tk.Entry(row, textvariable=name_var, bg="#121722", fg="#f7f9ff", insertbackground="#f7f9ff", relief="flat", font=("Arial", 14))
        name_entry.grid(row=0, column=2, sticky="ew", padx=(0, 12), pady=(0, 8))
        name_entry.bind("<FocusOut>", lambda _e, fid=player.face_id, var=name_var: self._rename_from_table(fid, var.get()))
        name_entry.bind("<Return>", lambda _e, fid=player.face_id, var=name_var: self._rename_from_table(fid, var.get()))
        tk.Label(row, text=player.game_status, bg="#1b2230", fg="#c6d0e1", font=("Arial", 12)).grid(row=1, column=2, sticky="w")
        tk.Label(row, text=player.status, bg="#1b2230", fg="#9fe3b1" if player.status == "В кадре" else "#d7b56d", font=("Arial", 12)).grid(row=2, column=2, sticky="w")
        ttk.Button(row, text="Удалить", command=lambda fid=player.face_id: self._delete_player(fid)).grid(row=0, column=3, sticky="e")
        row.columnconfigure(2, weight=1)

    def _load_table_photo(self, path: str):
        if not path or not Path(path).exists():
            return None
        image = Image.open(path)
        image.thumbnail((132, 132), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(image)

    def _rename_from_table(self, face_id: str, name: str):
        self.session.rename_player(face_id, name)
        self._refresh_players()

    def _close(self):
        if self.worker:
            self.worker.stop()
            self.worker.join(timeout=2.0)
        if self.table_window and self.table_window.winfo_exists():
            self.table_window.destroy()
        self.destroy()
