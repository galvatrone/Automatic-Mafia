import queue
import os
import time
from pathlib import Path
from typing import Optional

import cv2
from PySide6.QtCore import QObject, QTimer, Qt, Signal, QPointF, QRectF, QSize
from PySide6.QtGui import QBrush, QFont, QImage, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QShortcut, QPalette, QColor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from automatic_mafia.camera.source import detect_cameras
from automatic_mafia.models import Player
from automatic_mafia.storage.face_store import FaceStore
from automatic_mafia.storage.game_store import (
    ELIMINATED_VOTE,
    PHASE_COMMISSAR,
    PHASE_COMMISSAR_RESULT,
    PHASE_DAY,
    PHASE_DOCTOR,
    PHASE_DON,
    PHASE_DON_RESULT,
    PHASE_HIDDEN,
    PHASE_MAFIA,
    ROLE_CIVILIAN,
    ROLE_COMMISSAR,
    ROLE_DON,
    ROLE_DOCTOR,
    ROLE_MAFIA,
    GameStore,
)
from automatic_mafia.storage.session_store import SessionStore
from automatic_mafia.vision.worker import CameraWorker


BG = "#111114"
SURFACE = "#1b1b21"
RAISED = "#25252d"
BORDER = "#383840"
TEXT = "#f2eee7"
MUTED = "#a9a5a0"
GOLD = "#c9a66b"
BURGUNDY = "#742b38"
RED = "#d94a58"
GREEN = "#55a887"
BLUE = "#6c92d9"


def phase_name(phase: str) -> str:
    return {
        PHASE_HIDDEN: "СКРЫТЫЙ ЭКРАН",
        PHASE_DON: "ДОН",
        PHASE_DON_RESULT: "РЕЗУЛЬТАТ ПРОВЕРКИ ДОНА",
        PHASE_MAFIA: "МАФИЯ",
        PHASE_COMMISSAR: "КОМИССАР",
        PHASE_COMMISSAR_RESULT: "РЕЗУЛЬТАТ ПРОВЕРКИ",
        PHASE_DOCTOR: "ДОКТОР",
        PHASE_DAY: "ДЕНЬ",
    }.get(phase, "ПОДГОТОВКА")


def roman(value: int) -> str:
    result = ""
    for number, symbol in ((10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while value >= number:
            result += symbol
            value -= number
    return result


def card_fill(color: str, eliminated: bool = False) -> str:
    if eliminated:
        return "#25252a"
    return {
        GOLD: "#3a3020",
        RED: "#3b2027",
        GREEN: "#1e382f",
        TEXT: "#303036",
        BLUE: "#222f4a",
    }.get(color, RAISED)


class PlayerCard(QFrame):
    clicked = Signal(str)

    def __init__(self, player: Player, photo: Optional[QPixmap], public_label: str = "", color: str = BORDER, fill: str = RAISED, selectable: bool = True):
        super().__init__()
        self.face_id = player.face_id
        self.player_number = player.number
        self.player_name = player.name or f"Игрок {player.number}"
        self.photo = photo
        self.public_label = public_label
        self.border_color = QColor(color)
        self.fill_color = QColor(fill)
        self.eliminated = player.game_status != "В игре"
        self.setObjectName("playerCard")
        self.setProperty("selectable", selectable)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setMinimumSize(150, 150)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return width

    def sizeHint(self):
        return QSize(190, 190)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        radius = 16
        shadow_rect = rect.translated(0, 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 85))
        painter.drawRoundedRect(shadow_rect, radius, radius)
        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
        painter.setClipPath(clip)

        if self.photo and not self.photo.isNull():
            scaled = self.photo.scaled(rect.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            source = QRectF(
                max(0.0, (scaled.width() - rect.width()) / 2),
                max(0.0, (scaled.height() - rect.height()) / 2),
                min(rect.width(), scaled.width()),
                min(rect.height(), scaled.height()),
            )
            painter.drawPixmap(rect, scaled, source.toRect())
        else:
            painter.fillRect(rect, self.fill_color)
            silhouette = QPainterPath()
            center_x = rect.center().x()
            head_y = rect.top() + rect.height() * 0.38
            silhouette.addEllipse(QRectF(center_x - 25, head_y - 25, 50, 50))
            silhouette.moveTo(center_x - 60, rect.top() + rect.height() * 0.72)
            silhouette.cubicTo(center_x - 55, rect.top() + rect.height() * 0.53, center_x + 55, rect.top() + rect.height() * 0.53, center_x + 60, rect.top() + rect.height() * 0.72)
            painter.fillPath(silhouette, QColor(MUTED))

        if self.eliminated:
            painter.fillRect(rect, QColor(0, 0, 0, 155))
            painter.setPen(QPen(QColor(220, 55, 70), max(8, int(rect.width() * 0.055)), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            inset = rect.width() * 0.23
            painter.drawLine(QPointF(rect.left() + inset, rect.top() + inset), QPointF(rect.right() - inset, rect.bottom() - inset))
            painter.drawLine(QPointF(rect.right() - inset, rect.top() + inset), QPointF(rect.left() + inset, rect.bottom() - inset))
        elif self.border_color != QColor(BORDER):
            tint = QColor(self.fill_color)
            tint.setAlpha(125)
            painter.fillRect(rect, tint)

        painter.setClipping(False)
        painter.setPen(QPen(self.border_color, 3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)

        badge = QRectF(rect.left() + 10, rect.top() + 10, 42, 30)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(GOLD))
        painter.drawRoundedRect(badge, 6, 6)
        painter.setPen(QColor(BG))
        painter.setFont(QFont("DejaVu Sans", 12, QFont.Weight.Bold))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, f"{self.player_number:02d}")

        footer_height = max(48, int(rect.height() * 0.25))
        footer = QRectF(rect.left(), rect.bottom() - footer_height, rect.width(), footer_height)
        footer_gradient = QLinearGradient(0, footer.top() - footer_height * 0.7, 0, footer.bottom())
        footer_gradient.setColorAt(0.0, QColor(8, 8, 10, 0))
        footer_gradient.setColorAt(0.42, QColor(8, 8, 10, 170))
        footer_gradient.setColorAt(1.0, QColor(8, 8, 10, 235))
        painter.setBrush(footer_gradient)
        painter.drawRect(footer)
        painter.setPen(QColor(TEXT))
        painter.setFont(QFont("DejaVu Sans", 13, QFont.Weight.Bold))
        name_rect = footer.adjusted(10, 7, -10, -footer_height / 2)
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.player_name)
        if self.public_label:
            painter.setPen(QColor(GOLD if not self.eliminated else RED))
            painter.setFont(QFont("DejaVu Sans", 11, QFont.Weight.Bold))
            label_rect = footer.adjusted(8, footer_height / 2, -8, -4)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.public_label)
        painter.end()

    def mousePressEvent(self, event):
        if self.property("selectable") and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.face_id)
        super().mousePressEvent(event)


class BoardWindow(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.victory_fullscreen = False
        self.setWindowTitle("Automatic Mafia · Игровое табло")
        screen = QApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.availableGeometry())
        else:
            self.resize(1280, 820)
        self.setMinimumSize(900, 620)
        self._build()
        QShortcut(QKeySequence("Escape"), self, activated=self.showNormal)

    def _build(self):
        root = QWidget()
        root.setObjectName("boardRoot")
        self.setCentralWidget(root)
        self.root_layout = QVBoxLayout(root)
        self.root_layout.setContentsMargins(18, 20, 18, 20)
        self.root_layout.setSpacing(8)

        self.title = QLabel("МАФИЯ")
        self.title.setObjectName("boardTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.root_layout.addWidget(self.title)
        self.phase = QLabel()
        self.phase.setObjectName("boardPhase")
        self.phase.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.root_layout.addWidget(self.phase)
        self.instruction = QLabel()
        self.instruction.setObjectName("boardInstruction")
        self.instruction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.root_layout.addWidget(self.instruction)
        self.winner_banner = QLabel()
        self.winner_banner.setObjectName("winnerBanner")
        self.winner_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.winner_banner.hide()
        self.root_layout.addWidget(self.winner_banner)

        self.cards_host = QWidget()
        self.cards_host.setObjectName("cardsHost")
        self.cards_layout = QGridLayout(self.cards_host)
        self.cards_layout.setContentsMargins(0, 8, 0, 8)
        self.cards_layout.setHorizontalSpacing(14)
        self.cards_layout.setVerticalSpacing(14)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # The public board is a fixed visible table, not a scrolling list.
        self.scroll = self.cards_host
        self.root_layout.addWidget(self.cards_host, 1)

        self.public_message = QLabel()
        self.public_message.setObjectName("publicMessage")
        self.public_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.root_layout.addWidget(self.public_message)
        self.speech_panel = QWidget()
        self.speech_panel.setObjectName("speechPanel")
        speech_layout = QHBoxLayout(self.speech_panel)
        speech_layout.setContentsMargins(14, 6, 14, 6)
        speech_layout.setSpacing(14)
        self.timer_display = QLabel("00:30")
        self.timer_display.setObjectName("boardTimer")
        self.timer_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        speech_layout.addWidget(self.timer_display, 0)
        self.speaker_display = QLabel()
        self.speaker_display.setObjectName("speakerDisplay")
        speech_layout.addWidget(self.speaker_display, 1)
        self.speech_progress = QProgressBar()
        self.speech_progress.setObjectName("speechProgress")
        self.speech_progress.setRange(0, 30)
        self.speech_progress.setTextVisible(False)
        speech_layout.addWidget(self.speech_progress, 2)
        self.root_layout.addWidget(self.speech_panel)
        self.speech_panel.hide()

    def refresh(self):
        state = self.controller.game.state
        if state.winner:
            self.phase.setText("ПАРТИЯ ЗАВЕРШЕНА")
            self.instruction.setText("")
            self.winner_banner.setText("ПОБЕДА МИРНЫХ" if state.winner == "мирные" else "ПОБЕДА МАФИИ")
            self.winner_banner.show()
            self.scroll.hide()
            self.public_message.setText("Роли раскрываются только ведущим")
            self.public_message.show()
            self.speech_panel.hide()
            self.timer_display.clear()
            if not self.isFullScreen():
                self.showFullScreen()
                self.victory_fullscreen = True
            return
        if self.victory_fullscreen and self.isFullScreen():
            self.showNormal()
            self.victory_fullscreen = False
        self.winner_banner.hide()
        self.phase.setText("ДЕНЬ" if state.phase == PHASE_DAY else f"НОЧЬ {roman(state.night_number)} · {phase_name(state.phase)}")
        if state.phase == PHASE_HIDDEN and state.night_role_index >= 0:
            self.scroll.hide()
            self.instruction.setText("ГОРОД СПИТ")
            self.public_message.setText("Ожидание следующей роли")
            self.public_message.show()
            self.speech_panel.hide()
            return
        self.scroll.show()
        self.instruction.setText(self.controller.public_instruction())
        public_message = state.day_message if state.phase == PHASE_DAY else ""
        self.public_message.setText(public_message)
        self.public_message.setVisible(bool(public_message))
        timer = self.controller.public_view().get("timer", {})
        if state.phase == PHASE_DAY and timer.get("speaker_name"):
            remaining = int(timer.get("remaining", 30))
            self.timer_display.setText(f"{remaining // 60:02d}:{remaining % 60:02d}")
            self.speaker_display.setText(timer["speaker_name"])
            self.speech_progress.setValue(remaining)
            self.speech_panel.show()
        else:
            self.speech_panel.hide()
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        players = sorted(self.controller.session.players.values(), key=lambda player: player.number)
        columns = self._columns(len(players))
        rows = max(1, (len(players) + columns - 1) // columns)
        spacing = 14
        available_width = max(120, self.cards_host.width() - spacing * (columns - 1))
        available_height = max(120, self.cards_host.height() - 16 - spacing * (rows - 1))
        cell_size = max(120, min(available_width // columns, available_height // rows))
        public_view = self.controller.public_view()
        for index, player in enumerate(players):
            highlight = public_view["highlights"].get(player.face_id)
            disabled = public_view["disabled"].get(player.face_id)
            label = disabled or (highlight["label"] if highlight else player.elimination_reason)
            color = highlight["color"] if highlight else (RED if player.elimination_reason else BORDER)
            card = PlayerCard(player, self.controller.photo_pixmap(player.photo_path, 210), label, color, card_fill(color, bool(player.elimination_reason)), False)
            card.setFixedSize(cell_size, cell_size)
            self.cards_layout.addWidget(card, index // columns, index % columns)

    def _columns(self, count: int) -> int:
        if count <= 10:
            return min(5, max(1, count))
        return 5

    def move_to_screen(self, screen_index: int, fullscreen: bool = False):
        screens = QApplication.screens()
        if not screens:
            return
        screen = screens[max(0, min(screen_index, len(screens) - 1))]
        self.setGeometry(screen.availableGeometry())
        if fullscreen:
            self.showFullScreen()

    def closeEvent(self, event):
        self.hide()
        self.controller.refresh()
        event.ignore()


class SettingsDialog(QDialog):
    def __init__(self, board: BoardWindow, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки табло")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Монитор для игрового табло"))
        self.screen_box = QComboBox()
        for index, screen in enumerate(QApplication.screens()):
            self.screen_box.addItem(f"{index + 1}. {screen.name()}", index)
        layout.addWidget(self.screen_box)
        self.fullscreen = QPushButton("Развернуть на выбранном мониторе")
        self.fullscreen.clicked.connect(self._fullscreen)
        layout.addWidget(self.fullscreen)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.board = board

    def _fullscreen(self):
        self.board.move_to_screen(self.screen_box.currentData(), True)


class ControlWindow(QMainWindow):
    def __init__(self, app):
        super().__init__()
        self.app_controller = app
        self.setWindowTitle("Automatic Mafia · Пульт ведущего")
        self.resize(1480, 900)
        self.setMinimumSize(1080, 700)
        self._build()
        self._refresh()

    @property
    def game(self):
        return self.app_controller.game

    @property
    def session(self):
        return self.app_controller.session

    def closeEvent(self, event):
        self.app_controller.close_control()
        event.accept()

    def _build(self):
        root = QWidget()
        root.setObjectName("controlRoot")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(14)

        header = QHBoxLayout()
        brand = QLabel("Automatic Mafia · Пульт ведущего")
        brand.setObjectName("brand")
        header.addWidget(brand)
        header.addStretch()
        self.header_phase = QLabel()
        self.header_phase.setObjectName("headerPhase")
        header.addWidget(self.header_phase)
        self.live_count = QLabel()
        self.live_count.setObjectName("liveCount")
        header.addWidget(self.live_count)
        self.board_state = QLabel("Табло закрыто")
        self.board_state.setObjectName("boardState")
        header.addWidget(self.board_state)
        open_board = QPushButton("Открыть табло")
        open_board.clicked.connect(self.app_controller.open_board)
        header.addWidget(open_board)
        hide_board = QPushButton("Скрыть табло")
        hide_board.clicked.connect(self.app_controller.hide_board)
        header.addWidget(hide_board)
        settings = QPushButton("Настройки")
        settings.clicked.connect(self.app_controller.open_settings)
        header.addWidget(settings)
        outer.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        outer.addWidget(splitter, 1)

        self.nav = QListWidget()
        self.nav.setFixedWidth(180)
        for text in ("Подготовка", "Ночной экран", "Мафия", "Комиссар", "Доктор", "День", "История"):
            self.nav.addItem(QListWidgetItem(text))
        self.nav.currentRowChanged.connect(self._navigation_changed)
        splitter.addWidget(self.nav)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        self.control_phase = QLabel()
        self.control_phase.setObjectName("controlPhase")
        center_layout.addWidget(self.control_phase)
        self.camera_preview = QLabel("Камера не запущена")
        self.camera_preview.setObjectName("cameraPreview")
        self.camera_preview.setMinimumHeight(160)
        self.camera_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(self.camera_preview)
        camera_controls = QHBoxLayout()
        self.camera_box = QComboBox()
        self.camera_box.addItems([str(index) for index in self.app_controller.camera_devices])
        camera_controls.addWidget(self.camera_box)
        self.camera_button = QPushButton("Включить камеру")
        self.camera_button.clicked.connect(self.toggle_camera)
        camera_controls.addWidget(self.camera_button)
        register_button = QPushButton("Начать регистрацию")
        register_button.clicked.connect(self.begin_registration)
        camera_controls.addWidget(register_button)
        finish_button = QPushButton("Завершить регистрацию")
        finish_button.clicked.connect(self.finish_registration)
        camera_controls.addWidget(finish_button)
        center_layout.addLayout(camera_controls)
        self.cards_host = QWidget()
        self.cards_host.setObjectName("cardsHost")
        self.cards_layout = QGridLayout(self.cards_host)
        self.cards_layout.setSpacing(12)
        self.cards_scroll = QScrollArea()
        self.cards_scroll.setWidgetResizable(True)
        self.cards_scroll.setWidget(self.cards_host)
        center_layout.addWidget(self.cards_scroll, 1)
        splitter.addWidget(center)

        side = QFrame()
        side.setObjectName("sidePanel")
        side.setMinimumWidth(245)
        side_layout = QVBoxLayout(side)
        side_layout.addWidget(QLabel("Текущее действие"))
        self.action_description = QLabel()
        self.action_description.setWordWrap(True)
        side_layout.addWidget(self.action_description)
        side_layout.addSpacing(12)
        side_layout.addWidget(QLabel("Выбранный игрок"))
        self.selected_info = QLabel("Ничего не выбрано")
        self.selected_info.setWordWrap(True)
        side_layout.addWidget(self.selected_info)
        self.role_step_label = QLabel()
        self.role_step_label.setObjectName("roleStep")
        self.role_step_label.setWordWrap(True)
        side_layout.addWidget(self.role_step_label)
        self.role_count_label = QLabel()
        self.role_count_label.setObjectName("roleCount")
        side_layout.addWidget(self.role_count_label)
        self.role_confirm_button = QPushButton("Подтвердить и далее")
        self.role_confirm_button.clicked.connect(self.app_controller.confirm_role_assignment)
        side_layout.addWidget(self.role_confirm_button)
        self.role_back_button = QPushButton("Назад")
        self.role_back_button.clicked.connect(self.app_controller.back_role_assignment)
        side_layout.addWidget(self.role_back_button)
        side_layout.addStretch()
        self.role_button = QPushButton("Служебный режим ролей")
        self.role_button.clicked.connect(self.toggle_role_mode)
        side_layout.addWidget(self.role_button)
        self.next_role_button = QPushButton("Следующая роль")
        self.next_role_button.clicked.connect(self.advance_role)
        self.next_role_button.hide()
        side_layout.addWidget(self.next_role_button)
        self.restore_button = QPushButton("Восстановить выбранного")
        self.restore_button.clicked.connect(self.restore_selected)
        side_layout.addWidget(self.restore_button)
        self.name_button = QPushButton("Добавить имя")
        self.name_button.clicked.connect(self.rename_selected)
        side_layout.addWidget(self.name_button)
        self.remove_player_button = QPushButton("Удалить участника")
        self.remove_player_button.clicked.connect(self.remove_selected_player)
        side_layout.addWidget(self.remove_player_button)
        self.new_session_button = QPushButton("Новая партия · те же игроки")
        self.new_session_button.clicked.connect(self.new_game_same_players)
        side_layout.addWidget(self.new_session_button)
        self.clear_registration_button = QPushButton("Новая регистрация")
        self.clear_registration_button.clicked.connect(self.clear_registration)
        side_layout.addWidget(self.clear_registration_button)
        self.reveal_roles_button = QPushButton("Раскрыть роли")
        self.reveal_roles_button.clicked.connect(self.reveal_roles)
        self.reveal_roles_button.hide()
        side_layout.addWidget(self.reveal_roles_button)
        timer_title = QLabel("Таймер выступления")
        timer_title.setObjectName("panelTitle")
        side_layout.addWidget(timer_title)
        self.speaker_box = QComboBox()
        self.speaker_box.currentIndexChanged.connect(self._speaker_changed)
        side_layout.addWidget(self.speaker_box)
        self.timer_label = QLabel("00:30")
        self.timer_label.setObjectName("timerLabel")
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side_layout.addWidget(self.timer_label)
        timer_buttons = QHBoxLayout()
        for title, handler in (("Старт", self.app_controller.start_timer), ("Пауза", self.app_controller.pause_timer), ("Сброс", self.app_controller.reset_timer), ("Следующий", self.app_controller.next_speaker)):
            button = QPushButton(title)
            button.clicked.connect(handler)
            timer_buttons.addWidget(button)
        side_layout.addLayout(timer_buttons)
        splitter.addWidget(side)
        splitter.setSizes([180, 900, 280])

        bottom = QHBoxLayout()
        self.start_night_button = QPushButton("Начать ночь")
        self.start_night_button.clicked.connect(self.start_night)
        bottom.addWidget(self.start_night_button)
        self.confirm_button = QPushButton("Подтвердить")
        self.confirm_button.clicked.connect(self.confirm)
        bottom.addWidget(self.confirm_button)
        self.cancel_button = QPushButton("Отменить")
        self.cancel_button.clicked.connect(self.cancel)
        bottom.addWidget(self.cancel_button)
        self.end_turn_button = QPushButton("Завершить ход")
        self.end_turn_button.clicked.connect(self.next_step)
        bottom.addWidget(self.end_turn_button)
        self.no_action_button = QPushButton("Без действия")
        self.no_action_button.clicked.connect(self.no_action)
        bottom.addWidget(self.no_action_button)
        self.vote_button = QPushButton("Выгнать по голосованию")
        self.vote_button.clicked.connect(self.vote_out)
        bottom.addWidget(self.vote_button)
        bottom.addStretch()
        self.status = QLabel()
        self.status.setObjectName("statusLine")
        bottom.addWidget(self.status)
        outer.addLayout(bottom)

    def _navigation_changed(self, row: int):
        phase = {1: PHASE_HIDDEN, 2: PHASE_MAFIA, 3: PHASE_COMMISSAR, 4: PHASE_DOCTOR, 5: PHASE_DAY}.get(row)
        if phase:
            self.app_controller.set_phase(phase)

    def refresh_cards(self):
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        players = sorted(self.session.players.values(), key=lambda player: player.number)
        columns = 4 if len(players) > 12 else 3
        spacing = 12
        available_width = max(150, self.cards_scroll.viewport().width() - spacing * (columns - 1) - 10)
        cell_size = max(150, available_width // columns)
        view = self.game.current_view()
        for index, player in enumerate(players):
            highlight = view["highlights"].get(player.face_id)
            disabled = view["disabled"].get(player.face_id)
            if self.app_controller.role_mode:
                assigned_role = self.game.state.roles.get(player.face_id)
                role_colors = {
                    ROLE_DON: {"label": "Дон", "kind": "role_don"},
                    ROLE_MAFIA: {"label": "Мафия", "kind": "role_mafia"},
                    ROLE_COMMISSAR: {"label": "Комиссар", "kind": "role_commissar"},
                    ROLE_DOCTOR: {"label": "Доктор", "kind": "role_doctor"},
                    ROLE_CIVILIAN: {"label": "Мирный", "kind": "role_civilian"},
                }
                highlight = role_colors.get(assigned_role, highlight)
            if self.app_controller.confirmed_action and self.app_controller.confirmed_action[1] == player.face_id:
                confirmed_phase, _ = self.app_controller.confirmed_action
                highlight = {"label": "Цель мафии" if confirmed_phase == PHASE_MAFIA else "Лечение", "kind": "confirmed"}
            label = disabled or (highlight["label"] if highlight else player.elimination_reason)
            color = (RED if highlight["label"] == "Цель мафии" else GREEN) if highlight and highlight.get("kind") == "confirmed" else (self.app_controller.highlight_color(highlight) if highlight else (RED if player.elimination_reason else BORDER))
            card = PlayerCard(player, self.app_controller.photo_pixmap(player.photo_path, 170), label, color, card_fill(color, bool(player.elimination_reason)))
            card.setFixedSize(cell_size, cell_size)
            card.clicked.connect(self.select_player)
            self.cards_layout.addWidget(card, index // columns, index % columns)

    def select_player(self, face_id: str):
        if self.app_controller.role_mode:
            self.app_controller.select_role_candidate(face_id)
            return
        phase = self.game.state.phase
        try:
            if phase == PHASE_MAFIA:
                self.game.choose_mafia_target(face_id)
            elif phase == PHASE_DON:
                self.game.choose_don_check(face_id)
            elif phase == PHASE_COMMISSAR:
                self.game.choose_commissar_check(face_id)
            elif phase == PHASE_DOCTOR:
                self.game.choose_doctor_target(face_id)
            else:
                self.game.select_any_player(face_id)
            self.app_controller.status_text("Выбор сделан")
            self._refresh()
        except ValueError as error:
            self.app_controller.warning(str(error))

    def toggle_camera(self):
        if self.app_controller.worker and self.app_controller.worker.is_alive():
            self.app_controller.stop_camera()
            self.camera_button.setText("Включить камеру")
        else:
            self.app_controller.start_camera(int(self.camera_box.currentText()))
            self.camera_button.setText("Выключить камеру")

    def begin_registration(self):
        if self.app_controller.worker:
            self.app_controller.worker.registration_active = True
            self.app_controller.worker.registration_finished = False
            self.app_controller.status_text("Регистрация участников")

    def finish_registration(self):
        self.app_controller.finish_registration()

    def _refresh(self):
        state = self.game.state
        self.header_phase.setText("ДЕНЬ" if state.phase == PHASE_DAY else f"НОЧЬ {roman(state.night_number)} · {phase_name(state.phase)}")
        alive = sum(player.game_status == "В игре" for player in self.session.players.values())
        self.live_count.setText(f"В игре: {alive}")
        self.control_phase.setText(phase_name(state.phase))
        self.action_description.setText(self.app_controller.public_instruction())
        selected = self.session.players.get(state.current_selection or "")
        self.selected_info.setText(f"#{selected.number} · {selected.name or f'Игрок {selected.number}'}" if selected else "Ничего не выбрано")
        self.confirm_button.setText({PHASE_DON: "Проверить комиссара", PHASE_MAFIA: "Выбрать жертву", PHASE_COMMISSAR: "Проверить", PHASE_DOCTOR: "Лечить", PHASE_DAY: "Выгнать"}.get(state.phase, "Подтвердить"))
        finished = bool(state.winner)
        for button in (self.start_night_button, self.confirm_button, self.cancel_button, self.end_turn_button, self.no_action_button, self.vote_button, self.role_button):
            button.setEnabled(not finished)
        self.reveal_roles_button.setVisible(finished and not state.roles_revealed)
        self.start_night_button.setText("Начать ночь · Мафия" if state.phase in {PHASE_HIDDEN, PHASE_DAY} else "Начать ночь")
        self.end_turn_button.setText({PHASE_DON: "Завершить ход дона", PHASE_DON_RESULT: "Скрыть результат дона", PHASE_MAFIA: "Завершить ход мафии", PHASE_COMMISSAR_RESULT: "Скрыть результат", PHASE_DOCTOR: "Завершить ход доктора", PHASE_HIDDEN: "Разбудить следующую роль"}.get(state.phase, "Завершить ход"))
        if self.app_controller.role_mode:
            current_role = self.game.current_role_assignment()
            self.role_button.setText("Завершить знакомство" if current_role is None else f"Знакомство: {self.app_controller.role_title(current_role)}")
            self.role_step_label.setText("Сейчас просыпается: " + self.app_controller.role_title(current_role) if current_role else "Знакомство завершено")
            self.role_count_label.setText(f"Выбрано: {self.game.role_assignment_selected()} из {self.game.role_assignment_expected()}")
            self.role_confirm_button.setVisible(current_role is not None)
            self.role_back_button.setVisible(bool(self.game.state.role_assignment_history))
        else:
            self.role_button.setText("Назначить роли")
            self.role_step_label.clear()
            self.role_count_label.clear()
            self.role_confirm_button.hide()
            self.role_back_button.hide()
        self._refresh_speakers()
        self.timer_label.setText(self.app_controller.timer_text())
        self.refresh_cards()
        board = getattr(self.app_controller, "board", None)
        if board is not None:
            board.refresh()

    def start_night(self):
        try:
            if self.game.current_role_assignment() is not None:
                raise ValueError("Сначала завершите пошаговое назначение ролей")
            self.app_controller.confirmed_action = None
            self.game.start_night_sequence()
            self.app_controller.open_board()
            self.app_controller.status_text("Ночь началась")
            self._refresh()
        except ValueError as error:
            self.app_controller.warning(str(error))

    def confirm(self):
        try:
            if self.game.state.phase == PHASE_MAFIA:
                if not self.game.state.mafia_target:
                    raise ValueError("Сначала выберите цель мафии")
                self.app_controller.confirmed_action = (PHASE_MAFIA, self.game.state.mafia_target)
            elif self.game.state.phase == PHASE_DON:
                if not self.game.state.don_target:
                    raise ValueError("Сначала выберите игрока для проверки дона")
                self.game.finish_don_turn()
            elif self.game.state.phase == PHASE_COMMISSAR:
                self.game.finish_commissar_turn()
            elif self.game.state.phase == PHASE_DOCTOR:
                if not self.game.state.doctor_target:
                    raise ValueError("Сначала выберите цель лечения")
                self.app_controller.confirmed_action = (PHASE_DOCTOR, self.game.state.doctor_target)
            elif self.game.state.phase == PHASE_DAY:
                self.vote_out()
                return
            self.app_controller.status_text("Действие подтверждено")
            self._refresh()
        except ValueError as error:
            self.app_controller.warning(str(error))

    def cancel(self):
        phase = self.game.state.phase
        self.app_controller.confirmed_action = None
        if phase == PHASE_MAFIA:
            self.game.cancel_mafia_target()
        elif phase == PHASE_DON:
            self.game.cancel_don_check()
        elif phase == PHASE_COMMISSAR:
            self.game.cancel_commissar_check()
        elif phase == PHASE_DOCTOR:
            self.game.cancel_doctor_target()
        else:
            self.game.clear_selection()
        self._refresh()

    def next_step(self):
        try:
            if self.game.state.phase == PHASE_MAFIA:
                if not self.app_controller.confirmed_action:
                    raise ValueError("Сначала подтвердите цель мафии")
                self.game.finish_mafia_turn()
                self.app_controller.confirmed_action = None
            elif self.game.state.phase == PHASE_DON:
                if not self.game.state.don_target:
                    raise ValueError("Сначала выберите игрока для проверки дона")
                self.game.finish_don_turn()
            elif self.game.state.phase == PHASE_DOCTOR:
                if not self.app_controller.confirmed_action:
                    raise ValueError("Сначала подтвердите лечение")
                self.game.finish_doctor_turn()
                self.app_controller.confirmed_action = None
            elif self.game.state.phase in {PHASE_DON_RESULT, PHASE_COMMISSAR_RESULT, PHASE_HIDDEN}:
                self.game.advance_night_step()
            elif self.game.state.phase == PHASE_DAY:
                self.game.start_night_sequence()
            else:
                raise ValueError("Сначала подтвердите выбранное действие")
            self._refresh()
        except ValueError as error:
            self.app_controller.warning(str(error))

    def no_action(self):
        try:
            self.app_controller.confirmed_action = None
            phase = self.game.state.phase
            if phase == PHASE_MAFIA:
                self.game.finish_mafia_turn(no_action=True)
            elif phase == PHASE_DON:
                self.game.finish_don_turn(no_action=True)
            elif phase == PHASE_COMMISSAR:
                self.game.finish_commissar_turn(no_action=True)
            elif phase == PHASE_DOCTOR:
                self.game.finish_doctor_turn(no_action=True)
            else:
                raise ValueError("Без действия доступно только в ночной фазе")
            self._refresh()
        except ValueError as error:
            self.app_controller.warning(str(error))

    def vote_out(self):
        face_id = self.game.state.current_selection
        if not face_id:
            self.app_controller.warning("Выберите живого игрока")
            return
        if QMessageBox.question(self, "Выгнать по голосованию", "Подтвердить исключение игрока?") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.game.eliminate_by_vote(face_id)
            self._refresh()
        except ValueError as error:
            self.app_controller.warning(str(error))

    def toggle_role_mode(self):
        if self.app_controller.role_mode:
            self.app_controller.role_mode = False
        else:
            self.app_controller.begin_role_mode()
        self._refresh()

    def _speaker_changed(self, index: int):
        if index >= 0 and not self.app_controller.updating_speakers:
            self.app_controller.speaker_face_id = self.speaker_box.itemData(index)
            self.app_controller.timer_round_start_id = None
            self.app_controller.timer_round_moved = False

    def _refresh_speakers(self):
        current = self.app_controller.speaker_face_id
        self.app_controller.updating_speakers = True
        self.speaker_box.blockSignals(True)
        self.speaker_box.clear()
        for player in sorted(self.session.players.values(), key=lambda item: item.number):
            if player.game_status == "В игре":
                self.speaker_box.addItem(f"#{player.number} · {player.name or f'Игрок {player.number}'}", player.face_id)
        index = self.speaker_box.findData(current)
        if index < 0 and self.speaker_box.count():
            index = 0
            self.app_controller.speaker_face_id = self.speaker_box.itemData(0)
        self.speaker_box.setCurrentIndex(index)
        self.speaker_box.blockSignals(False)
        self.app_controller.updating_speakers = False

    def restore_selected(self):
        face_id = self.game.state.current_selection
        player = self.session.players.get(face_id or "")
        if not player or player.game_status == "В игре":
            self.app_controller.warning("Выберите выбывшего игрока")
            return
        self.game.restore_eliminated_player(face_id)
        self._refresh()

    def rename_selected(self):
        face_id = self.game.state.current_selection
        player = self.session.players.get(face_id or "")
        if not player:
            self.app_controller.warning("Сначала выберите игрока")
            return
        current = player.name or f"Игрок {player.number}"
        name, accepted = QInputDialog.getText(self, "Имя игрока", "Введите имя:", text=current)
        if accepted and name.strip():
            self.session.rename_player(face_id, name)
            self._refresh()

    def advance_role(self):
        self.app_controller.confirm_role_assignment()

    def new_game_same_players(self):
        if QMessageBox.question(self, "Новая партия", "Создать новую партию с теми же игроками?") == QMessageBox.StandardButton.Yes:
            self.game.new_game()
            self.app_controller.role_mode = False
            self.app_controller.confirmed_action = None
            self.app_controller.reset_timer()
            self._refresh()

    def clear_registration(self):
        if QMessageBox.question(self, "Новая регистрация", "Удалить текущий состав участников? База лиц останется сохранена.") != QMessageBox.StandardButton.Yes:
            return
        self.session.new_session()
        self.game.new_game()
        self.app_controller.role_mode = False
        self.app_controller.confirmed_action = None
        self.app_controller.reset_timer()
        self._refresh()

    def remove_selected_player(self):
        face_id = self.game.state.current_selection
        player = self.session.players.get(face_id or "")
        if not player:
            self.app_controller.warning("Сначала выберите участника")
            return
        if QMessageBox.question(self, "Удалить участника", f"Убрать игрока №{player.number} из текущего состава?") != QMessageBox.StandardButton.Yes:
            return
        self.session.remove_player(face_id)
        self.game.new_game()
        self._refresh()

    def reveal_roles(self):
        try:
            self.game.reveal_roles()
            self.app_controller.refresh()
        except ValueError as error:
            self.app_controller.warning(str(error))


class MafiaQtApp(QObject):
    def __init__(self, qt_app: QApplication):
        super().__init__()
        self.qt_app = qt_app
        self.face_store = FaceStore()
        self.session = SessionStore()
        self.game = GameStore(self.session)
        self.worker: Optional[CameraWorker] = None
        self.camera_devices = detect_cameras()
        self.role_mode = False
        self.confirmed_action = None
        self.speaker_face_id = None
        self.timer_remaining = 30
        self.timer_running = False
        self.timer_round_start_id = None
        self.timer_round_moved = False
        self.updating_speakers = False
        self.control = ControlWindow(self)
        self.board = BoardWindow(self)
        self.timer = QTimer()
        self.timer.timeout.connect(self.poll_worker)
        self.timer.start(50)
        self.speech_timer = QTimer()
        self.speech_timer.setInterval(1000)
        self.speech_timer.timeout.connect(self.tick_timer)

    def start(self):
        self.control.show()
        self.board.show()
        self.refresh()

    def refresh(self):
        if self.game.state.winner:
            self.timer_running = False
            self.speech_timer.stop()
        self.control._refresh()
        self.board.refresh()
        self.control.board_state.setText("Табло показано" if self.board.isVisible() else "Табло закрыто")

    def public_view(self):
        view = self.game.current_view()
        highlights = {}
        for face_id, highlight in view["highlights"].items():
            kind = highlight["kind"]
            if kind.startswith("role_"):
                visible_role_kinds = {
                    PHASE_DON: {"role_don"},
                    PHASE_DON_RESULT: {"role_don"},
                    PHASE_MAFIA: {"role_mafia", "role_don"},
                    PHASE_COMMISSAR: {"role_commissar"},
                    PHASE_COMMISSAR_RESULT: {"role_commissar"},
                    PHASE_DOCTOR: {"role_doctor"},
                }.get(self.game.state.phase, set())
                if kind not in visible_role_kinds:
                    continue
            color = {
                "selected": GOLD,
                "mafia": RED,
                "mafia_check": RED,
                "not_mafia_check": TEXT,
                "doctor": GREEN,
                "don_check": RED if highlight.get("label") == "Комиссар" else TEXT,
                "role_mafia": RED,
                "role_don": RED,
                "role_commissar": BLUE,
                "role_doctor": GREEN,
            }.get(kind, GOLD)
            highlights[face_id] = {"label": highlight["label"], "color": color}
        if self.game.state.roles_revealed:
            role_colors = {
                ROLE_MAFIA: RED,
                ROLE_DON: RED,
                ROLE_COMMISSAR: BLUE,
                ROLE_DOCTOR: GREEN,
                ROLE_CIVILIAN: TEXT,
            }
            for face_id, role in self.game.state.roles.items():
                highlights[face_id] = {"label": self.role_title(role), "color": role_colors.get(role, TEXT)}
        if self.confirmed_action:
            confirmed_phase, face_id = self.confirmed_action
            if confirmed_phase == PHASE_MAFIA:
                highlights[face_id] = {"label": "Цель мафии", "color": RED}
            elif confirmed_phase == PHASE_DOCTOR:
                highlights[face_id] = {"label": "Лечение", "color": GREEN}
        if self.role_mode:
            for face_id in self.game.state.role_assignment_pending:
                highlights[face_id] = {"label": "Выбран игрок", "color": GOLD}
        timer = self.timer_view()
        if self.game.state.phase == PHASE_DAY and timer["speaker_id"] and timer["speaker_id"] not in highlights:
            highlights[timer["speaker_id"]] = {"label": "Говорит", "color": GOLD}
        return {"highlights": highlights, "disabled": view["disabled"], "timer": timer}

    def public_instruction(self):
        if self.game.state.winner:
            return "ПОБЕДА МИРНЫХ" if self.game.state.winner == "мирные" else "ПОБЕДА МАФИИ"
        if self.role_mode:
            role = self.game.current_role_assignment()
            if role:
                return "Сейчас просыпается: " + self.role_title(role)
            return "Знакомство завершено"
        return {
            PHASE_HIDDEN: "Ожидание следующей роли",
            PHASE_DON: "Дон ищет комиссара",
            PHASE_DON_RESULT: "Результат проверки дона",
            PHASE_MAFIA: "Выберите игрока для убийства",
            PHASE_COMMISSAR: "Выберите игрока для проверки",
            PHASE_COMMISSAR_RESULT: "Результат проверки доступен комиссару",
            PHASE_DOCTOR: "Выберите игрока для лечения",
            PHASE_DAY: "Открытое обсуждение",
        }.get(self.game.state.phase, "Подготовка партии")

    @staticmethod
    def role_title(role):
        return {
            ROLE_MAFIA: "Мафия",
            ROLE_DON: "Дон",
            ROLE_COMMISSAR: "Комиссар",
            ROLE_DOCTOR: "Доктор",
            ROLE_CIVILIAN: "Мирные",
        }.get(role, "Роль")

    def timer_text(self):
        return f"{self.timer_remaining // 60:02d}:{self.timer_remaining % 60:02d}"

    def timer_view(self):
        speaker = self.session.players.get(self.speaker_face_id or "")
        return {
            "remaining": self.timer_remaining,
            "running": self.timer_running,
            "speaker_id": self.speaker_face_id,
            "speaker_name": f"#{speaker.number} · {speaker.name or f'Игрок {speaker.number}'}" if speaker else "",
        }

    def start_timer(self):
        living = self.living_speaker_ids()
        if not living:
            self.warning("Нет живых участников для выступления")
            return
        if self.speaker_face_id not in living:
            self.speaker_face_id = living[0]
        if self.timer_round_start_id is None:
            self.timer_round_start_id = self.speaker_face_id
            self.timer_round_moved = False
        if self.timer_remaining <= 0:
            self.timer_remaining = 30
        self.timer_running = True
        self.speech_timer.start()
        self.refresh()

    def pause_timer(self):
        self.timer_running = False
        self.speech_timer.stop()
        self.refresh()

    def reset_timer(self):
        self.timer_running = False
        self.speech_timer.stop()
        self.timer_remaining = 30
        self.timer_round_start_id = None
        self.timer_round_moved = False
        self.refresh()

    def next_speaker(self):
        ids = self.living_speaker_ids()
        if not ids:
            return
        if self.timer_round_start_id is None:
            self.timer_round_start_id = self.speaker_face_id if self.speaker_face_id in ids else ids[0]
        self.advance_speaker(ids)
        self.reset_timer()

    def living_speaker_ids(self):
        return [
            player.face_id
            for player in sorted(self.session.players.values(), key=lambda item: item.number)
            if player.game_status == "В игре"
        ]

    def advance_speaker(self, ids=None):
        ids = ids or self.living_speaker_ids()
        if not ids:
            return False
        current = ids.index(self.speaker_face_id) if self.speaker_face_id in ids else -1
        next_id = ids[(current + 1) % len(ids)]
        if self.timer_round_start_id and self.timer_round_moved and next_id == self.timer_round_start_id:
            return False
        self.speaker_face_id = next_id
        self.timer_round_moved = True
        return True

    def tick_timer(self):
        if not self.timer_running:
            return
        self.timer_remaining = max(0, self.timer_remaining - 1)
        if self.timer_remaining == 0:
            if not self.advance_speaker():
                self.timer_running = False
                self.speech_timer.stop()
                self.status_text("Круг выступлений завершён")
            else:
                self.timer_remaining = 30
                self.status_text("Следующий живой игрок")
        self.refresh()

    def highlight_color(self, highlight):
        if not highlight:
            return BORDER
        return {
            "selected": GOLD,
            "mafia": RED,
            "role_mafia": RED,
            "role_don": RED,
            "role_commissar": BLUE,
            "role_doctor": GREEN,
            "role_civilian": BORDER,
            "mafia_check": RED,
            "not_mafia_check": TEXT,
            "doctor": GREEN,
        }.get(highlight["kind"], BORDER)

    def photo_pixmap(self, path: str, size: int) -> Optional[QPixmap]:
        if not path or not Path(path).exists():
            return None
        image = cv2.imread(path)
        if image is None:
            return None
        player = next((item for item in self.session.players.values() if item.photo_path == path), None)
        if player and player.game_status != "В игре":
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        height, width = image.shape[:2]
        qimage = QImage(image.data, width, height, image.strides[0], QImage.Format.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(qimage).scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        return pixmap

    def open_board(self):
        self.board.show()
        self.board.raise_()
        self.refresh()

    def hide_board(self):
        self.board.hide()
        self.refresh()

    def open_settings(self):
        SettingsDialog(self.board, self.control).exec()

    def set_phase(self, phase: str):
        self.confirmed_action = None
        self.game.set_phase(phase)
        self.refresh()

    def begin_role_mode(self):
        if self.game.current_role_assignment() is None:
            self.game.state.role_assignment_index = 0
            self.game.state.role_assignment_pending = []
            self.game.state.role_assignment_history = []
            self.game.state.roles = {}
            self.game.save()
        self.role_mode = True
        self.game.set_phase(PHASE_HIDDEN)
        self.refresh()

    def select_role_candidate(self, face_id: str):
        try:
            self.game.select_role_candidate(face_id)
            self.status_text("Выбор роли обновлён")
            self.refresh()
        except ValueError as error:
            self.warning(str(error))

    def confirm_role_assignment(self):
        try:
            self.game.confirm_role_assignment()
            if self.game.current_role_assignment() is None:
                self.role_mode = False
                self.status_text("Знакомство завершено")
            else:
                self.status_text("Этап роли подтверждён")
            self.refresh()
        except ValueError as error:
            self.warning(str(error))

    def back_role_assignment(self):
        try:
            self.game.back_role_assignment()
            self.role_mode = True
            self.refresh()
        except ValueError as error:
            self.warning(str(error))

    def assign_current_role(self, face_id: str):
        self.select_role_candidate(face_id)

    def start_camera(self, index: int):
        if self.worker and self.worker.is_alive():
            return
        self.worker = CameraWorker(index, self.face_store, self.session)
        self.worker.registration_active = False
        self.worker.start()

    def stop_camera(self):
        if self.worker:
            self.worker.stop()
            self.worker.join(timeout=2.0)
            self.worker = None

    def finish_registration(self):
        if self.worker:
            self.worker.registration_active = False
            self.worker.registration_finished = True
        self.game.set_phase(PHASE_HIDDEN)
        self.open_board()
        self.status_text("Регистрация завершена")
        self.refresh()

    def poll_worker(self):
        if not self.worker:
            return
        try:
            while not self.worker.status_queue.empty():
                self.control.status.setText(self.worker.status_queue.get_nowait())
            frame, _observations, _metrics = self.worker.frame_queue.get_nowait()
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888).copy()
            self.control.camera_preview.setPixmap(QPixmap.fromImage(image).scaled(self.control.camera_preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        except queue.Empty:
            pass
        self.refresh()

    def status_text(self, text: str):
        self.control.status.setText(text)

    def warning(self, text: str):
        QMessageBox.warning(self.control, "Действие недоступно", text)

    def close(self):
        self.speech_timer.stop()
        if self.worker:
            self.worker.stop()
            self.worker.join(timeout=2.0)

    def close_control(self):
        self.close()
        self.qt_app.quit()


def run():
    import PySide6

    os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", str(Path(PySide6.__file__).resolve().parent / "Qt" / "plugins"))
    qt_app = QApplication.instance() or QApplication([])
    qt_app.setStyleSheet(
        f"""
        QWidget {{ color: {TEXT}; font-family: 'DejaVu Sans', sans-serif; font-size: 13px; }}
        QMainWindow, QWidget#controlRoot, QWidget#boardRoot {{ background: {BG}; }}
        QDialog, QMessageBox {{ background: {SURFACE}; color: {TEXT}; }}
        QMessageBox QLabel {{ color: {TEXT}; background: transparent; }}
        QMessageBox QPushButton {{ min-width: 90px; }}
        QLabel#brand {{ color: {TEXT}; font-size: 20px; font-weight: 700; }}
        QLabel#boardTitle {{ color: {GOLD}; font-family: Georgia, serif; font-size: 32px; font-weight: 700; letter-spacing: 3px; }}
        QLabel#boardPhase, QLabel#controlPhase {{ color: {GOLD}; font-size: 18px; font-weight: 700; }}
        QLabel#winnerBanner {{ color: {GOLD}; font-family: Georgia, serif; font-size: 64px; font-weight: 700; padding: 80px 20px; }}
        QLabel#boardInstruction, QLabel#statusLine {{ color: {MUTED}; }}
        QLabel#roleStep {{ color: {GOLD}; font-size: 16px; font-weight: 700; padding: 8px 0; }}
        QLabel#roleCount {{ color: {MUTED}; }}
        QLabel#panelTitle {{ color: {GOLD}; font-weight: 700; margin-top: 8px; }}
        QLabel#timerLabel, QLabel#boardTimer {{ color: {GOLD}; font-size: 25px; font-weight: 700; padding: 5px; }}
        QLabel#speakerDisplay {{ color: {TEXT}; font-size: 16px; font-weight: 700; }}
        QWidget#speechPanel {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
        QProgressBar#speechProgress {{ background: {BG}; border: 1px solid {BORDER}; border-radius: 4px; height: 8px; }}
        QProgressBar#speechProgress::chunk {{ background: {GOLD}; border-radius: 3px; }}
        QLabel#headerPhase, QLabel#liveCount, QLabel#boardState {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 8px 10px; color: {GOLD}; }}
        QFrame#sidePanel {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px; }}
        QLabel#numberBadge {{ background: {GOLD}; color: {BG}; border-radius: 5px; padding: 4px 6px; font-weight: 700; }}
        QLabel#playerName {{ color: {TEXT}; font-weight: 700; font-size: 14px; }}
        QLabel#cardResult {{ color: {GOLD}; font-weight: 700; min-height: 20px; }}
        QLabel#emptyPortrait {{ color: {MUTED}; font-size: 24px; }}
        QPushButton {{ background: {BURGUNDY}; color: {TEXT}; border: 1px solid #8e4855; border-radius: 7px; padding: 9px 13px; }}
        QPushButton:hover {{ background: #8a3948; }}
        QPushButton:pressed {{ background: #59212c; }}
        QPushButton:disabled {{ background: #2a292d; color: #77747a; border-color: #333238; }}
        QListWidget, QScrollArea, QLineEdit, QComboBox {{ background: {BG}; border: 1px solid {BORDER}; border-radius: 7px; color: {TEXT}; padding: 5px; }}
        QWidget#cardsHost {{ background: transparent; border: 0; padding: 0; }}
        QScrollArea QWidget {{ background: {BG}; }}
        QScrollArea QWidget#cardsHost {{ border: 0; border-radius: 0; }}
        QScrollArea::viewport {{ background: {BG}; border: 0; }}
        QAbstractScrollArea {{ background: {BG}; border: 0; }}
        QComboBox QAbstractItemView {{ background: {SURFACE}; color: {TEXT}; selection-background-color: {BURGUNDY}; selection-color: {TEXT}; border: 1px solid {BORDER}; }}
        QMenu {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; }}
        QListWidget::item:selected {{ background: {BURGUNDY}; color: {TEXT}; }}
        QScrollBar:vertical {{ background: {BG}; width: 10px; }}
        QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
        """
    )
    palette = qt_app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(SURFACE))
    palette.setColor(QPalette.ColorRole.Base, QColor(BG))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(RAISED))
    palette.setColor(QPalette.ColorRole.Button, QColor(BURGUNDY))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(BURGUNDY))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(TEXT))
    qt_app.setPalette(palette)
    controller = MafiaQtApp(qt_app)
    qt_app.aboutToQuit.connect(controller.close)
    controller.start()
    qt_app.exec()
