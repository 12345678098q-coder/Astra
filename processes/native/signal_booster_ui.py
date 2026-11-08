"""Visual placeholder. Signal Booster processing is not shipped."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QFormLayout,QGridLayout,QLabel,
    QComboBox,QSpinBox,QCheckBox,QPushButton,QHBoxLayout,QGraphicsOpacityEffect)

class SignalBoosterPanel(QWidget):
    def __init__(self,window):
        super().__init__()
        grid=QGridLayout(self);grid.setContentsMargins(0,0,0,0)
        shell=QWidget();layout=QVBoxLayout(shell);form=QFormLayout();layout.addLayout(form)
        model=QComboBox();model.addItem('Signal Booster');form.addRow(window.trtext('Модель','Model'),model)
        boost=QSpinBox();boost.setRange(0,100);boost.setValue(30);boost.setSuffix('%');form.addRow(window.trtext('Буст','Boost'),boost)
        layout.addWidget(QCheckBox(window.trtext('Данные кадра линейные','Image data are linear')))
        layout.addStretch();buttons=QHBoxLayout();layout.addLayout(buttons)
        for ru,en in [('Предпросмотр','Preview'),('Отмена','Cancel'),('Применить','Apply')]:buttons.addWidget(QPushButton(window.trtext(ru,en)))
        shell.setEnabled(False);fade=QGraphicsOpacityEffect(shell);fade.setOpacity(.3);shell.setGraphicsEffect(fade)
        grid.addWidget(shell,0,0)
        label=QLabel(window.trtext('В разработке','In development'));label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet('font-size:22px;font-weight:600;background:transparent;')
        grid.addWidget(label,0,0);label.raise_()
