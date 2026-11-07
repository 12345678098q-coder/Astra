"""Experimental linear-signal detail booster with preview and ordinary undo."""
from pathlib import Path
import numpy as np
from PySide6.QtWidgets import QComboBox, QMessageBox
from .ui import BasePanel
from .jobs import launch

MODELS = Path(__file__).resolve().parents[2] / 'experiments/signal_booster/models'
RGB_MODEL = MODELS / 'signal_booster_multiscale.npz'
NOISE_COMPAT_MODEL = MODELS / 'signal_booster_noise_compat.npz'


class SignalBoosterPanel(BasePanel):
    def __init__(self, window):
        super().__init__(window, 'signal_booster')
        self.generation = 0
        self.version = QComboBox()
        if RGB_MODEL.is_file():
            self.version.addItem('Multiscale RGB · experimental', 'multiscale')
        if NOISE_COMPAT_MODEL.is_file():
            self.version.addItem('Multiscale RGB · 4M structures test', 'noise_compat')
        self.version.addItem('Pilot', 'pilot')
        selected = self.version.findData(self.saved.get('model'))
        if selected >= 0:
            self.version.setCurrentIndex(selected)
        self.row(self.tr('Модель', 'Model'), self.version)
        self.version.currentIndexChanged.connect(self.save)
        self.number('boost', 'Буст, %', 'Boost, %', 30, 0, 100, True)
        self.check('linear', 'Данные кадра линейные', 'Image data are linear', False)
        self.note('Целевая выдержка: 30% → 1,3×, 100% → 2×. У пилота шкала регулирует силу обработки.',
                  'Target integration: 30% → 1.3×, 100% → 2×. For Pilot, the scale controls processing strength.')
        self.note('Тестовый модуль.', 'Test module.')
        self.button('Предпросмотр', 'Preview', lambda: self.execute(False))
        self.button('Отмена', 'Cancel', self.cancel)
        self.button('Применить', 'Apply', lambda: self.execute(True))

    def values(self):
        return dict(super().values(), model=self.version.currentData())

    def reset(self):
        super().reset()
        self.version.setCurrentIndex(0)
        self.fields['boost'].setValue(30)

    def cancel(self):
        self.generation += 1
        super().cancel()

    def execute(self, commit):
        source, record = self.target()
        if record is None:
            return
        if not self.fields['linear'].isChecked():
            QMessageBox.information(self, 'Signal Booster', self.tr(
                'Инструмент обучен на линейных данных. Подтвердите тип данных кадра.',
                'The model was trained on linear data. Confirm the image data type.'))
            return
        data = record['data']
        strength = self.fields['boost'].value() / 100
        model_key = self.version.currentData()
        multiscale = model_key in ('multiscale','noise_compat')
        checkpoint = NOISE_COMPAT_MODEL if model_key=='noise_compat' else RGB_MODEL
        label = f'Signal Booster {self.version.currentText()} {strength:.0%}'
        mask = record.get('mask') if record.get('mask_enabled') else None
        if mask is not None:
            mask = np.array(mask, copy=True)
        self.generation += 1
        generation = self.generation

        def work(job):
            import torch
            from experiments.signal_booster.model import load, apply
            torch.set_num_threads(4)
            job.note.emit(label)
            if multiscale:
                from experiments.signal_booster.gpu_backend import enhance_cuda
                result=enhance_cuda(data,checkpoint,1+strength,
                    cancel=job.isInterruptionRequested,note=job.note.emit)
                if result is None:
                    from experiments.signal_booster.multiscale import enhance, load_checkpoint
                    model, _ = load_checkpoint(checkpoint)
                    result = enhance(data, model, exposure_ratio=1+strength, cancel=job.isInterruptionRequested)
            else:
                model, _ = load(MODELS / 'signal_booster_pilot.npz')
                result = apply(data, model, strength, job.isInterruptionRequested)
            if mask is not None:
                opacity = mask[..., None] if data.ndim == 3 else mask
                result = data + (result - data) * opacity
            return result

        def done(result):
            if generation != self.generation or source not in self.window.documents:
                return
            if self.window.documents[source]['data'] is not data:
                return
            if commit:
                self.clear_preview()
                self.window.apply_image_result(source, result, label)
            else:
                self.preview_result(source, data, result)

        launch(self.window, label, work, done, data.nbytes * 4 + (512 if multiscale else 256) * 1024**2)
