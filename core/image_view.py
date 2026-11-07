"""Image viewport with cursor-anchored zoom and direct panning."""
from core.responsive import set_em_size
from core.i18n import localize
from PySide6.QtCore import Qt,QPointF,QRectF,QRect,Signal
from PySide6.QtGui import QPainter,QPen,QColor
from PySide6.QtWidgets import QWidget,QMenu,QInputDialog
import math

class ImageView(QWidget):
    viewportChanged=Signal()
    cropChanged=Signal()
    regionSelected=Signal()
    stretchRequested=Signal(bool)
    renameRequested=Signal()
    splitRequested=Signal()
    luminanceRequested=Signal()
    def __init__(self,parent=None):
        super().__init__(parent)
        self.annotations=[];self.annotation_options={};self.annotations_visible=False
        self.crop_enabled=False; self.crop_rect=None; self.crop_start=None; self.crop_ratio=0;self.crop_angle=0.
        self.crop_action=None;self.crop_origin=None;self.setMouseTracking(True)
        self.pixmap=None; self.scale=1.; self.offset=QPointF(); self.fitted=True
        self.brush_handler=None;self.brush_position=None;self.brush_drawing=False
        self.sample_rects=[]
        self.point_handler=None;self.background_points=[];self.background_sample_radius=25
        self.drag_position=None; self.stretched=True
        self.setCursor(Qt.OpenHandCursor); set_em_size(self,'setMinimumSize',6.25,6.25)

    def setPixmap(self,pixmap,source_size=None):
        self.message=None
        size=source_size or pixmap.size()
        changed=self.pixmap is None or self.source_size!=size
        self.source_size=size
        if changed:self.crop_rect=None;self.crop_angle=0.
        self.pixmap=pixmap
        if changed or self.fitted:self.fit_image()
        else:self.constrain_offset();self.update()

    def clear(self):
        self.pixmap=None;self.message=None;self.fitted=True;self.update()

    def setText(self,message):
        self.clear();self.message=message;self.update()

    def fit_image(self):
        self.fitted=True
        if self.pixmap is not None and not self.pixmap.isNull():
            self.scale=min(self.width()/self.source_size.width(),self.height()/self.source_size.height())
            self.offset=QPointF((self.width()-self.source_size.width()*self.scale)/2,(self.height()-self.source_size.height()*self.scale)/2)
        self.update()

    def zoom_at(self,position,factor):
        if self.pixmap is None:return
        image_position=(position-self.offset)/self.scale
        self.scale=max(0.001,min(64.,self.scale*factor))
        self.offset=position-image_position*self.scale
        self.constrain_offset()
        self.fitted=False; self.update();self.viewportChanged.emit()

    def set_zoom_percent(self,percent):
        self.zoom_at(QPointF(self.width()/2,self.height()/2),percent/100/self.scale)

    def choose_zoom_percent(self):
        percent,ok=QInputDialog.getDouble(self,localize('Масштаб'),localize('Масштаб, %'),self.scale*100,.1,6400,1)
        if ok:self.set_zoom_percent(percent)

    def constrain_offset(self):
        """Keep >=10% of the maximally visible image area reachable on screen.

        At high zoom the complete image cannot fit: use the viewport dimensions
        as the bound instead. Requiring sqrt(.1) on each axis also protects corners.
        """
        if self.pixmap is None or self.pixmap.isNull():return
        width=self.source_size.width()*self.scale;height=self.source_size.height()*self.scale
        if min(width,height,self.width(),self.height())<=0:return
        fraction=.1**.5
        visible_x=min(width,self.width())*fraction;visible_y=min(height,self.height())*fraction
        self.offset=QPointF(max(visible_x-width,min(self.width()-visible_x,self.offset.x())),
                           max(visible_y-height,min(self.height()-visible_y,self.offset.y())))

    def wheelEvent(self,event):
        amount=event.angleDelta().y() or event.pixelDelta().y()
        if amount:self.zoom_at(event.position(),1.2**(amount/120.))
        event.accept()

    def mousePressEvent(self,event):
        if self.point_handler is not None and self.pixmap is not None and event.button() in (Qt.LeftButton,Qt.RightButton):
            p=(event.position()-self.offset)/self.scale
            self.point_handler(p,event.button());event.accept();return
        if self.brush_handler is not None and self.pixmap is not None and event.button()==Qt.LeftButton:
            p=(event.position()-self.offset)/self.scale
            if 0<=p.x()<self.source_size.width() and 0<=p.y()<self.source_size.height():
                self.brush_handler.press(p,event.modifiers());self.brush_drawing=True
            event.accept();return
        if self.crop_enabled and self.pixmap is not None and event.button()==Qt.LeftButton:
            p=(event.position()-self.offset)/self.scale
            hit=self.crop_hit(p)
            self.crop_origin=p;self.crop_original=QRect(self.crop_rect) if self.crop_rect is not None else None
            if hit=='rotate':
                center=QRectF(self.crop_rect).center();self.crop_rotate_start=math.degrees(math.atan2(p.y()-center.y(),p.x()-center.x()));self.crop_rotate_original=self.crop_angle
                self.crop_action='rotate';event.accept();return
            if hit=='move':self.crop_action='move';event.accept();return
            if hit is not None:
                corners=self.crop_corners();opposite={'tl':'br','tr':'bl','bl':'tr','br':'tl'}
                self.crop_start=corners[opposite[hit]];self.crop_fixed_corner=self.crop_start;self.crop_resize_key=hit;self.crop_action='resize';event.accept();return
            self.crop_action='draw'
            self.crop_angle=0.
            self.crop_start=QPointF(max(0,min(self.source_size.width(),p.x())),max(0,min(self.source_size.height(),p.y())))
            self.setCursor(Qt.CrossCursor)
            event.accept();return
        if event.button() in (Qt.LeftButton,Qt.MiddleButton) and self.pixmap is not None:
            self.drag_position=event.position(); self.setCursor(Qt.ClosedHandCursor); event.accept()
        else:super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self.brush_handler is not None and self.pixmap is not None:
            p=(event.position()-self.offset)/self.scale
            p=QPointF(max(0,min(self.source_size.width()-1,p.x())),max(0,min(self.source_size.height()-1,p.y())))
            self.brush_position=p
            if self.brush_drawing and event.buttons() & Qt.LeftButton:self.brush_handler.move(p)
            self.update()
            if event.buttons() & Qt.LeftButton:event.accept();return
        if self.crop_action=='move' and event.buttons() & Qt.LeftButton:
            self.move_crop((event.position()-self.offset)/self.scale);event.accept();return
        if self.crop_action=='rotate' and event.buttons() & Qt.LeftButton:
            self.rotate_crop((event.position()-self.offset)/self.scale);event.accept();return
        if self.crop_start is not None and event.buttons() & (Qt.LeftButton|Qt.MiddleButton):
            self.select_crop((event.position()-self.offset)/self.scale);event.accept();return
        if self.drag_position is not None and event.buttons() & (Qt.LeftButton|Qt.MiddleButton):
            self.offset+=event.position()-self.drag_position; self.drag_position=event.position()
            self.constrain_offset()
            self.fitted=False; self.update();self.viewportChanged.emit(); event.accept()
        else:
            if self.crop_enabled:
                hit=self.crop_hit((event.position()-self.offset)/self.scale)
                self.setCursor(Qt.SizeAllCursor if hit=='move' else Qt.PointingHandCursor if hit=='rotate' else Qt.SizeFDiagCursor if hit in ('tl','br') else Qt.SizeBDiagCursor if hit else Qt.CrossCursor)
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.LeftButton and self.brush_drawing:
            self.brush_drawing=False
            if self.brush_handler is not None:self.brush_handler.release()
            event.accept();return
        if self.crop_action=='move':
            self.move_crop((event.position()-self.offset)/self.scale);self.crop_action=None;event.accept();return
        if self.crop_action=='rotate':
            self.rotate_crop((event.position()-self.offset)/self.scale);self.crop_action=None;event.accept();return
        if self.crop_start is not None:
            self.select_crop((event.position()-self.offset)/self.scale);self.crop_start=None;self.crop_action=None;self.regionSelected.emit();event.accept();return
        self.drag_position=None; self.setCursor(Qt.OpenHandCursor); super().mouseReleaseEvent(event)

    def crop_corners(self):
        r=QRectF(self.crop_rect)
        corners={'tl':r.topLeft(),'tr':r.topRight(),'bl':r.bottomLeft(),'br':r.bottomRight()}
        if not self.crop_angle:return corners
        return {key:self.rotate_crop_point(point) for key,point in corners.items()}

    def rotate_crop_point(self,point):
        center=QRectF(self.crop_rect).center();dx=point.x()-center.x();dy=point.y()-center.y();angle=math.radians(self.crop_angle)
        return QPointF(center.x()+math.cos(angle)*dx-math.sin(angle)*dy,center.y()+math.sin(angle)*dx+math.cos(angle)*dy)

    def crop_rotation_handle(self):
        r=QRectF(self.crop_rect);return self.rotate_crop_point(QPointF(r.center().x(),r.bottom()+max(18,20/self.scale)))

    def rotate_crop(self,point):
        center=QRectF(self.crop_rect).center();angle=math.degrees(math.atan2(point.y()-center.y(),point.x()-center.x()))
        self.crop_angle=(self.crop_rotate_original+angle-self.crop_rotate_start+180)%360-180
        self.cropChanged.emit();self.update()

    def crop_hit(self,point):
        if self.crop_rect is None:return None
        handle=self.crop_rotation_handle()
        if (point-handle).manhattanLength()*self.scale<=12:return 'rotate'
        for key,corner in self.crop_corners().items():
            if max(abs(point.x()-corner.x()),abs(point.y()-corner.y()))*self.scale<=8:return key
        from PySide6.QtGui import QPolygonF
        corners=self.crop_corners()
        if QPolygonF([corners[key] for key in ('tl','tr','br','bl')]).containsPoint(point,Qt.OddEvenFill):return 'move'
        return None

    def move_crop(self,point):
        r=QRect(self.crop_original);delta=point-self.crop_origin
        r.moveTo(max(0,min(self.source_size.width()-r.width(),round(r.x()+delta.x()))),max(0,min(self.source_size.height()-r.height(),round(r.y()+delta.y()))))
        self.crop_rect=r;self.cropChanged.emit();self.update()

    def select_crop(self,point):
        if self.crop_start is None or self.pixmap is None:return
        if self.crop_action=='resize' and self.crop_angle:
            fixed=self.crop_fixed_corner;dx=point.x()-fixed.x();dy=point.y()-fixed.y()
            angle=math.radians(self.crop_angle);c=math.cos(angle);s=math.sin(angle)
            local_x=c*dx+s*dy;local_y=-s*dx+c*dy
            width=max(1,round(abs(local_x)));height=max(1,round(abs(local_y)))
            if self.crop_ratio:height=max(1,round(width/self.crop_ratio))
            signs={'tl':(-1,-1),'tr':(1,-1),'bl':(-1,1),'br':(1,1)}
            sx,sy=signs[self.crop_resize_key];corner=QPointF(fixed.x()+c*sx*width-s*sy*height,fixed.y()+s*sx*width+c*sy*height)
            center=(fixed+corner)/2
            self.crop_rect=QRect(round(center.x()-width/2),round(center.y()-height/2),width,height)
            self.cropChanged.emit();self.update();return
        x0,y0=round(self.crop_start.x()),round(self.crop_start.y())
        dx=max(0,min(self.source_size.width(),point.x()))-x0;dy=max(0,min(self.source_size.height(),point.y()))-y0
        w,h=abs(dx),abs(dy)
        if self.crop_ratio:
            w=min(w,h*self.crop_ratio);h=w/self.crop_ratio
        w,h=round(w),round(h)
        if w<1 or h<1:return
        self.crop_rect=QRect(x0-w if dx<0 else x0,y0-h if dy<0 else y0,w,h)
        self.cropChanged.emit();self.update()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.fitted:self.fit_image()
        elif event.oldSize().isValid():
            self.offset+=QPointF((event.size().width()-event.oldSize().width())/2,(event.size().height()-event.oldSize().height())/2)
            self.constrain_offset()

    def paintEvent(self,event):
        self.constrain_offset()
        painter=QPainter(self)
        painter.fillRect(self.rect(),self.palette().window())
        if self.pixmap is None and getattr(self,'message',None):
            painter.setPen(self.palette().windowText().color());painter.drawText(self.rect(),Qt.AlignCenter|Qt.TextWordWrap,self.message)
        if self.pixmap is not None:
            painter.setRenderHint(QPainter.SmoothPixmapTransform,self.scale<1)
            painter.translate(self.offset); painter.scale(self.scale,self.scale)
            painter.drawPixmap(QRectF(0,0,self.source_size.width(),self.source_size.height()),self.pixmap,QRectF(self.pixmap.rect()))
            if self.background_points:
                painter.setPen(QPen(QColor('#80e5a0'),1/self.scale))
                r=self.background_sample_radius
                for x,y in self.background_points:painter.drawRect(QRectF(x-r,y-r,r*2,r*2))
            if self.sample_rects:
                painter.save();painter.setPen(QPen(QColor('#ffd780'),1/self.scale))
                font=painter.font();font.setPixelSize(max(1,round(12/self.scale)));painter.setFont(font)
                for index,rect in enumerate(self.sample_rects,1):
                    painter.drawRect(QRectF(rect));painter.drawText(QPointF(rect.x(),rect.y()-3/self.scale),str(index))
                painter.restore()
            if self.brush_handler is not None:
                handler=self.brush_handler
                painter.setPen(QPen(QColor('#74d6ed'),1/self.scale))
                if self.brush_position is not None:
                    radius=handler.fields['radius'].value();painter.drawEllipse(self.brush_position,radius,radius)
                if handler.anchor is not None:
                    p=QPointF(*handler.anchor);r=5/self.scale
                    painter.drawLine(p-QPointF(r,0),p+QPointF(r,0));painter.drawLine(p-QPointF(0,r),p+QPointF(0,r))
                from PySide6.QtGui import QPolygonF
                strokes=[] if handler.mode=='heal' and handler.draft_revision==handler.revision else handler.strokes
                for stroke in strokes+([handler.path] if handler.path else []):
                    painter.drawPolyline(QPolygonF([QPointF(x,y) for x,y in stroke['points']]))
            if self.annotations_visible and self.annotations:
                from processes.annotations import paint_annotations
                painter.save();painter.setClipRect(QRectF(0,0,self.source_size.width(),self.source_size.height()));paint_annotations(painter,self.annotations,self.annotation_options,self.scale);painter.restore()
            if self.crop_enabled and self.crop_rect is not None:
                r=QRectF(self.crop_rect);W,H=self.source_size.width(),self.source_size.height()
                from PySide6.QtGui import QPainterPath,QPolygonF
                corners=self.crop_corners();polygon=QPolygonF([corners[key] for key in ('tl','tr','br','bl')])
                shade=QPainterPath();shade.setFillRule(Qt.OddEvenFill);shade.addRect(QRectF(0,0,W,H));shade.addPolygon(polygon);painter.fillPath(shade,QColor(0,0,0,135))
                painter.setPen(QPen(QColor('#eeeeee'),1/self.scale));painter.drawPolygon(polygon)
                painter.setBrush(QColor('#eeeeee'))
                for point in corners.values():painter.drawRect(QRectF(point.x()-3/self.scale,point.y()-3/self.scale,6/self.scale,6/self.scale))
                handle=self.crop_rotation_handle();bottom=self.rotate_crop_point(QPointF(r.center().x(),r.bottom()))
                painter.drawLine(bottom,handle);painter.drawEllipse(handle,5/self.scale,5/self.scale)

    def contextMenuEvent(self,event):
        if self.point_handler is not None:event.accept();return
        menu=QMenu(self)
        fit=menu.addAction(localize('Вписать в окно')); fit.triggered.connect(lambda:(self.fit_image(),self.viewportChanged.emit()))
        fit.setEnabled(self.pixmap is not None)
        zoom=menu.addMenu(localize('Масштаб'))
        zoom.setEnabled(self.pixmap is not None)
        for percent in (10,25,50,75,100,125,150,200,300,400,800,1600):
            action=zoom.addAction(f'{percent}%')
            action.setCheckable(True);action.setChecked(abs(self.scale*100-percent)<.01)
            action.triggered.connect(lambda checked=False,p=percent:self.set_zoom_percent(p))
        zoom.addSeparator()
        zoom.addAction(localize('Другой…'),self.choose_zoom_percent)
        stretch=menu.addAction(localize('Автопредрастяжка'))
        stretch.setCheckable(True); stretch.setChecked(self.stretched); stretch.toggled.connect(self.stretchRequested)
        menu.addSeparator()
        menu.addAction(localize('Переименовать изображение…'),self.renameRequested.emit)
        menu.addAction(localize('Разделить RGB на изображения'),self.splitRequested.emit)
        menu.addAction(localize('Извлечь яркость'),self.luminanceRequested.emit)
        menu.exec(event.globalPos())
