"""Reusable step editor embedded in quick mode settings."""
import copy
import uuid
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QWidget,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QLineEdit)


class RouteEditor(QWidget):
    def __init__(self, panel, parent=None):
        super().__init__(parent or panel)
        self.panel = panel; self.tr = panel.tr
        self.route = copy.deepcopy(panel.route); self.guard = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        note = QLabel(self.tr('Переставляйте шаги, меняйте инструменты, добавляйте свои этапы.',
                             'Reorder steps, change tools and add your own stages.'))
        note.setWordWrap(True); layout.addWidget(note)
        self.steps = QListWidget(); self.steps.setDragDropMode(QAbstractItemView.InternalMove)
        self.steps.setMinimumHeight(160)
        layout.addWidget(self.steps, 1)
        layout.addWidget(QLabel(self.tr('Название шага', 'Step name')))
        self.name=QLineEdit();self.name.setMaxLength(160);layout.addWidget(self.name)
        self.name.editingFinished.connect(self.rename)
        layout.addWidget(QLabel(self.tr('Инструмент', 'Tool')))
        self.tool = QComboBox()
        for key, title in panel.catalog.items(): self.tool.addItem(title, key)
        layout.addWidget(self.tool)
        row = QHBoxLayout()
        for ru, en, fn in [('Выше', 'Up', lambda: self.move(-1)), ('Ниже', 'Down', lambda: self.move(1)),
                           ('Добавить', 'Add', self.add), ('Удалить', 'Remove', self.remove)]:
            button = QPushButton(self.tr(ru, en)); button.clicked.connect(fn); row.addWidget(button)
        layout.addLayout(row)
        defaults = QPushButton(self.tr('Стандартный маршрут Astra', 'Astra default workflow'))
        defaults.clicked.connect(self.defaults); layout.addWidget(defaults)
        self.steps.currentRowChanged.connect(self.selected)
        self.steps.model().rowsMoved.connect(self.reordered)
        self.tool.currentIndexChanged.connect(self.changed)
        self.refresh(panel.current)

    def load(self):
        self.route=copy.deepcopy(self.panel.route)
        self.refresh(self.panel.current)

    def refresh(self, index):
        self.guard = True; self.steps.clear()
        for i, step in enumerate(self.route):
            item = QListWidgetItem(f'{i+1}. {self.panel.title(step)} · {self.panel.catalog[step["tool"]]}')
            item.setData(Qt.UserRole, step['id']); self.steps.addItem(item)
        self.steps.setCurrentRow(max(0, min(index, len(self.route)-1))); self.guard = False
        self.selected(self.steps.currentRow())

    def selected(self, index):
        if self.guard or not 0 <= index < len(self.route): return
        self.guard = True
        self.tool.setCurrentIndex(self.tool.findData(self.route[index]['tool']))
        self.name.setText(self.panel.title(self.route[index]))
        self.guard = False

    def rename(self):
        index=self.steps.currentRow()
        if self.guard or index<0:return
        title=self.name.text().strip()
        if title==self.panel.title(self.route[index]):return
        if title:self.route[index]['title']=title
        else:self.route[index].pop('title',None)
        self.refresh(index)

    def changed(self):
        index = self.steps.currentRow()
        if self.guard or index < 0: return
        self.route[index]['tool'] = self.tool.currentData(); self.refresh(index)

    def move(self, delta):
        index = self.steps.currentRow(); target = index+delta
        if 0 <= target < len(self.route):
            self.route[index], self.route[target] = self.route[target], self.route[index]
            self.refresh(target)

    def reordered(self, *_):
        lookup = {step['id']: step for step in self.route}
        self.route = [lookup[self.steps.item(i).data(Qt.UserRole)] for i in range(self.steps.count())]
        self.refresh(self.steps.currentRow())

    def add(self):
        if len(self.route) >= 50: return
        index = self.steps.currentRow()+1
        self.route.insert(index, dict(id=uuid.uuid4().hex, stage='custom', tool=self.tool.currentData()))
        self.refresh(index)

    def remove(self):
        if len(self.route) <= 1: return
        index = self.steps.currentRow(); self.route.pop(index); self.refresh(index)

    def defaults(self):
        from .guided_mode import default_route
        self.route = default_route(); self.refresh(0)
