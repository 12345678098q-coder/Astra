"""Keep process actions below the scrolling settings, in a stable order."""
from PySide6.QtCore import Qt,QTimer,QRect,QSize
from PySide6.QtWidgets import QWidget,QLayout,QPushButton,QSizePolicy

class CompactActionLayout(QLayout):
    def __init__(self,parent):
        super().__init__(parent);self.items=[];self.setContentsMargins(0,8,0,0);self.setSpacing(4)
    def addItem(self,item):self.items.append(item)
    def count(self):return len(self.items)
    def itemAt(self,index):return self.items[index] if 0<=index<len(self.items) else None
    def takeAt(self,index):return self.items.pop(index) if 0<=index<len(self.items) else None
    def hasHeightForWidth(self):return True
    def heightForWidth(self,width):return self.arrange(QRect(0,0,width,0),False)
    def minimumSize(self):
        active=[item for item in self.items if not item.isEmpty()]
        size=QSize(max([item.sizeHint().width() for item in active] or [0]),max([item.sizeHint().height() for item in active] or [0]))
        margins=self.contentsMargins()
        return size+QSize(margins.left()+margins.right(),margins.top()+margins.bottom())
    def sizeHint(self):
        active=[item for item in self.items if not item.isEmpty()]
        margins=self.contentsMargins()
        width=sum(item.sizeHint().width() for item in active)+max(0,len(active)-1)*self.spacing()+margins.left()+margins.right()
        return QSize(width,self.heightForWidth(width))
    def setGeometry(self,rect):
        super().setGeometry(rect);self.arrange(rect,True)
    def arrange(self,rect,place):
        m=self.contentsMargins();width=max(1,rect.width()-m.left()-m.right())
        rows=[];row=[];used=0;height=0
        for item in self.items:
            if item.isEmpty():continue
            size=item.sizeHint();w=min(width,size.width());h=size.height()
            if row and used+self.spacing()+w>width:
                rows.append((row,used,height));row=[];used=0;height=0
            x=used+(self.spacing() if row else 0)
            row.append((item,x,w,h));used=x+w;height=max(height,h)
        if row:rows.append((row,used,height))
        y=rect.y()+m.top()
        for row,used,height in rows:
            extra=max(0,width-used);share,remainder=divmod(extra,len(row));x=0
            for index,(item,_,w,h) in enumerate(row):
                # Distribute spare width into the buttons, never into a large gap.
                w+=share+(1 if index<remainder else 0)
                if place:item.setGeometry(QRect(rect.x()+m.left()+x,y,w,h))
                x+=w+self.spacing()
            y+=height+self.spacing()
        return y-rect.y()-(self.spacing() if rows else 0)+m.bottom()

class AdaptiveFooter(QWidget):
    def __init__(self):
        super().__init__();self.controls=[];self.grid=CompactActionLayout(self)
        policy=QSizePolicy(QSizePolicy.Expanding,QSizePolicy.Preferred);policy.setHeightForWidth(True);self.setSizePolicy(policy)
    def reflow(self):
        self.grid.invalidate();self.updateGeometry()

PREVIEW={'Просмотр','Preview','Предпросмотр','Просмотр маски','View mask'}
RESET={'Сброс','Reset','Сбросить настройки','Reset settings','По умолчанию','Defaults','Сбросить область','Reset region','Сбросить настройки подписей','Reset annotation settings'}
CANCEL={'Отмена','Cancel','Отменить','Отменить предпросмотр','Cancel preview','Отменить вычисление','Cancel calculation','Остановить','Stop','Отменить после текущей операции','Cancel after current operation'}
APPLY={'Применить','Apply','Применить кроп','Apply crop','Создать изображение','Create image','Создать маску','Create mask','Запустить пакет','Run batch','Определить координаты','Обновить координаты','Показать / обновить подписи','Сохранить фото','Solve coordinates','Update coordinates','Show or refresh annotations','Save image'}

def make_footer(page):
    from .native.ui import BasePanel
    for panel in page.findChildren(BasePanel):
        if not any(button.text() in RESET for button in panel.findChildren(QPushButton)):
            panel.button('Сброс','Reset',panel.reset)
    groups=[[],[],[],[]]
    for button in page.findChildren(QPushButton):
        if button.property('astra_stay_in_form'):continue
        text=button.text()
        for index,names in enumerate((PREVIEW,RESET,CANCEL,APPLY)):
            if text in names:groups[index].append(button);break
    if not any(groups):return None
    footer=AdaptiveFooter();footer.setObjectName('actionFooter')
    for index,buttons in enumerate(groups):
        # One main action per group; secondary actions stay in the settings area.
        preferred=({'Предпросмотр','Preview'},{'Сброс','Reset'},{'Отмена','Cancel'},{'Применить','Apply'})[index]
        chosen=next((button for button in buttons if button.text() in preferred),buttons[0] if buttons else None)
        for button in ([chosen] if chosen is not None else []):
            hidden=button.isHidden() and button.objectName()=='starnet_cancel'
            button.setParent(footer);footer.controls.append(button);footer.grid.addWidget(button)
            if not hidden:button.show()
    QTimer.singleShot(0,footer,footer.reflow)
    return footer
