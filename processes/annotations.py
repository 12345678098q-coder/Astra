"""Catalog labels projected through the image's celestial WCS."""
from core.i18n import localize
import csv
from pathlib import Path
import numpy as np
from astropy.wcs import WCS
from astropy.coordinates import SkyCoord
import astropy.units as u
from PySide6.QtCore import Qt,QPointF,QRectF
from PySide6.QtGui import QColor,QPen,QPolygonF,QPainter
from PySide6.QtWidgets import QWidget,QVBoxLayout,QFormLayout,QCheckBox,QSpinBox,QPushButton,QColorDialog,QFileDialog,QLabel,QMessageBox
from .astap_updates import HOME

def catalog_path():
    for path in (HOME/'deep_sky.csv',Path('C:/Program Files/astap/deep_sky.csv')):
        if path.is_file():return path
    raise ValueError(localize('Каталог подписей не найден. Нажмите «Установить / обновить ASTAP и каталог».'))

def project_objects(header,shape,stars=True,deep=True,limit=150,path=None):
    rows=[]
    with Path(path or catalog_path()).open(encoding='utf-8-sig') as stream:
        for row in csv.reader(stream):
            try:
                ra=float(row[0])*360/864000;dec=float(row[1])/3600;name=row[2]
                if name.startswith(('NP_','SP_')):continue
                major=float(row[3])/600 if len(row)>3 and row[3] else 0
                minor=float(row[4])/600 if len(row)>4 and row[4] else major
                angle=float(row[5]) if len(row)>5 and row[5] else 0
                star=len(row)<=3
                if (star and stars) or (not star and deep):rows.append((ra,dec,name,major,minor,angle,star))
            except (ValueError,IndexError):continue
    if not rows:return []
    wcs=WCS(header).celestial
    if not wcs.has_celestial:raise ValueError(localize('Сначала определите координаты изображения.'))
    x,y=wcs.world_to_pixel_values([r[0] for r in rows],[r[1] for r in rows]);height,width=shape[:2]
    indices=np.flatnonzero(np.isfinite(x)&np.isfinite(y)&(x>=0)&(x<width)&(y>=0)&(y<height))
    indices=sorted(indices,key=lambda i:(not rows[i][6],-rows[i][3]))[:limit]
    result=[]
    for i in indices:
        ra,dec,name,major,minor,angle,star=rows[i];points=[]
        if major>0:
            theta=np.linspace(0,2*np.pi,49);east=minor/2*np.sin(theta);north=major/2*np.cos(theta)
            pa=np.radians(angle);e=east*np.cos(pa)+north*np.sin(pa);n=north*np.cos(pa)-east*np.sin(pa)
            coords=SkyCoord(ra*u.deg,dec*u.deg).directional_offset_by(np.arctan2(e,n)*u.rad,np.hypot(e,n)*u.deg)
            px,py=wcs.world_to_pixel(coords)
            if np.isfinite([px,py]).all():points=np.column_stack((px,py)).tolist()
        result.append({'x':float(x[i]),'y':float(y[i]),'name':name.replace('_',' '),'points':points})
    return result

def paint_annotations(painter,items,options,scale=1):
    painter.save();painter.setRenderHint(QPainter.Antialiasing)
    color=QColor(options.get('color','#50ff30'));font=painter.font();font.setPixelSize(max(1,round(options.get('font',14)/scale)));painter.setFont(font)
    painter.setPen(QPen(color,1.2/scale));occupied=[]
    for item in items:
        point=QPointF(item['x'],item['y'])
        if options.get('outlines',True):
            if item['points']:painter.drawPolyline(QPolygonF([QPointF(*p) for p in item['points']]))
            else:painter.drawEllipse(point,5/scale,5/scale)
        label=item['name'] if options.get('aliases',False) else item['name'].split('/')[0]
        metrics=painter.fontMetrics();height=metrics.height()
        location=point+QPointF(7/scale,-7/scale)
        for shift in (0,1,-1,2,-2,3,-3):
            candidate=point+QPointF(7/scale,-7/scale+shift*(height+3/scale))
            bounds=QRectF(metrics.boundingRect(label));bounds.translate(candidate)
            if not any(bounds.intersects(other) for other in occupied):location=candidate;break
        bounds=QRectF(metrics.boundingRect(label));bounds.translate(location);occupied.append(bounds)
        painter.setPen(QPen(QColor('#101010'),3/scale));painter.drawText(location+QPointF(1/scale,1/scale),label)
        painter.setPen(QPen(color,1.2/scale));painter.drawText(location,label)
    painter.restore()

class AnnotationPanel(QWidget):
    def __init__(self,window):
        super().__init__();self.window=window;layout=QVBoxLayout(self);layout.addWidget(QLabel(localize('Подписи объектов')))
        self.controls={};form=QFormLayout();layout.addLayout(form)
        for key,label in [('stars',localize('Именованные звёзды')),('deep',localize('Объекты глубокого космоса')),('outlines',localize('Контуры объектов')),('aliases',localize('Альтернативные названия'))]:
            control=QCheckBox(label);control.setChecked(window.settings.value('annotation/'+key,key!='aliases',type=bool));control.setToolTip(label+localize(' на основе каталога ASTAP.'));form.addRow(control);self.controls[key]=control;control.toggled.connect(self.save)
        for key,label,default,low,high in [('font',localize('Размер подписей'),14,8,40),('limit',localize('Максимум объектов'),150,1,1000)]:
            control=QSpinBox();control.setRange(low,high);control.setValue(window.settings.value('annotation/'+key,default,type=int));form.addRow(label,control);self.controls[key]=control;control.valueChanged.connect(self.save)
        self.color=str(window.settings.value('annotation/color','#50ff30'));color=QPushButton(localize('Цвет подписей…'));color.clicked.connect(self.choose_color);layout.addWidget(color)
        for label,callback in [(localize('Показать / обновить подписи'),self.apply),(localize('Скрыть подписи'),self.hide_annotations),(localize('Сохранить фото с подписями…'),self.export)]:
            button=QPushButton(label);button.clicked.connect(callback);layout.addWidget(button)
        self.status=QLabel();self.status.setWordWrap(True);layout.addWidget(self.status)
        reset=QPushButton(localize('Сбросить настройки подписей'));reset.clicked.connect(self.reset);layout.addWidget(reset)
    def reset(self):
        for key,control in self.controls.items():
            if isinstance(control,QCheckBox):control.setChecked(key!='aliases')
            else:control.setValue(14 if key=='font' else 150)
        self.color='#50ff30';self.save()
    def options(self):
        return {**{key:field.isChecked() if isinstance(field,QCheckBox) else field.value() for key,field in self.controls.items()},'color':self.color}
    def save(self):
        for key,value in self.options().items():self.window.settings.setValue('annotation/'+key,value)
    def choose_color(self):
        color=QColorDialog.getColor(QColor(self.color),self)
        if color.isValid():self.color=color.name();self.save()
    def record(self):return self.window.documents.get(self.window.mdi.activeSubWindow())
    def apply(self):
        record=self.record()
        if record is None:return
        if record.get('wcs_header') is None:self.status.setText(localize('Сначала нажмите «Определить координаты». Для FITS с WCS повторное решение не требуется.'));return
        try:
            options=self.options();items=project_objects(record['wcs_header'],record['data'].shape,options['stars'],options['deep'],options['limit'])
            view=record['image'];view.annotations=items;view.annotation_options=options;view.annotations_visible=True;view.update();self.status.setText(localize('Объектов на фото: {0}. Контуры показывают каталожные размеры.').format(len(items)))
        except Exception as error:self.status.setText(str(error))
    def hide_annotations(self):
        record=self.record()
        if record:record['image'].annotations_visible=False;record['image'].update()
    def export(self):
        record=self.record()
        if record is None:return
        view=record['image']
        if not view.annotations:self.status.setText(localize('Сначала постройте подписи.'));return
        path,_=QFileDialog.getSaveFileName(self,localize('Фото с подписями'),'','PNG (*.png)')
        if not path:return
        if not path.lower().endswith('.png'):path+='.png'
        pix=view.pixmap.copy();painter=QPainter(pix);paint_annotations(painter,view.annotations,view.annotation_options);painter.end()
        if not pix.save(path,'PNG'):QMessageBox.warning(self,'Astra',localize('Не удалось сохранить PNG.'))
