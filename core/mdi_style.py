"""MDI caption geometry shared by painting and mouse hit testing."""
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QMdiSubWindow, QProxyStyle, QStyle, QStyleOptionTitleBar

class AstraStyle(QProxyStyle):
    def pixelMetric(self,metric,option=None,widget=None):
        if metric==QStyle.PM_TitleBarHeight and widget is not None:
            return round(widget.fontMetrics().height()*1.8)
        return super().pixelMetric(metric,option,widget)

    @staticmethod
    def title_bar_option(option, widget):
        if isinstance(option, QStyleOptionTitleBar):
            return option
        if not isinstance(widget, QMdiSubWindow):
            return None
        # Older PySide exposes the title bar as QStyleOptionComplex in style callbacks.
        title_bar = QStyleOptionTitleBar()
        title_bar.rect = option.rect
        title_bar.palette = option.palette
        title_bar.fontMetrics = option.fontMetrics
        title_bar.state = option.state
        title_bar.text = widget.windowTitle()
        title_bar.icon = widget.windowIcon()
        title_bar.titleBarState = widget.windowState().value
        return title_bar

    def caption_buttons(self, option):
        buttons = [QStyle.SC_TitleBarCloseButton]
        buttons.append(QStyle.SC_TitleBarNormalButton if option.titleBarState & Qt.WindowMaximized.value else QStyle.SC_TitleBarMaxButton)
        buttons.append(QStyle.SC_TitleBarNormalButton if option.titleBarState & Qt.WindowMinimized.value else QStyle.SC_TitleBarMinButton)
        return list(dict.fromkeys(buttons))

    def subControlRect(self, control, option, subcontrol, widget=None):
        title_bar = self.title_bar_option(option, widget) if control == QStyle.CC_TitleBar else None
        if title_bar is None:
            return super().subControlRect(control, option, subcontrol, widget)
        option = title_bar
        rect = option.rect
        size = rect.height()
        buttons = self.caption_buttons(option)
        if subcontrol in buttons:
            return QRect(rect.right()-(buttons.index(subcontrol)+1)*size+1, rect.top(), size, rect.height())
        if subcontrol == QStyle.SC_TitleBarSysMenu:
            return QRect(rect.left(), rect.top(), size, rect.height())
        if subcontrol == QStyle.SC_TitleBarLabel:
            return rect.adjusted(size, 0, -size*len(buttons), 0)
        return QRect()

    def hitTestComplexControl(self, control, option, position, widget=None):
        title_bar = self.title_bar_option(option, widget) if control == QStyle.CC_TitleBar else None
        if title_bar is None:
            return super().hitTestComplexControl(control, option, position, widget)
        option = title_bar
        for subcontrol in self.caption_buttons(option)+[QStyle.SC_TitleBarSysMenu,QStyle.SC_TitleBarLabel]:
            if self.subControlRect(control,option,subcontrol,widget).contains(position):
                return subcontrol
        return QStyle.SC_None

    def drawComplexControl(self, control, option, painter, widget=None):
        title_bar = self.title_bar_option(option, widget) if control == QStyle.CC_TitleBar else None
        if title_bar is None:
            return super().drawComplexControl(control, option, painter, widget)
        option = title_bar
        painter.save()
        background = option.palette.color(QPalette.Window)
        active = widget.property('activeDocument') if widget is not None else bool(option.state & QStyle.State_Active)
        if active:
            accent = QColor('#78a9c7') if background.lightness() < 140 else QColor('#427c9f')
            background = QColor(
                round(background.red() * .82 + accent.red() * .18),
                round(background.green() * .82 + accent.green() * .18),
                round(background.blue() * .82 + accent.blue() * .18),
            )
        painter.fillRect(option.rect, background)
        painter.setPen(option.palette.color(QPalette.WindowText))
        label=self.subControlRect(control,option,QStyle.SC_TitleBarLabel,widget)
        text=option.fontMetrics.elidedText(option.text,Qt.ElideRight,max(0,label.width()-8))
        painter.drawText(label.adjusted(4,0,-4,0),Qt.AlignCenter,text)
        for subcontrol in self.caption_buttons(option)+[QStyle.SC_TitleBarSysMenu]:
            rect=self.subControlRect(control,option,subcontrol,widget)
            if subcontrol == QStyle.SC_TitleBarSysMenu:
                option.icon.paint(painter,rect.adjusted(4,4,-4,-4))
                continue
            side=max(1,round(rect.height()*.4))
            mark = QRect(0,0,side,side)
            mark.moveCenter(rect.center())
            if subcontrol == QStyle.SC_TitleBarCloseButton:
                painter.drawLine(mark.topLeft(),mark.bottomRight())
                painter.drawLine(mark.topRight(),mark.bottomLeft())
            elif subcontrol == QStyle.SC_TitleBarMinButton:
                painter.drawLine(mark.bottomLeft(),mark.bottomRight())
            elif subcontrol == QStyle.SC_TitleBarNormalButton:
                painter.drawRect(mark.adjusted(2,0,0,-2))
                painter.fillRect(mark.adjusted(0,2,-2,0),background)
                painter.drawRect(mark.adjusted(0,2,-2,0))
            else:
                painter.drawRect(mark)
        painter.restore()
