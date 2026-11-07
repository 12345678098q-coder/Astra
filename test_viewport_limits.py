import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF,QRectF,QSize,Qt,QEvent
from PySide6.QtGui import QPixmap,QMouseEvent
from core.image_view import ImageView

class ViewportLimitsTest(unittest.TestCase):
    def test_corners_zoom_and_drag_remain_visible(self):
        app=QApplication.instance() or QApplication([]);view=ImageView();view.resize(600,400);view.show()
        pix=QPixmap(100,80);pix.fill(Qt.white);view.setPixmap(pix,QSize(1000,800))
        def visible():
            image=QRectF(view.offset.x(),view.offset.y(),view.source_size.width()*view.scale,view.source_size.height()*view.scale)
            area=image.intersected(QRectF(view.rect()))
            maximum=min(image.width(),view.width())*min(image.height(),view.height())
            self.assertGreaterEqual(area.width()*area.height()+1e-6,.1*maximum)
        for scale in (.05,1,64):
            view.scale=scale;view.fitted=False
            for x,y in ((1e6,1e6),(-1e6,-1e6),(-1e6,1e6),(1e6,-1e6)):
                view.offset=QPointF(x,y);view.constrain_offset();visible()
        view.drag_position=QPointF(0,0)
        event=QMouseEvent(QEvent.MouseMove,QPointF(-1e6,1e6),QPointF(-1e6,1e6),Qt.NoButton,Qt.LeftButton,Qt.NoModifier)
        view.mouseMoveEvent(event);visible()
        view.zoom_at(QPointF(0,0),.001);visible()
        view.resize(160,110);app.processEvents();visible();view.close()

if __name__=='__main__':unittest.main()
