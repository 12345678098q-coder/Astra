"""Small, theme-aware document toolbar icons."""
from PySide6.QtCore import Qt, QRect, QPoint
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QIcon

def document_icon(kind,color):
    pix=QPixmap(24,24);pix.fill(Qt.transparent)
    painter=QPainter(pix);painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor(color),1.7))
    if kind=='linked_views':
        painter.drawRoundedRect(2,5,12,9,3,3);painter.drawRoundedRect(10,10,12,9,3,3);painter.drawLine(8,12,16,12)
    elif kind=='quality_limits':
        painter.drawPolygon([QPoint(12,2),QPoint(23,21),QPoint(1,21)])
        painter.drawLine(12,8,12,14);painter.drawPoint(12,18)
    elif kind=='quality_difference':
        painter.drawRect(2,3,20,18);painter.drawLine(12,3,12,21)
        painter.drawLine(5,12,9,12);painter.drawLine(15,12,20,12);painter.drawLine(17,9,17,15)
    elif kind=='rename':
        painter.drawLine(4,20,20,20)
        painter.drawPolygon([QPoint(x,y) for x,y in [(5,16),(7,11),(17,1),(21,5),(11,15),(5,16)]])
    elif kind=='low_preview':
        painter.drawRect(2,3,20,14);painter.drawLine(8,21,16,21);painter.drawLine(12,17,12,21)
        painter.drawRect(5,6,4,4);painter.drawRect(12,9,5,5)
    elif kind in ('split_rgb','luminance'):
        colours=('#d88181','#82b98c','#84a9d0') if kind=='split_rgb' else (color,color,color)
        for (x,y),c in zip(((3,3),(8,8),(13,13)),colours):
            painter.setPen(QPen(QColor(c),1.6));painter.drawRect(x,y,8,8)
        if kind=='luminance':
            painter.setBrush(QColor(color));painter.drawRect(15,15,4,4)
    else:
        painter.drawEllipse(3,3,18,18);painter.setBrush(QColor(color))
        painter.drawPie(QRect(3,3,18,18),90*16,180*16)
    painter.end();return QIcon(pix)
