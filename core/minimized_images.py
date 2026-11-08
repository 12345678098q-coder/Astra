"""Application-level restore strip for minimized image documents."""
from core.responsive import set_em_size
from PySide6.QtCore import Qt,QTimer,QPoint
from PySide6.QtWidgets import QDialog,QHBoxLayout,QPushButton

class MinimizedImages(QDialog):
 def __init__(self,owner):
  super().__init__(owner,Qt.Tool|Qt.FramelessWindowHint|Qt.WindowDoesNotAcceptFocus)
  self.owner=owner;self.setAttribute(Qt.WA_ShowWithoutActivating);self.row=QHBoxLayout(self);self.row.setContentsMargins(4,3,4,3);self.windows=[]
  self.timer=QTimer(self);self.timer.setInterval(150);self.timer.timeout.connect(self.sync);self.timer.start()
 def sync(self):
  windows=[w for w in self.owner.documents if w.isMinimized() and not w.isHidden()]
  if windows!=self.windows:
   while self.row.count():
    item=self.row.takeAt(0);item.widget().deleteLater()
   self.windows=windows
   for window in windows:
    restore=QPushButton(window.windowTitle());set_em_size(restore,'setMaximumWidth',11.25);restore.setToolTip(self.owner.trtext('Восстановить изображение','Restore image')+': '+window.windowTitle());restore.clicked.connect(lambda checked=False,w=window:self.restore(w));self.row.addWidget(restore)
    close=QPushButton('×');set_em_size(close,'setFixedWidth',1.625);close.setToolTip(self.owner.trtext('Закрыть изображение','Close image'));close.clicked.connect(lambda checked=False,w=window:w.close());self.row.addWidget(close)
   self.adjustSize()
  if not windows or not self.owner.isVisible() or self.owner.isMinimized():self.hide();return
  self.setMaximumWidth(max(200,self.owner.width()-16));self.adjustSize()
  position=self.owner.statusBar().mapToGlobal(QPoint(8,0));self.move(position.x(),position.y()-self.height()-4)
  if not self.isVisible():self.show()
  self.raise_()
 def restore(self,window):
  window.showNormal();self.owner.mdi.setActiveSubWindow(window);self.owner.activate_document(window);self.sync()
