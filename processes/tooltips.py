"""Delayed setting help shared by all process panels."""
from core.i18n import localize
from PySide6.QtCore import QObject,QEvent,QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QWidget,QToolTip,QApplication,QFormLayout

HELP={
 'device':'Где выполнять вычисления. Авто выбирает доступный вариант; GPU требует поддержки со стороны инструмента.',
 'overlap':'Перекрытие соседних блоков обработки. Помогает уменьшить швы, но увеличивает объём вычислений.',
 'ml_version':'Версия модели RC-Astro. 0 выбирает актуальную доступную модель.',
 'sharpen_stars':'Сила повышения резкости звёзд. Уменьшите при появлении неестественных контуров.',
 'halos':'Коррекция ореолов звёзд: отрицательные значения уменьшают, положительные увеличивают ореолы.',
 'auto_psf':'Автоматическая оценка размытия звёзд. Отключите для ручного задания диаметра PSF.',
 'psf':'Размер размытия PSF в пикселях. Используется деконволюцией для восстановления деталей.',
 'sharpen_nonstellar':'Сила повышения резкости протяжённых объектов, включая туманности и галактики.',
 'correct_only':'Только коррекция аберраций, без дополнительного повышения резкости.',
 'lunar':'Режим для изображений Луны и планет.',
 'intensity_high':'Подавление мелкомасштабного яркостного шума.',
 'intensity_low':'Подавление крупномасштабного яркостного шума.',
 'color_high':'Подавление мелких цветных шумовых пятен.',
 'color_low':'Подавление крупных цветных шумовых пятен.',
 'frequency_scale':'Граница между мелкими и крупными структурами шума, в пикселях.',
 'iterations':'Количество проходов шумоподавления. Больше проходов увеличивает время обработки.',
 'stars':'Создать отдельное изображение выделенных звёзд.',
 'unscreen':'Подготовить слой звёзд для обратного объединения в режиме «Экран».',
 'smoothing':'Сглаживание модели фона GraXpert. Более высокие значения делают модель плавнее.',
 'correction':'Вычитание исправляет добавочный фон; деление используется для относительных перепадов освещённости.',
 'background':'Открыть рассчитанную модель фона отдельным изображением.',
 'strength':'Интенсивность обработки.',
 'gpu':'Использовать GPU, если его поддерживает установленная версия GraXpert.',
 'batch':'Число блоков, обрабатываемых одновременно. Увеличение требует больше памяти GPU.',
 'model':'Версия модели GraXpert. Пустое поле оставляет автоматический выбор.',
 'mode':'Укажите состояние пикселей изображения. Предрастяжка просмотра сама по себе не делает данные нелинейными.',
 'stride':'Шаг обработки StarNet в пикселях. Меньший шаг увеличивает перекрытие и время обработки.',
 'upsample':'Обработка при увеличении изображения вдвое. Требует больше памяти и времени.',
 'shadows':'Порог теней в единицах MAD для линейного режима StarNet.',
 'target':'Целевая яркость фона при растяжении линейного изображения.',
 'protect':'Сохранять яркие области от чрезмерного изменения при обработке StarNet.',
 'percentile':'Доля наиболее тёмных участков, используемых для оценки цвета фона. Снижайте, если кадр заполнен туманностью.',
 'grid':'Количество участков по каждой стороне сетки для оценки фона.',
 'sigma':'Порог исключения ярких звёзд из фоновой выборки. Меньшее значение исключает больше ярких пикселей.',
}

class DelayedHelp(QObject):
    def __init__(self,parent):
        super().__init__(parent);self.target=None;self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.show)
    def eventFilter(self,widget,event):
        if not isinstance(widget,QWidget):return False
        if event.type()==QEvent.Enter and widget.toolTip():
            self.target=widget;self.timer.start(2000)
        elif event.type() in (QEvent.Leave,QEvent.Hide,QEvent.MouseButtonPress) and widget is self.target:
            self.timer.stop();self.target=None;QToolTip.hideText()
        elif event.type()==QEvent.ToolTip:return True
        return False
    def show(self):
        try:
            if self.target and self.target.isVisible() and self.target.underMouse():QToolTip.showText(QCursor.pos(),self.target.toolTip(),self.target)
        except RuntimeError:self.target=None

def add_form_help(page):
    for form in page.findChildren(QFormLayout):
        for row in range(form.rowCount()):
            field=form.itemAt(row,QFormLayout.FieldRole);label=form.itemAt(row,QFormLayout.LabelRole)
            if field and field.widget() and label and label.widget():
                widget=field.widget();caption=label.widget()
                if not widget.toolTip():widget.setToolTip(caption.text()+localize('. Измените значение для настройки обработки.'))
                caption.setToolTip(widget.toolTip())
