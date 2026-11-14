"""Data and runner for authored, photo-specific learning scenarios.

Register Scenario objects in SCENARIOS. Image paths must point to bundled
training copies; the runner never saves or overwrites the source image.
Steps advance explicitly: opening a tool does not mean processing succeeded.
"""
from core.i18n import localize
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDockWidget, QWidget, QVBoxLayout, QLabel,
                              QListWidget, QPushButton, QMessageBox)
from core.resources import heavy_job_running


@dataclass(frozen=True)
class LearningStep:
    id: str
    title: str
    tool: str
    image_hint: str
    tool_hint: str


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    image_path: Path
    steps: tuple[LearningStep, ...]

    def validate(self, tools):
        if not self.image_path.is_file():
            raise ValueError(localize('Фотография не найдена: {0}', 'Photo not found: {0}').format(self.image_path))
        if not self.steps:
            raise ValueError(localize('В сценарии нет шагов'))
        ids = [step.id for step in self.steps]
        if len(set(ids)) != len(ids):
            raise ValueError(localize('Идентификаторы шагов должны быть уникальны'))
        for step in self.steps:
            if step.tool not in tools:
                raise ValueError(localize('Неизвестный инструмент: {0}', 'Unknown tool: {0}').format(step.tool))


SCENARIOS: list[Scenario] = []


class LearningRunner(QDockWidget):
    def __init__(self, owner):
        super().__init__(owner.trtext('Режим обучения', 'Learning mode'), owner)
        self.owner = owner
        self.scenario = None
        self.document = None
        self.current = 0
        self.setObjectName('learningRunner')
        body = QWidget(self)
        layout = QVBoxLayout(body)
        self.heading = QLabel()
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)
        self.steps = QListWidget()
        self.steps.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(self.steps)
        self.image_hint = QLabel()
        self.tool_hint = QLabel()
        for label in (self.image_hint, self.tool_hint):
            label.setWordWrap(True)
            label.setTextFormat(Qt.PlainText)
            layout.addWidget(label)
        self.open_button = QPushButton(owner.trtext('Открыть инструмент', 'Open tool'))
        self.open_button.clicked.connect(self.open_tool)
        layout.addWidget(self.open_button)
        self.next_button = QPushButton(owner.trtext('Шаг выполнен – дальше', 'Step complete – next'))
        self.next_button.clicked.connect(self.advance)
        layout.addWidget(self.next_button)
        close = QPushButton(owner.trtext('Завершить обучение', 'End learning'))
        close.clicked.connect(self.close)
        layout.addWidget(close)
        self.setWidget(body)
        owner.addDockWidget(Qt.LeftDockWidgetArea, self)
        self.hide()

    def start(self, scenario):
        if heavy_job_running(self.owner):
            return False
        scenario.validate(self.owner.tool_entries())
        if not self.owner.open_image_path(scenario.image_path):
            return False
        self.document = self.owner.mdi.activeSubWindow()
        # A training document must never use the bundled photo as its save target.
        record = self.owner.documents[self.document]
        record['file_path'] = None
        record['saved_entry'] = None
        self.scenario = scenario
        self.current = 0
        self.steps.clear()
        self.steps.addItems([step.title for step in scenario.steps])
        self.refresh()
        self.show()
        return True

    def activate_photo(self):
        if heavy_job_running(self.owner):
            return False
        if self.document not in self.owner.documents:
            QMessageBox.information(self, 'Astra', self.owner.trtext(
                'Учебная фотография закрыта. Запустите сценарий заново.',
                'The training photo is closed. Restart the scenario.'))
            return False
        self.owner.mdi.setActiveSubWindow(self.document)
        return True

    def refresh(self):
        step = self.scenario.steps[self.current]
        self.heading.setText(f'{self.scenario.title} · {self.current + 1}/{len(self.scenario.steps)}')
        self.steps.setCurrentRow(self.current)
        self.image_hint.setText(self.owner.trtext('На фотографии: ', 'In the photo: ') + step.image_hint)
        self.tool_hint.setText(self.owner.trtext('В инструменте: ', 'In the tool: ') + step.tool_hint)

    def open_tool(self):
        if self.activate_photo():
            self.owner.open_tool(self.scenario.steps[self.current].tool)

    def advance(self):
        if not self.activate_photo():
            return
        if self.current + 1 == len(self.scenario.steps):
            self.close()
            return
        self.current += 1
        self.refresh()

    def closeEvent(self, event):
        self.scenario = None
        self.document = None
        super().closeEvent(event)
