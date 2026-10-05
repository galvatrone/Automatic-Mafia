from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QMainWindow

DARK_STYLE = """
QMainWindow, QWidget { background: #15161a; color: #ebe8e1; }
QGroupBox, QFrame { background: #202228; border: 1px solid #363943; border-radius: 8px; }
QLabel { color: #ebe8e1; }
QPushButton, QComboBox, QLineEdit, QSpinBox { background: #292c34; color: #ebe8e1; border: 1px solid #4a4d58; border-radius: 5px; padding: 6px; }
QPushButton:hover { background: #3a3440; border-color: #c9a66b; }
QPushButton:disabled { color: #72757e; }
QListWidget, QPlainTextEdit, QGraphicsView { background: #111216; color: #ebe8e1; border: 1px solid #363943; }
QScrollArea, QScrollArea QWidget { background: #15161a; }
"""

def frame_pixmap(frame, size: QSize) -> QPixmap:
    import cv2
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w, c = rgb.shape
    image = QImage(rgb.data, w, h, c * w, QImage.Format_RGB888).copy()
    return QPixmap.fromImage(image).scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

class ExperimentWindow(QMainWindow):
    def __init__(self, title: str):
        super().__init__()
        self.setWindowTitle(title)
        self.resize(1200, 780)
        self.setStyleSheet(DARK_STYLE)
