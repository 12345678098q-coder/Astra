"""One-row application header with menus and native window operations."""
from core.responsive import set_em_size
from PySide6.QtCore import Qt,QEvent,QObject
from PySide6.QtGui import QPainter,QPen,QPalette
from PySide6.QtWidgets import QWidget,QHBoxLayout,QLabel,QToolButton,QApplication,QSizePolicy

class WindowButton(QToolButton):
    def __init__(self,kind,window):
        super().__init__();self.kind=kind;self.owner=window;set_em_size(self,'setFixedSize',2.625,2.0)
    def paintEvent(self,event):
        super().paintEvent(event)
        painter=QPainter(self);painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(self.palette().color(QPalette.ButtonText),1.2))
        side=self.height()*.32
        painter.translate((self.width()-side)/2,(self.height()-side)/2)
        painter.scale(side/10,side/10)
        if self.kind=='minimize':painter.drawLine(0,5,10,5)
        elif self.kind=='close':painter.drawLine(0,0,10,10);painter.drawLine(0,10,10,0)
        elif self.owner.isMaximized():
            painter.drawLine(3,0,10,0);painter.drawLine(10,0,10,7);painter.drawLine(8,7,10,7);painter.drawLine(3,0,3,2)
            painter.drawRect(0,3,7,7)
        else:painter.drawRect(0,0,10,10)

class WindowHeader(QWidget):
    def __init__(self,window,menu):
        super().__init__(window);self.owner=window;self.setObjectName('applicationHeader')
        set_em_size(self,'setFixedHeight',2.25)
        layout=QHBoxLayout(self);layout.setContentsMargins(10,2,2,2);layout.setSpacing(0);layout.setAlignment(Qt.AlignVCenter)
        icon=QLabel();icon.setPixmap(window.windowIcon().pixmap(22,22));icon.setAttribute(Qt.WA_TransparentForMouseEvents);layout.addWidget(icon,0,Qt.AlignVCenter);layout.addSpacing(7)
        title=QLabel('Astra');title.setAlignment(Qt.AlignVCenter);title.setAttribute(Qt.WA_TransparentForMouseEvents);layout.addWidget(title,0,Qt.AlignVCenter);layout.addSpacing(12)
        menu.setObjectName('headerMenu');menu.setNativeMenuBar(False);menu.setSizePolicy(QSizePolicy.Maximum,QSizePolicy.Fixed);layout.addWidget(menu,0,Qt.AlignVCenter)
        guided=getattr(window,'guided_action',None)
        if guided is not None:
            button=QToolButton(self);button.setDefaultAction(guided)
            button.setObjectName('guidedHeaderButton');button.setToolButtonStyle(Qt.ToolButtonTextOnly);button.setAutoRaise(True)
            button.setStyleSheet('''QToolButton {background:transparent;border:0;border-radius:0;padding:5px 10px;}
                QToolButton:checked {background:rgba(100,125,220,65);color:#e0e7ff;}
                QToolButton:hover {background:rgba(100,125,220,40);}''')
            layout.addWidget(button,0,Qt.AlignVCenter);window.guided_header_button=button
        layout.addStretch(1)
        self.buttons={}
        for key,symbol,ru,en,callback in [('minimize','−','Свернуть','Minimize',window.showMinimized),('maximize','□','Развернуть / восстановить','Maximize / restore',self.toggle_maximized),('close','×','Закрыть','Close',window.close)]:
            button=WindowButton(key,window);button.setObjectName('windowClose' if key=='close' else 'windowControl');button.setToolTip(window.trtext(ru,en));button.setAccessibleName(button.toolTip());button.clicked.connect(callback);layout.addWidget(button,0,Qt.AlignVCenter);self.buttons[key]=button
        window.installEventFilter(self)
        self.edge_filter=WindowEdges(window);QApplication.instance().installEventFilter(self.edge_filter)
    def toggle_maximized(self):
        if self.owner.isMaximized():self.owner.showNormal()
        else:self.owner.showMaximized()
    def eventFilter(self,watched,event):
        if event.type()==QEvent.WindowStateChange:self.buttons['maximize'].update()
        return False
    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton and self.owner.windowHandle():
            self.owner.windowHandle().startSystemMove();event.accept()
        else:super().mousePressEvent(event)
    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.LeftButton:self.toggle_maximized();event.accept()
        else:super().mouseDoubleClickEvent(event)

class WindowEdges(QObject):
    def __init__(self,window):super().__init__(window);self.owner=window
    def eventFilter(self,watched,event):
        if event.type()!=QEvent.MouseButtonPress or event.button()!=Qt.LeftButton:return False
        # Tool panels store their owner as `window`, shadowing QWidget.window().
        if not isinstance(watched,QWidget) or QWidget.window(watched) is not self.owner or self.owner.isMaximized() or self.owner.isFullScreen():return False
        point=self.owner.mapFromGlobal(event.globalPosition().toPoint());edges=Qt.Edges()
        if point.x()<5:edges|=Qt.LeftEdge
        elif point.x()>=self.owner.width()-5:edges|=Qt.RightEdge
        if point.y()<5:edges|=Qt.TopEdge
        elif point.y()>=self.owner.height()-5:edges|=Qt.BottomEdge
        if edges and self.owner.windowHandle():return self.owner.windowHandle().startSystemResize(edges)
        return False

def install_header(window):
    menu=window.menuBar()
    # Reparent before replacing the menu widget so QMainWindow keeps the menu alive.
    header=WindowHeader(window,menu);window.setMenuWidget(header);window.application_header=header
    window.setWindowFlag(Qt.FramelessWindowHint,True)
