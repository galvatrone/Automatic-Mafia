import argparse, json, math, sys
from dataclasses import dataclass
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QObject, Qt, QRectF, Signal
from PySide6.QtGui import QBrush, QColor, QPen, QPainter
from PySide6.QtWidgets import QApplication, QFileDialog, QGraphicsEllipseItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView, QLabel, QListWidget, QPushButton, QSplitter, QVBoxLayout, QWidget
from shared.config import load_json, save_json
from shared.exchange import read_participants
from shared.ui import ExperimentWindow

@dataclass
class Participant:
    person_id: str
    seat_id: str
    label: str = ""
    photo_path: str = ""
    player_number: int|None=None

class Node(QObject, QGraphicsEllipseItem):
    clicked=Signal(str)
    def __init__(self, participant, x, y):
        QObject.__init__(self); QGraphicsEllipseItem.__init__(self,-42,-42,84,84); self.person_id=participant.person_id; self.setPos(x,y); self.setBrush(QBrush(QColor("#282b34"))); self.setPen(QPen(QColor("#c9a66b"),2)); self.setFlag(QGraphicsEllipseItem.ItemIsMovable,True)
        text = participant.label or participant.person_id
        label=QGraphicsSimpleTextItem(text,self); label.setBrush(QBrush(QColor("#ebe8e1"))); label.setPos(-min(34, len(text)*4),-8)
    def mousePressEvent(self,event): self.clicked.emit(self.person_id); super().mousePressEvent(event)

class Model:
    def __init__(self, participants):
        normalized = [p if isinstance(p, dict) else {"person_id": str(p), "label": str(p), "photo_path": ""} for p in participants]
        self.people={p["person_id"]:Participant(p["person_id"],f"seat-{i+1}",p.get("label",p["person_id"]),p.get("photo_path", "")) for i,p in enumerate(normalized)}; self.edges={}; self.chain=[]; self.start=None; self.direction="clockwise"
    def click(self, person):
        if not self.chain: self.start=person; self.chain=[person]; return f"Старт: {person}"
        current=self.chain[-1]
        if person==self.start and len(self.chain)>2:
            self.edges[current]=person; return "Цикл замкнут"
        if person in self.chain: return "Участник уже есть в цепочке"
        self.edges[current]=person; self.chain.append(person); return f"{current} → {person}"
    def undo(self):
        if len(self.chain)>1:
            removed=self.chain.pop(); self.edges.pop(self.chain[-1],None); return f"Убран {removed}"
        if self.chain: self.chain=[]; self.start=None; return "Старт сброшен"
        return "Нечего отменять"
    def validate(self):
        if not self.start or len(self.chain)!=len(self.people): return False,"Включите каждого участника один раз"
        if self.edges.get(self.chain[-1])!=self.start: return False,"Последняя связь не замкнута на старт"
        if len(self.edges)!=len(self.people) or len(set(self.chain))!=len(self.people): return False,"У каждого должен быть один следующий сосед"
        return True,"Единый цикл корректен"
    def confirm(self):
        ok,msg=self.validate()
        if not ok:return False,msg
        for i,n in enumerate(self.chain,1): self.people[n].player_number=i
        return True,"Номера назначены"
    def save(self,path): save_json(path,{"direction":self.direction,"start":self.start,"chain":self.chain,"edges":self.edges,"participants":[p.__dict__ for p in self.people.values()]})

class Window(ExperimentWindow):
    def __init__(self, participants, exchange_path=None):
        super().__init__("Automatic Mafia · эксперимент virtual_table"); self.exchange_path=exchange_path; self.model=Model(participants); self.scene=QGraphicsScene(self); self.scene.setSceneRect(0,0,900,700); self.view=QGraphicsView(self.scene); self.view.setRenderHint(QPainter.Antialiasing); self.view.setMinimumSize(800,650); self.nodes={}; self.edges=[]
        self.build_scene()
        self.status=QLabel("Выберите стартового участника на схеме")
        self.list=QListWidget(); self.refresh_list()
        load=QPushButton("Загрузить теги person_face"); load.clicked.connect(self.load_exchange); undo=QPushButton("Назад"); undo.clicked.connect(self.undo); reverse=QPushButton("Развернуть направление"); reverse.clicked.connect(self.reverse); suggest=QPushButton("Предложить соседей"); suggest.clicked.connect(self.suggest); confirm=QPushButton("Подтвердить круг и назначить номера"); confirm.clicked.connect(self.confirm); save=QPushButton("Сохранить схему"); save.clicked.connect(self.save)
        side=QWidget(); sl=QVBoxLayout(side); sl.addWidget(QLabel("Цепочка обхода")); sl.addWidget(self.list); sl.addWidget(load); sl.addWidget(undo); sl.addWidget(reverse); sl.addWidget(suggest); sl.addWidget(confirm); sl.addWidget(save); sl.addWidget(self.status); split=QSplitter(); split.addWidget(self.view); split.addWidget(side); split.setSizes([900,300]); self.setCentralWidget(split)
    def build_scene(self):
        self.scene.clear(); self.nodes={}; self.edges=[]; cx,cy=450,340; rx,ry=310,230; count=max(1,len(self.model.people))
        self.scene.addEllipse(cx-190,cy-115,380,230,QPen(QColor("#4a4d58"),2),QBrush(QColor("#202228")))
        for i,p in enumerate(self.model.people.values()):
            a=2*math.pi*i/count-math.pi/2; node=Node(p,cx+rx*math.cos(a),cy+ry*math.sin(a)); node.clicked.connect(self.select); self.scene.addItem(node); self.nodes[p.person_id]=node
    def load_exchange(self):
        default=str(self.exchange_path or (Path(__file__).parents[1]/"person_face/results/participants.json")); path,_=QFileDialog.getOpenFileName(self,"Файл участников person_face",default,"JSON (*.json)")
        if not path:return
        try: participants=read_participants(path)
        except Exception as exc: self.status.setText(f"Не удалось загрузить: {exc}"); return
        self.model=Model(participants); self.exchange_path=Path(path); self.build_scene(); self.refresh_list(); self.status.setText(f"Загружено реальных тегов: {len(participants)}")
    def select(self,p): self.status.setText(self.model.click(p)); self.redraw(); self.refresh_list()
    def undo(self): self.status.setText(self.model.undo()); self.redraw(); self.refresh_list()
    def reverse(self): self.model.direction="counterclockwise" if self.model.direction=="clockwise" else "clockwise"; self.status.setText(f"Направление: {self.model.direction}")
    def suggest(self): self.status.setText("Подсказка: подтверждайте соседей вручную; экранная сортировка не назначает номера")
    def confirm(self): ok,msg=self.model.confirm(); self.status.setText(msg); self.refresh_list()
    def save(self): self.model.save(Path(__file__).parent/"results/table_schema.json"); self.status.setText("Схема сохранена отдельно от партии")
    def refresh_list(self):
        self.list.clear(); self.list.addItems([f"{i+1}. {n}" for i,n in enumerate(self.model.chain)]); self.list.addItem(f"Не включены: {', '.join(n for n in self.model.people if n not in self.model.chain) or 'нет'}")
    def redraw(self):
        for item in self.edges: self.scene.removeItem(item)
        self.edges=[]
        for a,b in self.model.edges.items():
            line=self.scene.addLine(self.nodes[a].x(),self.nodes[a].y(),self.nodes[b].x(),self.nodes[b].y(),QPen(QColor("#742b38"),3)); self.edges.append(line)
        for n,node in self.nodes.items(): node.setBrush(QBrush(QColor("#742b38" if n in self.model.chain else "#282b34")))

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--participants-file"); args=parser.parse_args(); cfg=load_json(Path(__file__).with_name("config.json"),{"participants":["A","B","C","D"]}); exchange=Path(args.participants_file) if args.participants_file else Path(__file__).parents[1]/"person_face/results/participants.json"
    try: participants=read_participants(exchange) if exchange.exists() else cfg["participants"]
    except Exception as exc: print(f"Файл обмена не принят: {exc}; используется ручной список",file=sys.stderr); participants=cfg["participants"]
    app=QApplication(sys.argv); w=Window(participants,exchange); w.show(); sys.exit(app.exec())
if __name__=="__main__": main()
