"""Edge snapping and companion selection for the image workspace."""
from PySide6.QtCore import Qt, QRect, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import QFrame, QVBoxLayout, QPushButton, QLabel, QRubberBand, QScrollArea, QWidget


class WindowSnap:
    def __init__(self, workspace):
        self.workspace = workspace
        self.preview = QRubberBand(QRubberBand.Rectangle, workspace.viewport())
        self.preview.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.choice = None
        self.pending = None
        self.slots = {}
        self.animations = {}
        self.edge_hints=[]
        for right in (False,True):
            hint=QFrame(workspace.viewport())
            hint.setAttribute(Qt.WA_TransparentForMouseEvents)
            start,end=(1,0) if right else (0,1)
            hint.setStyleSheet(f"""
                background:qlineargradient(x1:{start},y1:0,x2:{end},y2:0,
                    stop:0 rgba(120,185,225,115),
                    stop:0.35 rgba(120,185,225,45),
                    stop:1 rgba(120,185,225,0));
                border:0;
            """)
            hint.hide()
            self.edge_hints.append(hint)
        self.escape = QShortcut(QKeySequence(Qt.Key_Escape), workspace)
        self.escape.setContext(Qt.WidgetWithChildrenShortcut)
        self.escape.activated.connect(self.cancel)
        self.escape.setEnabled(False)

    def rectangle(self, slot):
        x, y, width, height = slot
        area = self.workspace.viewport().rect()
        left = round(area.width() * x)
        top = round(area.height() * y)
        right = round(area.width() * (x + width))
        bottom = round(area.height() * (y + height))
        return QRect(left, top, right - left, bottom - top)

    def cancel(self):
        for hint in self.edge_hints:hint.hide()
        self.escape.setEnabled(False)
        self.pending = None
        self.preview.hide()
        if self.choice is not None:
            self.choice.hide()
            self.choice.deleteLater()
            self.choice = None

    def begin(self, window):
        self.cancel()
        animation=self.animations.pop(window,None)
        if animation is not None:animation.stop();animation.deleteLater()
        self.slots.pop(window, None)
        if not window.isMinimized():self.show_edge_hints()

    def show_edge_hints(self):
        area=self.workspace.viewport().rect()
        width=max(1,round(area.width()*(.08/3)))
        for hint,x in zip(self.edge_hints,(0,area.width()-width)):
            hint.setGeometry(x,0,width,area.height())
            hint.show()
            hint.raise_()

    def update(self, position):
        if any(hint.isVisible() for hint in self.edge_hints):
            self.show_edge_hints()
        area = self.workspace.viewport().rect()
        edge = max(1,round(min(area.width(),area.height())*.006))
        left = position.x() <= edge
        right = position.x() >= area.width() - edge
        top = position.y() <= edge
        bottom = position.y() >= area.height() - edge
        corner_width = area.width() * .18
        corner_height = area.height() * .22
        near_left = position.x() <= corner_width
        near_right = position.x() >= area.width() - corner_width
        near_top = position.y() <= corner_height
        near_bottom = position.y() >= area.height() - corner_height
        slot = None
        if ((left or right) and (near_top or near_bottom)
                or (top or bottom) and (near_left or near_right)):
            slot = (.5 if near_right else 0, .5 if near_bottom else 0, .5, .5)
        elif left or right:
            slot = (.5 if right else 0, 0, .5, 1)
        self.pending = slot
        self.escape.setEnabled(slot is not None)
        if slot is None:
            self.preview.hide()
        else:
            self.preview.setGeometry(self.rectangle(slot))
            self.preview.show()
            self.preview.raise_()

    def place(self, window, slot):
        previous=self.animations.pop(window,None)
        if previous is not None:previous.stop()
        window.showNormal()
        self.slots[window] = slot
        animation=QPropertyAnimation(window,b'geometry',self.workspace)
        animation.setDuration(180)
        animation.setStartValue(window.geometry())
        animation.setEndValue(self.rectangle(slot))
        animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animations[window]=animation
        def finished():
            if self.animations.get(window) is animation:self.animations.pop(window,None)
            animation.deleteLater()
        animation.finished.connect(finished)
        animation.start()

    def toggle_maximized(self,window):
        previous=self.animations.pop(window,None)
        if previous is not None:previous.stop();previous.deleteLater()
        start=window.geometry()
        if window.isMaximized():
            target=getattr(window,'_snap_restore_geometry',window.normalGeometry())
            if not target.isValid():
                target=self.workspace.viewport().rect().adjusted(
                    round(self.workspace.width()*.1),round(self.workspace.height()*.1),
                    -round(self.workspace.width()*.1),-round(self.workspace.height()*.1))
            window.showNormal()
            window.setGeometry(start)
            maximize=False
        else:
            window._snap_restore_geometry=window.geometry()
            target=self.workspace.viewport().rect()
            maximize=True
        self.slots.pop(window,None)
        animation=QPropertyAnimation(window,b'geometry',self.workspace)
        animation.setDuration(200)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.setStartValue(start)
        animation.setEndValue(target)
        self.animations[window]=animation
        def finish():
            self.animations.pop(window,None)
            if maximize:
                restore=window._snap_restore_geometry
                window.setGeometry(restore)
                window.showMaximized()
            animation.deleteLater()
        animation.finished.connect(finish)
        animation.start()

    def finish(self, window):
        slot = self.pending
        self.cancel()
        if slot is None:
            return
        self.place(window, slot)
        x, y, width, height = slot
        if width == height == 1:
            return
        if width == height == .5:
            free = [(sx, sy, .5, .5) for sy in (0, .5) for sx in (0, .5)
                    if (sx, sy) != (x, y)]
        elif width == .5:
            free = [(1 - x - width, 0, .5, 1)]
        else:
            free = [(0, 1 - y - height, 1, .5)]
        self.offer(free, [window])

    def offer(self, free, placed):
        candidates = [window for window in self.workspace.subWindowList()
                      if window not in placed and not window.isHidden()]
        if not free or not candidates:
            return
        panel = QFrame(self.workspace.viewport())
        panel.setObjectName('snapAssist')
        panel.setStyleSheet('QFrame#snapAssist {border:2px solid #78a9c7;}')
        layout = QVBoxLayout(panel)
        owner = self.workspace.owner
        translate = owner.trtext if owner is not None else lambda ru, en: ru
        title = QLabel(translate('Выберите окно для этой области', 'Choose a window for this area'))
        title.setWordWrap(True)
        layout.addWidget(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        choices = QVBoxLayout(content)
        for window in candidates:
            button = QPushButton(window.windowTitle())
            button.clicked.connect(lambda checked=False, target=window: self.choose(target, free, placed))
            choices.addWidget(button)
        choices.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        close = QPushButton(translate('Пропустить', 'Skip'))
        close.clicked.connect(self.cancel)
        layout.addWidget(close)
        self.choice = panel
        self.escape.setEnabled(True)
        self.choice_slot = free[0]
        panel.setGeometry(self.rectangle(free[0]).adjusted(8, 8, -8, -8))
        panel.show()
        panel.raise_()

    def choose(self, window, free, placed):
        self.cancel()
        self.place(window, free[0])
        self.offer(free[1:], placed + [window])

    def resize(self):
        if any(hint.isVisible() for hint in self.edge_hints):self.show_edge_hints()
        for window, slot in list(self.slots.items()):
            if window not in self.workspace.subWindowList():
                self.slots.pop(window, None)
            elif not window.isMinimized():
                animation=self.animations.pop(window,None)
                if animation is not None:animation.stop();animation.deleteLater()
                window.setGeometry(self.rectangle(slot))
        if self.choice is not None:
            self.choice.setGeometry(self.rectangle(self.choice_slot).adjusted(8, 8, -8, -8))
