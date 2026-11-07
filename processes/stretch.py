from core.responsive import set_em_size
from PySide6.QtCore import Qt
from PySide6.QtWidgets import *
import numpy as np

def automatic_strength(finite,lo,hi,target=.2):
    """Fit the asinh preview curve to the median without changing pixel data."""
    if hi<=lo:return 0
    level=float(np.clip((np.median(finite)-lo)/(hi-lo),0,1))
    if level<=0 or level>=target:return 0
    low,high=0.,1000.
    for _ in range(32):
        mid=(low+high)/2
        if np.arcsinh(mid*level)/np.arcsinh(mid)<target:low=mid
        else:high=mid
    return int(round(high))
FILTER='Астроизображения (*.fit *.fits *.fts *.tif *.tiff *.xisf);;RAW фотоаппаратов и другие файлы (*.*)'

class StretchProcessMixin:
    def toggle_stretch(self):
        self.stretch.setChecked(not self.stretch.isChecked()); self.actions['stretch'].setChecked(self.stretch.isChecked())

    def stretch_preferences(self):
        dialog=QDialog(self); dialog.setWindowTitle(self.trtext('Предрастяжение','Preview stretch')); set_em_size(dialog,'setMinimumWidth',23.75)
        layout=QVBoxLayout(dialog)
        enabled=QCheckBox(self.trtext('Включить предрастяжение','Enable preview stretch')); enabled.setChecked(self.stretch.isChecked()); layout.addWidget(enabled)
        layout.addWidget(QLabel(self.trtext('Сила растяжения (0 - линейное, больше - сильнее):','Stretch strength (0 = linear, higher = stronger):')))
        row=QHBoxLayout(); slider=QSlider(Qt.Horizontal); slider.setRange(0,1000); value=QSpinBox(); value.setRange(0,1000); value.setValue(self.stretch_strength); slider.setValue(self.stretch_strength)
        slider.valueChanged.connect(value.setValue); value.valueChanged.connect(slider.setValue); row.addWidget(slider,1); row.addWidget(value); layout.addLayout(row)
        hint=QLabel(self.trtext('Изменения сразу видны на изображении и в предпросмотре кадра.','Changes appear immediately in the image and frame preview.')); hint.setWordWrap(True); layout.addWidget(hint)
        original=(self.stretch.isChecked(),self.stretch_strength)
        def update():
            self.stretch_strength=value.value(); self.stretch.setChecked(enabled.isChecked()); self.actions['stretch'].setChecked(enabled.isChecked()); self.render(); self.render_frame_preview()
        enabled.toggled.connect(update); value.valueChanged.connect(update)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        if dialog.exec()==QDialog.Accepted:
            self.settings.setValue('stretch_strength',self.stretch_strength)
        else:
            main,self.stretch_strength=original; self.stretch.setChecked(main); self.actions['stretch'].setChecked(main); self.render(); self.render_frame_preview()

