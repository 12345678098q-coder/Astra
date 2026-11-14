"""Channel toolbar context menu, including buttons re-added by customization."""
from PySide6.QtCore import QObject, QEvent, QTimer, Qt
from PySide6.QtWidgets import QMenu


class ChannelTools(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        owner.toolbar.installEventFilter(self)
        self.refresh()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.ActionAdded:
            QTimer.singleShot(0, self, self.refresh)
        return False

    def refresh(self):
        owner = self.owner
        rgb, lum = owner.actions['split_rgb'], owner.actions['luminance']
        actions = owner.toolbar.actions()
        if rgb in actions and lum in actions and actions.index(lum) != actions.index(rgb) + 1:
            owner.toolbar.removeAction(lum)
            actions = owner.toolbar.actions()
            index = actions.index(rgb) + 1
            owner.toolbar.insertAction(actions[index] if index < len(actions) else None, lum)
        button = owner.toolbar.widgetForAction(rgb)
        if button is not None and not button.property('channelMenuInstalled'):
            button.setProperty('channelMenuInstalled', True)
            button.setContextMenuPolicy(Qt.CustomContextMenu)
            button.customContextMenuRequested.connect(lambda pos, b=button: self.menu(b, pos))

    def menu(self, button, pos):
        owner = self.owner
        source = owner.mdi.activeSubWindow()
        record = owner.documents.get(source)
        menu = QMenu(button)
        enabled = record is not None and record['data'].ndim == 3 and record['data'].shape[-1] == 3
        for channel in ('RGB', 'R', 'G', 'B'):
            action = menu.addAction(owner.trtext('Извлечь ', 'Extract ') + channel)
            action.setEnabled(enabled)
            action.triggered.connect(lambda checked=False, c=channel: owner.split_rgb(source, None if c == 'RGB' else c))
        menu.exec(button.mapToGlobal(pos))
