"""Scenario picker for learning mode."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListWidget, QTabWidget, QVBoxLayout, QPushButton, QMessageBox
from core.learning_scenarios import SCENARIOS, LearningRunner
from core.interface_tour import InterfaceTour
from core.stacking_tour import show_stacking_tour
from core.stacking_practice import start_stacking_practice


def offer_first_run_learning(parent):
    if parent.settings.value('learning/first_run_offer_seen', False, type=bool):
        return
    tr = parent.trtext
    dialog = QDialog(parent)
    dialog.setObjectName('firstRunLearning')
    dialog.setWindowTitle(tr('Добро пожаловать в Astra', 'Welcome to Astra'))
    dialog.setModal(True)
    dialog.setAttribute(Qt.WA_DeleteOnClose)
    dialog.resize(470, 190)
    layout = QVBoxLayout(dialog)
    heading = QLabel(tr('Пройти обучение?', 'Take a tour?'))
    heading.setObjectName('hero')
    layout.addWidget(heading)
    description = QLabel(tr(
        'Познакомьтесь с интерфейсом Astra и узнайте, как начать работу со снимками. '
        'Вы также можете открыть обучение позже через «Справка → Режим обучения».',
        'Get to know the Astra interface and learn how to start working with photos. '
        'You can also open the tours later from Help → Learning mode.'))
    description.setWordWrap(True)
    layout.addWidget(description, 1)
    buttons = QDialogButtonBox()
    start = buttons.addButton(tr('Пройти обучение', 'Take a tour'), QDialogButtonBox.AcceptRole)
    later = buttons.addButton(tr('Не сейчас', 'Not now'), QDialogButtonBox.RejectRole)
    start.setProperty('astraPrimaryAction', True)
    start.setDefault(True)
    later.clicked.connect(dialog.reject)
    start.clicked.connect(dialog.accept)
    dialog.accepted.connect(lambda: show_learning_mode(parent))
    layout.addWidget(buttons)
    parent.settings.setValue('learning/first_run_offer_seen', True)
    parent.settings.sync()
    dialog.open()


def show_learning_mode(parent):
    dialog = getattr(parent, '_learning_mode_dialog', None)
    if dialog is None:
        tr = parent.trtext
        dialog = QDialog(parent)
        dialog.setWindowTitle(tr('Режим обучения', 'Learning mode'))
        dialog.resize(560, 400)
        layout = QVBoxLayout(dialog)
        tabs = QTabWidget(dialog)
        tabs.setObjectName('learningTabs')
        layout.addWidget(tabs)
        scenarios = QListWidget(dialog)
        scenarios.setObjectName('learningScenarios')
        scenarios.setStyleSheet('QListWidget#learningScenarios { outline: 0; }')
        scenarios.setAccessibleName(tr('Сценарии обучения', 'Learning scenarios'))
        tabs.addTab(scenarios, tr('Обучение', 'Learning'))
        practice = QListWidget(dialog)
        practice.setObjectName('practiceScenarios')
        practice.setAccessibleName(tr('Сценарии', 'Scenarios'))
        tabs.addTab(practice, tr('Сценарии', 'Scenarios'))
        start = QPushButton(tr('Начать обучение', 'Start learning'))
        start.setEnabled(False)
        layout.addWidget(start)
        def update_start():
            start.setEnabled(tabs.currentWidget().currentRow() >= 0)

        scenarios.currentRowChanged.connect(update_start)
        practice.currentRowChanged.connect(update_start)
        tabs.currentChanged.connect(update_start)

        def launch():
            row = tabs.currentWidget().currentRow()
            if row < 0:
                return
            if tabs.currentIndex() == 0 and row == 0:
                dialog.close()
                InterfaceTour(parent).start()
                return
            if tabs.currentIndex() == 0 and row in (1, 2):
                dialog.close()
                if row == 2:
                    show_stacking_tour(parent)
                else:
                    parent.module.show()
                    parent.stacking_preferences(learning=True)
                return
            if row == 0:
                try:
                    if start_stacking_practice(parent):
                        dialog.close()
                except ValueError as error:
                    QMessageBox.warning(dialog, tr('Режим обучения', 'Learning mode'), str(error))
                return
            runner = getattr(parent, '_learning_runner', None)
            if runner is None:
                runner = LearningRunner(parent)
                parent._learning_runner = runner
            try:
                if runner.start(dialog.available_scenarios[row - 1]):
                    dialog.close()
            except ValueError as error:
                QMessageBox.warning(dialog, tr('Режим обучения', 'Learning mode'), str(error))

        start.clicked.connect(launch)
        scenarios.itemDoubleClicked.connect(launch)
        practice.itemDoubleClicked.connect(launch)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText(tr('Закрыть', 'Close'))
        buttons.rejected.connect(dialog.close)
        layout.addWidget(buttons)
        parent._learning_mode_dialog = dialog
    dialog.available_scenarios = tuple(SCENARIOS)
    scenarios = dialog.findChild(QListWidget, 'learningScenarios')
    scenarios.clear()
    scenarios.addItem(parent.trtext('Знакомство с программой', 'Getting to know the app'))
    scenarios.addItem(parent.trtext('Сложение – настройки', 'Stacking – settings'))
    scenarios.addItem(parent.trtext('Сложение – интерфейс и рабочий процесс', 'Stacking – interface and workflow'))
    practice = dialog.findChild(QListWidget, 'practiceScenarios')
    practice.clear()
    practice.addItem(parent.trtext('Первое сложение · Полумесяц', 'First stack · Crescent Nebula'))
    practice.addItems([scenario.title for scenario in dialog.available_scenarios])
    if practice.count():
        practice.setCurrentRow(0)
    dialog.findChild(QTabWidget, 'learningTabs').setCurrentIndex(0)
    scenarios.setCurrentRow(0)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
