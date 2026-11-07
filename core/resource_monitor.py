"""Small, nonblocking status-bar resource readout (no image processing)."""
import psutil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QSizePolicy


class ResourceMonitor(QLabel):
    def __init__(self, parent=None, trtext=lambda ru, en: ru):
        super().__init__(parent)
        self.trtext = trtext
        self.process = psutil.Process()
        self.setObjectName('resourceMonitor')
        self.setContentsMargins(6, 0, 6, 0)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setToolTip(trtext(
            'CPU - общая загрузка процессора. ОЗУ - занятая память компьютера. '
            'Astra - память процесса программы, без внешних инструментов. Обновление раз в 2 секунды.',
            'CPU - total processor usage. RAM - used system memory. '
            'Astra - application process memory, excluding external tools. Updates every 2 seconds.'))
        psutil.cpu_percent(interval=None)  # Prime the counter; never block for a sample.
        self.setText('CPU —  ·  '+trtext('ОЗУ', 'RAM')+' —  ·  Astra —')
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

    def refresh(self):
        try:
            cpu = f'{psutil.cpu_percent(interval=None):.0f}%'
        except (psutil.Error, OSError):
            cpu = '—'
        try:
            memory = psutil.virtual_memory()
            used = max(0, memory.total-memory.available)/1024**3
            ram = f'{used:.1f}/{memory.total/1024**3:.1f} '+self.trtext('ГБ', 'GB')
        except (psutil.Error, OSError):
            ram = '—'
        try:
            own = f'{self.process.memory_info().rss/1024**2:.0f} '+self.trtext('МБ', 'MB')
        except (psutil.Error, OSError):
            own = '—'
        self.setText(f'CPU {cpu}  ·  {self.trtext("ОЗУ", "RAM")} {ram}  ·  Astra {own}')
