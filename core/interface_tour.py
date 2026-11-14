"""Spotlight tour of the main window. The tour never triggers application actions."""
from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QRect, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QFormLayout, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QMenuBar, QPushButton, QScrollArea, QVBoxLayout, QWidget)


STOPS = (
    ('Файл', 'File',
     'Откройте снимок или проект, сохраните работу или экспортируйте готовое изображение.',
     'Open a photo or project, save your work, or export the finished image.'),
    ('Правка', 'Edit',
     'Отмените последнее изменение или повторите отменённое действие.',
     'Undo the last change or redo an action you undid.'),
    ('Инструменты', 'Tools',
     'Выберите инструмент для обработки активного снимка.',
     'Choose a tool to edit the active photo.'),
    ('Плагины', 'Plugins',
     'Откройте модуль калибровки или сложения кадров, в том числе Live stacking.',
     'Open a module for calibration or stacking, including Live stacking.'),
    ('Настройки', 'Settings',
     'Измените параметры программы и выберите команды для панели быстрых кнопок.',
     'Change application preferences and choose which shortcuts appear on the toolbar.'),
    ('Справка', 'Help',
     'Запустите обучение заново или посмотрите сведения о программе.',
     'Restart learning mode or view information about the application.'),
    ('Вид', 'View',
     'Покажите или скройте историю и панель быстрых кнопок. Здесь же включите полноэкранный или пошаговый режим.',
     'Show or hide the history and quick toolbar. Use this menu to enter full screen or guided mode.'),
)

SETTINGS_STOPS = (
    ('Панель быстрых кнопок', 'Customize toolbar',
     'Отметьте команды, которые хотите видеть на панели.',
     'Check the commands you want to see on the toolbar.'),
    ('Настройки программы', 'Preferences',
     'Выберите язык и фон рабочей области. Настройте предрастяжение при запуске и открытие обычных фотоформатов, например JPG и PNG. При необходимости укажите пути к внешним программам. Нажмите «Сохранить», чтобы применить изменения.',
     'Choose the language and workspace background. Configure preview stretch on startup and opening common photo formats such as JPG and PNG. Set paths to external programs if needed. Select Save to apply your changes.'),
    ('Подкачка Windows', 'Windows page file',
     'Проверьте объём оперативной памяти и размер файла подкачки. При необходимости включите автоматическое управление, чтобы Windows могла увеличить файл подкачки при нехватке памяти.',
     'Check the amount of RAM and the page file size. Enable automatic management if needed so Windows can grow the page file when memory runs low.'),
    ('Поддержка NVIDIA GPU', 'NVIDIA GPU support',
     'Проверьте совместимость видеокарты NVIDIA и драйвера. Установите CUDA для инструментов, которые поддерживают ускорение на видеокарте, затем перезапустите Astra.',
     'Check whether your NVIDIA GPU and driver are compatible. Install CUDA to accelerate supported tools, then restart Astra.'),
    ('Обновления инструментов и ИИ-моделей', 'Tool and AI model updates',
     'Проверьте наличие обновлений внешних инструментов и ИИ-моделей. Запустите установку доступных обновлений и следите за её ходом в журнале этого окна.',
     'Check for updates to external tools and AI models. Install available updates and follow their progress in this dialog’s log.'),
)


class InterfaceTour(QWidget):
    def __init__(self, owner, *, surface=None, steps=None, tabs=None):
        self.surface = owner if surface is None else surface
        super().__init__(self.surface)
        self.tabs = tabs
        if tabs is not None:
            self.tab_indices = [
                0 if widget is tabs.tabBar() else
                next(index for index in range(tabs.count())
                     if tabs.widget(index) is widget or tabs.widget(index).isAncestorOf(widget))
                for widget, *_ in steps
            ]
        self.scroll = None if surface is None else surface.findChild(QScrollArea, 'stackTourScroll')
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.StrongFocus)
        self.owner = owner
        self.index = 0
        self.frame = None
        self.blurred = None
        tr = owner.trtext
        self.settings_rows = []
        if steps is None:
            self.build_main_stops(owner)
        else:
            self.stops = [(widget, tr(hint_ru, hint_en))
                          for widget, _, _, hint_ru, hint_en in steps]
            self.widget_titles = [tr(ru, en) for _, ru, en, _, _ in steps]
        self.card = QFrame(self)
        self.card.setAutoFillBackground(True)
        self.card_opacity = QGraphicsOpacityEffect(self.card)
        self.card_opacity.setOpacity(1)
        self.card.setGraphicsEffect(self.card_opacity)
        self.transition = QVariantAnimation(self)
        self.transition.setDuration(320)
        self.transition.setStartValue(0.0)
        self.transition.setEndValue(1.0)
        self.transition.setEasingCurve(QEasingCurve.InOutCubic)
        self.transition.valueChanged.connect(self.animate_step)
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(16, 12, 16, 12)
        self.title = QLabel()
        self.hint = QLabel()
        for label in (self.title, self.hint):
            label.setTextFormat(Qt.PlainText)
            label.setWordWrap(True)
            layout.addWidget(label)
        buttons = QHBoxLayout()
        layout.addLayout(buttons)
        self.exit = QPushButton(tr('Выйти', 'Exit'))
        self.back = QPushButton(tr('Назад', 'Back'))
        self.next = QPushButton()
        buttons.addWidget(self.exit)
        buttons.addStretch()
        buttons.addWidget(self.back)
        buttons.addWidget(self.next)
        self.exit.clicked.connect(self.close)
        self.back.clicked.connect(lambda: self.move_step(-1))
        self.next.clicked.connect(lambda: self.move_step(1))
        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.timeout.connect(self.capture)

    def build_main_stops(self, owner):
        self.bar = owner.findChild(QMenuBar, 'headerMenu') or owner.menuBar()
        tr = owner.trtext
        menu_hints = {tr(ru, en): tr(hint_ru, hint_en) for ru, en, hint_ru, hint_en in STOPS}
        settings_hints = {tr(ru, en): tr(hint_ru, hint_en)
                          for ru, en, hint_ru, hint_en in SETTINGS_STOPS}
        self.stops = []
        self.settings_action = None
        self.settings_rows = []
        for action in self.bar.actions():
            title = action.text().replace('&', '')
            if not action.isVisible() or title not in menu_hints:
                continue
            self.stops.append((action, menu_hints[title]))
            if title == tr('Настройки', 'Settings') and action.menu() is not None:
                self.settings_action = action
                for row in action.menu().actions():
                    row_title = row.text().replace('&', '')
                    if row.isVisible() and row_title in settings_hints:
                        self.settings_rows.append((row, settings_hints[row_title]))
                self.stops.extend(self.settings_rows)
        guided = getattr(owner, 'guided_header_button', None)
        if guided is not None and guided.isVisible():
            self.stops.append((guided, tr(
                'Включите пошаговый режим, чтобы обработать снимок по этапам.',
                'Enable guided mode to process a photo step by step.')))
        document = owner.mdi.activeSubWindow()
        history = owner.documents.get(document, {}).get('history_panel')
        header = getattr(owner, 'application_header', None)
        window_buttons = getattr(header, 'buttons', {})
        widgets = (
            (owner.toolbar, 'Панель быстрых кнопок', 'Quick toolbar',
             'Запускайте часто используемые команды с панели. Выберите кнопки в меню «Настройки».',
             'Run frequently used commands from the toolbar. Choose the buttons in Settings.'),
            (owner.mdi, 'Рабочая область', 'Workspace',
             'Щёлкните по окну снимка, чтобы сделать его активным. Откройте «Вид → История», чтобы посмотреть его изменения.',
             'Click a photo window to make it active. Open View → History to see its edits.'),
            (history, 'История снимка', 'Photo history',
             'Выберите запись, чтобы посмотреть снимок на соответствующем этапе обработки.',
             'Select an entry to view the photo at that stage of editing.'),
            (owner.tools_dock, 'Боковая панель инструментов', 'Tools sidebar',
             'Проверьте, какой снимок активен, и настройте параметры выбранного инструмента.',
             'Check which photo is active, then adjust the selected tool’s settings.'),
            (owner.resource_monitor, 'Монитор ресурсов', 'Resource monitor',
             'Следите за загрузкой системы во время обработки.',
             'Monitor system load during processing.'),
            (owner.log_button, 'Журнал', 'Log',
             'Откройте журнал, чтобы проверить ход обработки и посмотреть подробности ошибок.',
             'Open application messages to check progress and see error details.'),
            (window_buttons.get('minimize'), 'Свернуть окно', 'Minimize window',
             'Сверните Astra на панель задач.', 'Minimize Astra to the taskbar.'),
            (window_buttons.get('maximize'), 'Размер окна', 'Window size',
             'Разверните окно или верните ему прежний размер.', 'Maximize or restore the window.'),
            (window_buttons.get('close'), 'Закрыть окно', 'Close window',
             'Закройте главное окно Astra.', 'Close the main Astra window.'),
        )
        self.widget_titles = {}
        for widget, title_ru, title_en, hint_ru, hint_en in widgets:
            if widget is not None and widget.isVisible() and widget.window() is owner:
                self.widget_titles[widget] = tr(title_ru, title_en)
                self.stops.append((widget, tr(hint_ru, hint_en)))
        if owner.tools_dock in self.widget_titles:
            position = next(i for i, (target, _) in enumerate(self.stops)
                            if target is owner.tools_dock)
            self.stops.insert(position + 1, (owner.tools_dock, tr(
                'Чтобы инструмент открывался при каждом запуске Astra, откройте его, щёлкните правой кнопкой по его кнопке на боковой панели и выберите «Закрепить при запуске».',
                'To reopen a tool when Astra starts, open it, right-click its button in the sidebar, and select “Pin on startup”.')))

    def start(self):
        if not self.stops:
            self.close()
            return
        self.surface.installEventFilter(self)
        self.capture()

    def capture(self, previous_target=None):
        self.transition.stop()
        self.hide()
        self.setGeometry(self.surface.rect())
        action, _ = self.stops[self.index]
        if self.tabs is not None:
            tab_index = self.tab_indices[self.index]
            self.tabs.setCurrentIndex(tab_index)
        if self.scroll is not None:
            self.scroll.ensureWidgetVisible(action)
        self.frame = self.surface.grab()
        if any(action is row for row, _ in self.settings_rows):
            menu = self.settings_action.menu()
            menu.ensurePolished()
            menu.adjustSize()
            snapshot = menu.grab()
            anchor = self.menu_rect(self.settings_action)
            origin = QPoint(max(0, min(anchor.left(), self.width() - menu.width())),
                            anchor.bottom() + 1)
            painter = QPainter(self.frame)
            painter.drawPixmap(origin, snapshot)
            painter.end()
            self.target = menu.actionGeometry(action).translated(origin)
        elif isinstance(action, QWidget):
            self.target = action.rect().translated(action.mapTo(self.surface, QPoint())).intersected(self.rect())
            if self.tabs is not None and (not action.isVisible() or self.target.isEmpty()):
                bar = self.tabs.tabBar()
                self.target = bar.tabRect(tab_index).translated(bar.mapTo(self.surface, QPoint()))
            elif self.tabs is not None:
                form = self.tabs.widget(tab_index).layout()
                if isinstance(form, QFormLayout):
                    label = form.labelForField(action)
                    if label is not None and label.isVisible():
                        label_rect = label.rect().translated(label.mapTo(self.surface, QPoint()))
                        self.target = self.target.united(label_rect).intersected(self.rect())
        else:
            self.target = self.menu_rect(action)
        small = self.frame.scaled(max(1, self.width() // 16), max(1, self.height() // 16),
                                  Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self.blurred = small.scaled(self.frame.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self.blurred.setDevicePixelRatio(self.frame.devicePixelRatio())
        self.refresh()
        self.transition_origin = self.target if previous_target is None else previous_target
        self.animate_step(1.0 if previous_target is None else 0.0)
        self.show()
        self.raise_()
        self.next.setFocus()
        if previous_target is not None:
            self.transition.start()

    def animate_step(self, progress):
        origin = self.transition_origin
        start = origin.topLeft()
        end = origin.bottomRight()
        self.spotlight = QRect(start + (self.target.topLeft() - start) * progress,
                               end + (self.target.bottomRight() - end) * progress)
        self.card_opacity.setOpacity(min(1.0, 0.15 + progress))
        self.update()

    def menu_rect(self, action):
        return self.bar.actionGeometry(action).translated(self.bar.mapTo(self.owner, QPoint()))

    def refresh(self):
        action, hint = self.stops[self.index]
        title = self.widget_titles[self.index] if self.surface is not self.owner else self.widget_titles.get(action)
        if title is None:
            title = action.text().replace('&', '')
        self.title.setText(f'{self.index + 1}/{len(self.stops)} · {title}')
        self.hint.setText(hint)
        self.back.setEnabled(self.index > 0)
        self.next.setText(self.owner.trtext('Готово', 'Done') if self.index == len(self.stops) - 1
                          else self.owner.trtext('Далее', 'Next'))
        self.card.setFixedWidth(min(440, max(1, self.width() - 24)))
        self.card.adjustSize()
        margin = 12
        max_x = max(margin, self.width() - self.card.width() - margin)
        max_y = max(margin, self.height() - self.card.height() - margin)
        x = min(max_x, max(margin, self.target.left()))
        y = min(max_y, max(margin, self.target.top()))
        if self.target.bottom() + margin <= max_y:
            y = self.target.bottom() + margin
        elif self.target.top() - self.card.height() - margin >= margin:
            y = self.target.top() - self.card.height() - margin
        elif self.target.left() - self.card.width() - margin >= margin:
            x = self.target.left() - self.card.width() - margin
        elif self.target.right() + margin <= max_x:
            x = self.target.right() + margin
        else:
            x, y = max_x, max_y
        self.card.move(x, y)
        self.update()

    def move_step(self, delta):
        index = self.index + delta
        if index >= len(self.stops):
            self.close()
        elif index >= 0:
            self.index = index
            self.capture(self.spotlight)

    def paintEvent(self, event):
        if self.frame is None:
            return
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.blurred)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 135))
        painter.save()
        painter.setClipRect(self.spotlight)
        painter.drawPixmap(0, 0, self.frame)
        painter.restore()
        painter.setPen(QPen(QColor('#74c8ff'), 2))
        painter.drawRect(self.spotlight.adjusted(-1, 1, 1, -1))

    def event(self, event):
        if event.type() == QEvent.ShortcutOverride:
            event.accept()
            return True
        return super().event(event)

    def focusNextPrevChild(self, forward):
        buttons = [button for button in (self.exit, self.back, self.next) if button.isEnabled()]
        focused = self.focusWidget()
        index = buttons.index(focused) if focused in buttons else -1
        buttons[(index + (1 if forward else -1)) % len(buttons)].setFocus()
        return True

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            button = self.focusWidget()
            if isinstance(button, QPushButton):
                button.click()
        event.accept()

    def mousePressEvent(self, event):
        event.accept()

    def wheelEvent(self, event):
        event.accept()

    def eventFilter(self, watched, event):
        if watched is self.surface and event.type() == QEvent.Resize:
            self.resize_timer.start(0)
        return False

    def closeEvent(self, event):
        self.transition.stop()
        self.resize_timer.stop()
        self.surface.removeEventFilter(self)
        super().closeEvent(event)
