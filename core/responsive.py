"""Font-relative widget constraints and screen-relative window sizes."""
from PySide6.QtCore import QObject, QEvent, QTimer, QSize
from PySide6.QtWidgets import QApplication, QWidget, QLabel


class FormCaption(QLabel):
    """Prefer one line; wrap only when the available row really is too narrow."""
    def sizeHint(self):
        size = super().sizeHint()
        if self.wordWrap():
            size.setWidth(self.fontMetrics().horizontalAdvance(self.text()) + 2 * self.margin())
            size.setHeight(self.fontMetrics().height() + 2 * self.margin())
        return size

    def minimumSizeHint(self):
        return QSize(0, self.fontMetrics().height())


def em(widget, value=1):
    return max(1, round(widget.fontMetrics().height() * value))


class RelativeSize(QObject):
    def __init__(self, widget):
        super().__init__(widget)
        self.constraints = {}
        self.pending = False
        widget.installEventFilter(self)

    def apply(self):
        self.pending = False
        widget = self.parent()
        for method, values in self.constraints.items():
            sizes=[em(widget, value) for value in values]
            if widget.isWindow() and method.startswith('setMinimum'):
                area=QWidget.screen(widget).availableGeometry()
                limits=[area.width(),area.height()] if len(sizes)==2 else [area.height() if 'Height' in method else area.width()]
                sizes=[min(size,round(limit*.9)) for size,limit in zip(sizes,limits)]
            getattr(widget, method)(*sizes)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.FontChange, QEvent.StyleChange) and not self.pending:
            self.pending = True
            QTimer.singleShot(0, self, self.apply)
        return False


def set_em_size(widget, method, *values):
    binding = getattr(widget, '_relative_size', None)
    if binding is None:
        binding = RelativeSize(widget)
        widget._relative_size = binding
    binding.constraints[method] = values
    binding.apply()


def fit_screen(widget, width=.75, height=.75):
    screen = QWidget.screen(widget) or QApplication.primaryScreen()
    available = screen.availableGeometry()
    widget.resize(round(available.width() * width), round(available.height() * height))
    if not hasattr(widget,'_screen_fit'):
        widget._screen_fit=ScreenFit(widget)


class ScreenFit(QObject):
    def __init__(self,widget):
        super().__init__(widget)
        self.connected=False
        widget.installEventFilter(self)

    def fit(self,*args):
        widget=self.parent()
        if not widget.isWindow():return
        area=QWidget.screen(widget).availableGeometry()
        if hasattr(widget,'_relative_size'):widget._relative_size.apply()
        minimum=widget.minimumSize()
        widget.setMinimumSize(min(minimum.width(),round(area.width()*.9)),min(minimum.height(),round(area.height()*.9)))
        if not widget.isMaximized():
            widget.resize(min(widget.width(),round(area.width()*.96)),min(widget.height(),round(area.height()*.94)))
            frame=widget.frameGeometry()
            widget.move(widget.pos().x()+max(area.left()-frame.left(),min(0,area.right()-frame.right())),
                        widget.pos().y()+max(area.top()-frame.top(),min(0,area.bottom()-frame.bottom())))

    def eventFilter(self,watched,event):
        if event.type()==QEvent.Show:
            handle=watched.windowHandle()
            if handle is not None and not self.connected:
                handle.screenChanged.connect(self.fit)
                self.connected=True
            QTimer.singleShot(0,self,self.fit)
        return False
