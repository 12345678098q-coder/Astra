"""Native tool panels. All numerical work lives in processing / pixelmath / batch."""
from core.responsive import set_em_size
from core.i18n import localize
import json
from pathlib import Path
import numpy as np
from shiboken6 import isValid
from PySide6.QtCore import Qt,QPointF,QRectF,QRect,QTimer,Signal
from PySide6.QtGui import QPainter,QColor,QPen,QPolygonF,QPainterPath
from PySide6.QtWidgets import *
from . import processing as engine
from .autostretch import DEFAULT_TARGET,auto_settings
from .jobs import launch,cancel

class HistogramPlot(QWidget):
    def __init__(self):super().__init__();set_em_size(self,'setMinimumSize',10.0,7.5);self.values=None;self.channel=0;self.drag=None;self.panel=None;self.views={}
    def full_bounds(self):
        if self.channel:return 0.,1.
        low,high=(self.values['low'],self.values['high']) if self.values else (0.,1.)
        return low,max(high,low+max(1,abs(low))*1e-12)
    def bounds(self):
        return self.views.get(self.channel,self.full_bounds())
    def wheelEvent(self,event):
        if not self.values or not event.angleDelta().y():return
        low,high=self.bounds();full_low,full_high=self.full_bounds()
        span=float(np.clip((high-low)*2**(-event.angleDelta().y()/360), (full_high-full_low)/10000,full_high-full_low))
        if span>=full_high-full_low:
            self.views.pop(self.channel,None)
        else:
            start=low if event.position().x()<self.width()/2 else high-span
            start=float(np.clip(start,full_low,full_high-span));self.views[self.channel]=(start,start+span)
        self.update();event.accept()
    def mouseDoubleClickEvent(self,event):
        self.views.pop(self.channel,None);self.update();event.accept()
    def positions(self):
        low,high=self.bounds();high=max(high,low+1e-12)
        black=self.panel.fields['black'].value();white=self.panel.fields['white'].value();mid=self.panel.fields['mid'].value()
        return [3+(value-low)/(high-low)*(self.width()-6) for value in (black,black+(white-black)*mid,white)]
    def handle_positions(self):
        # Keep each grip accessible even when zoom clips several levels to one edge.
        left,right=7,self.width()-7
        black,mid,white=self.positions()
        mid=float(np.clip(mid,left+14,right-14))
        return (float(np.clip(black,left,mid-14)),mid,float(np.clip(white,mid+14,right)))
    def histogram_curve(self):
        # Build the curve from fixed bins over the whole channel. Rebinning a
        # narrow viewport produces sparse spikes and changes their height.
        channels=self.values['bins']
        bins=np.asarray(channels[min(self.channel,len(channels)-1)],float)
        padded=np.pad(bins,1,mode='edge')
        heights=np.log1p(np.convolve(padded,[.25,.5,.25],mode='valid'))
        return np.linspace(*self.full_bounds(),len(bins)),heights/max(1.,heights.max())
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing);p.fillRect(self.rect(),QColor('#24282b'));p.setPen(QColor('#93a1ac'));p.drawRect(self.rect().adjusted(1,1,-2,-2))
        if not self.values:return
        low,high=self.bounds()
        levels,heights=self.histogram_curve()
        # Keep neighboring knots so the same smoothed path continues across
        # the viewport edges at every zoom level.
        start,end=np.searchsorted(levels,[low,high]);visible=slice(max(0,start-2),end+2)
        xs=3+(levels[visible]-low)/(high-low)*(self.width()-6)
        p.setPen(QPen(QColor(['#dddddd','#ed7777','#77dd88','#7799ee'][self.channel]),1.4))
        points=[QPointF(x,self.height()-19-value*(self.height()-22)) for x,value in zip(xs,heights[visible])]
        if points:
            path=QPainterPath(points[0])
            for a,b in zip(points,points[1:]):path.quadTo(a,(a+b)*.5)
            path.lineTo(points[-1]);p.save();p.setClipRect(QRectF(3,2,self.width()-6,self.height()-20));p.drawPath(path);p.restore()
        p.drawText(5,15,f'{low:.6g}');p.drawText(self.width()-95,15,90,20,Qt.AlignRight,f'{high:.6g}')
        if self.panel:
            inputs=np.linspace(low,high,256)
            settings={key:self.panel.fields[key].value() for key in ('black','white','mid')}
            settings['curve']=self.panel.fields['curve'].text()
            try:
                output=engine.transfer(inputs,settings)
            except ValueError:
                output=None
            if output is not None:
                p.setPen(QPen(QColor('#8ad5ed'),1.5))
                p.drawPolyline(QPolygonF([QPointF(x,self.height()-17-v*(self.height()-22)) for x,v in zip(np.linspace(3,self.width()-3,256),output)]))
            for level,x,color in zip(self.positions(),self.handle_positions(),('#888888','#b5b5b5','#ffffff')):
                level=float(np.clip(level,3,self.width()-3))
                p.setPen(QPen(QColor(color),1));p.drawLine(QPointF(level,3),QPointF(level,self.height()-19))
                p.drawLine(QPointF(level,self.height()-19),QPointF(x,self.height()-17))
                p.setBrush(QColor(color));p.drawPolygon(QPolygonF([QPointF(x,self.height()-17),QPointF(x-6,self.height()-3),QPointF(x+6,self.height()-3)]))
    def mousePressEvent(self,event):
        if self.panel and self.values and event.button()==Qt.LeftButton and event.position().y()>=self.height()-24:
            from core.resources import heavy_job_running
            if heavy_job_running(self.panel.window):return
            self.drag=int(np.argmin([abs(event.position().x()-x) for x in self.handle_positions()]))
            fields=self.panel.fields
            black,white,mid=(fields[key].value() for key in ('black','white','mid'))
            low,high=self.bounds()
            self.drag_origin=(event.position().x(),black,white,black+(white-black)*mid,min(high-low,white-black))
            self.drag_changed=False
            event.accept()
    def mouseMoveEvent(self,event):
        if self.drag is None:return
        start,black,white,center,span=self.drag_origin
        delta=(event.position().x()-start)*span/max(1,self.width()-14)
        if event.modifiers() & Qt.ShiftModifier:delta*=.1
        fields=self.panel.fields
        if self.drag==0:
            black=min(black+delta,(center-.001*white)/.999)
        elif self.drag==2:
            white=max(white+delta,(center-.001*black)/.999)
        else:
            center+=delta
        # Update the endpoints and midtone together to keep the centre anchored.
        if white<=black:return
        self.drag_changed=self.drag_changed or delta!=0
        for key,value in (('black',black),('white',white),('mid',float(np.clip((center-black)/(white-black),.001,.999)))):
            field=fields[key]
            field.blockSignals(True)
            field.setValue(value)
            field.blockSignals(False)
        self.panel.preview_tone()
        self.update()
    def mouseReleaseEvent(self,event):
        changed=self.drag is not None and self.drag_changed
        self.drag=None
        if changed:
            self.panel.save()
            if self.panel.quick_histogram:self.panel.execute(True,quick_manual=True)

class CurvePlot(QWidget):
    dragged=Signal()
    drag_finished=Signal()
    def __init__(self,field):
        super().__init__();self.field=field;self.drag=None;set_em_size(self,'setMinimumSize',10.0,8.75);field.textChanged.connect(self.update)
    def points(self):
        try:return engine.curve_points(self.field.text()).tolist()
        except ValueError:return [[0,0],[1,1]]
    def screen(self,point):return QPointF(8+point[0]*(self.width()-16),self.height()-8-point[1]*(self.height()-16))
    def normalized(self,pos):return [float(np.clip((pos.x()-8)/max(1,self.width()-16),0,1)),float(np.clip((self.height()-8-pos.y())/max(1,self.height()-16),0,1))]
    def store(self,points):self.field.setText(';'.join(f'{x:.6f}:{y:.6f}' for x,y in points))
    def paintEvent(self,event):
        p=QPainter(self);p.fillRect(self.rect(),QColor('#24282b'));p.setPen(QColor('#555d65'));p.drawLine(self.screen([0,0]),self.screen([1,1]));p.setPen(QPen(QColor('#8ad5ed'),1.5));points=self.points();p.drawPolyline(QPolygonF([self.screen(v) for v in points]))
        for point in points:p.drawEllipse(self.screen(point),4,4)
    def mousePressEvent(self,event):
        points=self.points();distances=[(self.screen(p)-event.position()).manhattanLength() for p in points];closest=int(np.argmin(distances))
        if event.button()==Qt.RightButton:
            if distances[closest]<14 and 0<closest<len(points)-1:points.pop(closest);self.store(points)
            return
        if event.button()!=Qt.LeftButton:return
        if distances[closest]<14:self.drag=closest
        else:
            point=self.normalized(event.position())
            if not .00001<point[0]<.99999 or any(abs(p[0]-point[0])<.00001 for p in points):return
            points.append(point);points.sort();self.drag=points.index(point);self.store(points);self.dragged.emit()
    def mouseMoveEvent(self,event):
        if self.drag is None:return
        points=self.points();i=self.drag;point=self.normalized(event.position())
        point[0]=points[i][0] if i in (0,len(points)-1) else float(np.clip(point[0],points[i-1][0]+.00001,points[i+1][0]-.00001))
        points[i]=point;self.store(points);self.dragged.emit()
    def mouseReleaseEvent(self,event):
        if self.drag is not None and event.button()==Qt.LeftButton:
            self.drag=None
            self.drag_finished.emit()

class BasePanel(QWidget):
    def __init__(self,window,key):
        super().__init__();self.window=window;self.key=key;self.tr=window.trtext;self.layout=QVBoxLayout(self);self.fields={};self.guard=False
        try:self.saved=json.loads(window.settings.value('process_options/native_'+key,'{}'))
        except (TypeError,ValueError):self.saved={}
        if not isinstance(self.saved,dict):self.saved={}
        self.form=QFormLayout();self.form.setRowWrapPolicy(QFormLayout.WrapLongRows);self.layout.addLayout(self.form)
        self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    def row(self,label,field):
        from core.responsive import FormCaption
        caption=FormCaption(label);caption.setWordWrap(True);caption.setMinimumWidth(0);caption.setToolTip(label);self.form.addRow(caption,field)
    def note(self,ru,en):
        label=QLabel(self.tr(ru,en));label.setWordWrap(True);self.layout.addWidget(label);return label
    def number(self,key,ru,en,default,low,high,integer=False):
        field=QSpinBox() if integer else QDoubleSpinBox()
        if not integer:field.setDecimals(12)
        field.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
        field.setRange(low,high);field.setValue(self.saved.get(key,default));field.setToolTip(self.tr(ru,en));self.fields[key]=field;self.row(self.tr(ru,en),field);field.valueChanged.connect(self.save);return field
    def check(self,key,ru,en,default=False):
        field=QCheckBox(self.tr(ru,en));field.setChecked(self.saved.get(key,default));field.setToolTip(self.tr(ru,en));self.fields[key]=field;self.form.addRow(field);field.toggled.connect(self.save);return field
    def text(self,key,ru,en,default=''):
        field=QLineEdit(str(self.saved.get(key,default)));self.fields[key]=field;field.setToolTip(self.tr(ru,en));self.row(self.tr(ru,en),field);field.textChanged.connect(self.save);return field
    def button(self,ru,en,fn):
        button=QPushButton(self.tr(ru,en));button.clicked.connect(fn);button.setToolTip(button.text());self.layout.addWidget(button);return button
    def values(self):
        return {key:field.isChecked() if isinstance(field,QCheckBox) else field.text() if isinstance(field,QLineEdit) else field.value() for key,field in self.fields.items()}
    def reset(self):
        self.cancel()
        defaults={'low':0,'high':1,'softness':.05,'sigma':5,'size':2,'radius':3,'invert':False,'formula':'I1','name':'PixelMath','prefix':'','suffix':'_processed','folder':''}
        for key,field in self.fields.items():
            value=defaults.get(key,0)
            if isinstance(field,QLineEdit):field.setText(str(value))
            elif isinstance(field,QCheckBox):field.setChecked(bool(value))
            else:field.setValue(value)
        if hasattr(self,'kind'):self.kind.setCurrentIndex(0)
        if hasattr(self,'steps'):self.steps=[];self.refresh_steps()
        self.save()
    def save(self,*args):
        if not self.guard:self.window.settings.setValue('process_options/native_'+self.key,json.dumps(self.values()))
    def target(self):
        source=self.window.mdi.activeSubWindow();record=self.window.documents.get(source)
        if record is None:QMessageBox.information(self,'Astra',self.tr('Сначала откройте фото.','Open an image first.'))
        return source,record
    def has_preview(self):
        dialog=getattr(self,'temporary_preview',None)
        return dialog is not None and getattr(dialog,'tool_owner',None) is self and dialog.isVisible()
    def preview_tone(self):
        source=self.window.mdi.activeSubWindow()
        inline=self.key=='histogram' and self.quick_histogram
        if not inline:
            if not self.has_preview() or self.temporary_preview.source_window is not source:return
            dialog=self.temporary_preview
        record=self.window.documents.get(source)
        if record is None:return
        data=record['data']
        history=record['history']
        input_entry=history.entries[history.index]
        if self.key=='histogram' and self.quick_histogram:
            _,baseline=self.quick_stretch_state(record)
            input_entry=history.entries[baseline]
        if self.key=='curves' and self.window.guided_action.isChecked():
            guided=self.window.guided_panel
            if guided.route[guided.current]['tool']=='native:curves':
                anchor=guided.step_anchor(guided.current)
                if anchor is not None and anchor[0]<=history.index:input_entry=anchor[1][0]
        cache=getattr(self,'tone_cache',None)
        mask=record.get('mask') if record.get('mask_enabled') else None
        full_resolution=(self.key=='histogram' and not
                         self.window.settings.value('preview/low_resolution',False,type=bool))
        try:
            if cache is None or cache[0] is not data or cache[1] is not input_entry or cache[5]!=full_resolution:
                original=data if input_entry is history.entries[history.index] else np.load(input_entry['path'],mmap_mode='r',allow_pickle=False)
                step=1 if full_resolution else max(1,int(np.ceil(max(original.shape[:2])/384)))
                sample=original if full_resolution else np.array(original[::step,::step])
                prepared=None
                if self.key=='curves':
                    from .curves_preview import prepare
                    existing=getattr(self,'curve_preview_cache',None)
                    if existing is not None and existing[0] is original:
                        prepared=(sample,sample,existing[2],existing[3],1)
                    else:prepared=prepare(sample)
                cache=(data,input_entry,sample,step,prepared,full_resolution)
                self.tone_cache=cache
            _,_,sample,step,prepared,_=cache
            sampled_mask=mask[::step,::step] if mask is not None else None
            if full_resolution:
                result=engine.apply_operation(sample,'histogram',self.values(),sampled_mask)
            elif prepared is None:
                result=engine.stretch_block(sample,self.values()['channels'])
                if sampled_mask is not None:
                    weight=sampled_mask if sample.ndim==2 else sampled_mask[...,None]
                    with np.errstate(invalid='ignore'):
                        result=np.where(weight==0,sample,np.where(weight==1,result,sample+(result-sample)*weight))
            else:
                from .curves_preview import render
                result=render(prepared,self.values(),sampled_mask)
        except (ValueError,OSError,MemoryError):
            return
        if inline:
            self.inline_stretch_source=source
            display=dict(record,preview_data=result,preview_owner=self,quality_mode=None,
                         preview_source_size=record['image'].source_size)
            self.window.render(document=source,display_record=display)
        else:
            if self.key=='histogram':dialog.full_resolution=full_resolution
            dialog.data=result
            dialog.render(dialog.image.source_size)

    def clear_inline_stretch(self):
        source=getattr(self,'inline_stretch_source',None)
        self.inline_stretch_source=None
        if source is not None and source in self.window.documents:
            self.window.render(document=source)

    def hideEvent(self,event):
        self.clear_inline_stretch()
        self.tone_cache=None
        super().hideEvent(event)

    def clear_preview(self):
        self.clear_inline_stretch()
        self.tone_cache=None
        dialog=getattr(self,'temporary_preview',None)
        if dialog is not None and getattr(dialog,'tool_owner',None) is self:dialog.close()
        for source,record in self.window.documents.items():
            if record.get('preview_owner') is self:
                record.pop('preview_data',None);record.pop('preview_owner',None)
                if source is self.window.mdi.activeSubWindow():self.window.activate_document(source);self.window.render()
        if getattr(self,'roi_source',None) in self.window.documents:
            view=self.window.documents[self.roi_source]['image'];view.crop_enabled=False;view.update()
    def cancel(self):
        if hasattr(self,'preview_timer'):self.preview_timer.stop()
        cancel(self.window);self.clear_preview()
    def preview_result(self,source,data,result):
        record=self.window.documents.get(source)
        if record is None or record['data'] is not data:raise ValueError(self.tr('Фото изменилось. Повторите действие.','Image changed. Please retry.'))
        from core.preview_window import show_preview
        display_range=(0.,1.) if self.key in ('mask','histogram') else None
        stretched=False if display_range is not None else None
        full_resolution=(self.key=='histogram' and not
                         self.window.settings.value('preview/low_resolution',False,type=bool))
        self.temporary_preview=show_preview(self.window,result,source.windowTitle(),stretched,source=source,
                                            display_range=display_range,full_resolution=full_resolution)
        self.temporary_preview.tool_owner=self

class ProcessingPanel(BasePanel):
    def __init__(self,window,key):
        super().__init__(window,key)
        self.quick_histogram=False
        if key=='histogram':
            self.channels=self.saved.get('channels',{'All':{'black':0,'white':1,'mid':.5,'curve':'0:0;1:1'}});self.current='All'
            self.channel=QComboBox()
            for code in ('All','R','G','B'):self.channel.addItem(self.tr('Общий','All') if code=='All' else code,code)
            self.form.addRow(self.tr('Канал','Channel'),self.channel)
            self.number('black','Чёрная точка (в единицах данных)','Black point (data units)',0,-1e30,1e30)
            self.number('white','Белая точка (в единицах данных)','White point (data units)',1,-1e30,1e30)
            self.number('mid','Полутона: 0.5 = без изменения','Midtones: 0.5 = identity',.5,.001,.999)
            self.text('curve','Кривая: x:y; x:y (0…1)','Curve: x:y; x:y (0…1)','0:0;1:1')
            self.plot=HistogramPlot();self.layout.addWidget(self.plot);self.channel.currentIndexChanged.connect(lambda:self.switch_channel(self.channel.currentData()))
            self.plot.setToolTip(self.tr('Колесо: масштаб от ближайшего края. Двойной щелчок: полный диапазон. Нижние маркеры: чёрная точка, полутона и белая точка.','Wheel: zoom from the nearest edge. Double click: full range. Bottom handles: black point, midtones and white point.'))
            self.curveplot=CurvePlot(self.fields['curve']);self.curveplot.setToolTip(self.tr('Клик добавляет узел; перетаскивание меняет кривую; правый клик удаляет узел.','Click adds a point; drag edits the curve; right-click removes a point.'));self.layout.addWidget(self.curveplot)
            refresh=self.button('Обновить гистограмму','Refresh histogram',lambda:self.load_histogram())
            set_range=self.button('Чёрная / белая по диапазону фото','Set black / white from image range',lambda:self.load_histogram(True))
            self.histogram_full_controls=(self.curveplot,refresh,set_range)
            self.switch_channel('All')
            self.auto_button=self.button('Авторастяжка','Auto stretch',self.toggle_auto);self.auto_button.setCheckable(True)
            self.auto_target=self.number('auto_target','Фон авторастяжки','Auto stretch background',DEFAULT_TARGET,.05,.5)
            self.auto_target.setToolTip(self.tr('Целевая яркость фона. Astra может снизить её, чтобы сохранить детали в светах.',
                                               'Target background brightness. Astra may lower it to preserve highlight detail.'))
            self.plot.panel=self;set_em_size(self.plot,'setMinimumHeight',9.6875)
            self.auto_before=None
            self.layout.removeWidget(self.plot);self.layout.insertWidget(0,self.plot)
            self.layout.removeWidget(self.auto_button);self.layout.insertWidget(0,self.auto_button)
            self.histogram_source=None
            self.histogram_active=True
            self.histogram_generation=0
            self.histogram_timer=QTimer(self)
            self.histogram_timer.setSingleShot(True)
            self.histogram_timer.timeout.connect(self.sync_histogram)
            self.histogram_timer.start(0)
            for name in ('black','white','mid'):
                self.fields[name].valueChanged.connect(lambda *_:self.plot.update())
            self.fields['curve'].textChanged.connect(lambda:self.plot.update())
        elif key=='defects':
            if self.saved.get('algorithm_version')!=2:self.saved.update(sigma=6,radius=2,iterations=1,algorithm_version=2)
            self.check('hot','Горячие пиксели','Hot pixels',True);self.check('cold','Холодные пиксели','Cold pixels',True)
            self.number('sigma','Порог отклонения, σ','Deviation threshold, sigma',6,2,50)
            self.number('radius','Радиус дефекта, пикс.','Defect radius, px',2,1,4,True)
            self.number('iterations','Проходы','Passes',1,1,3,True)
            self.sample_selecting=False;self.sample_pending=False;self.sample_rectangles=[]
            self.check('sample_auto','Автонастройка по рамкам','Auto settings from samples',True)
            self.fields['sample_auto'].toggled.connect(self.update_sample_controls)
            self.button('Добавить рамки образцов','Add sample rectangles',self.select_defect_sample)
            self.sample_list=QListWidget();set_em_size(self.sample_list,'setMaximumHeight',6.875);self.layout.addWidget(self.sample_list)
            self.button('Удалить выбранную рамку','Remove selected rectangle',self.remove_sample)
            self.button('Очистить рамки','Clear rectangles',self.clear_sample_selection)
            self.note('Добавьте до 20 рамок вокруг отдельных горячих и холодных дефектов. Подбор и исправление всего кадра начнутся по кнопке Применить. Размер рамки до 64×64 пикселей. Не выбирайте звёзды.','Add up to 20 tight rectangles around individual hot and cold defects. Apply fits the samples and corrects the whole image. Each rectangle is limited to 64×64 pixels. Do not select stars.')
            self.correction_status=self.note('','')
        else:
            self.check('neutral','Нейтрализация выбранного фона','Neutralize selected background',True)
            for key,ru,en in [('x','X области','Region X'),('y','Y области','Region Y'),('width','Ширина области','Region width'),('height','Высота области','Region height')]:self.number(key,ru,en,0,0,1000000,True)
            self.button('Выделить область фона мышью','Select background with mouse',self.select_region)
            self.button('Использовать выделенную область','Use selected region',self.use_region)
            for key,ru,en in [('red','Баланс R','R gain'),('green','Баланс G','G gain'),('blue','Баланс B','B gain')]:self.number(key,ru,en,1,.001,100)
            self.note('Нейтрализация добавляет постоянные поправки каналам по медиане выбранного фона. Баланс умножает каналы на коэффициенты и меняет цвет всего кадра. Диапазон не обрезается; отрицательные значения сохраняются. Область выбирайте без звёзд и туманности.','Neutralization adds constant channel offsets from the selected background median. Balance multiplies channels and changes the whole image color. No clipping; negative values remain. Select a region without stars or nebulosity.')
        if key not in ('curves','histogram'):
            self.note('Активная маска ограничивает обработку: белое изменяется, чёрное защищено.','An active mask limits processing: white changes, black is protected.')
        actions=QWidget();row=QHBoxLayout(actions);row.setContentsMargins(0,0,0,0)
        for ru,en,callback in [('Просмотр','Preview',lambda:self.execute(False)),('Применить','Apply',lambda:self.execute(True)),('Отмена','Cancel',self.cancel),('Сброс','Reset',self.reset)]:
            button=QPushButton(self.tr(ru,en));button.setToolTip(button.text());button.clicked.connect(callback);row.addWidget(button)
        actions.setObjectName('toolActions');self.layout.addWidget(actions)
        self.preview_timer=QTimer(self);self.preview_timer.setSingleShot(True);self.preview_timer.setInterval(350);self.preview_timer.timeout.connect(self.live_preview)
    def save(self,*args):
        if self.quick_histogram:
            if not self.guard:self.values();self.plot.update()
            return
        super().save(*args)
        if not self.guard and hasattr(self,'plot'):
            self.plot.update()
            if hasattr(self,'auto_button'):self.auto_button.setChecked(False)
        if not self.guard and hasattr(self,'preview_timer') and self.has_preview():self.preview_timer.start()
    def live_preview(self):
        from core.resources import heavy_job_running
        if heavy_job_running(self.window) or getattr(getattr(self,'plot',None),'drag',None) is not None:self.preview_timer.start();return
        if self.has_preview():self.execute(False)
    def values(self):
        if self.key=='defects':return {**super().values(),'algorithm_version':2,'sample_halo_fraction':self.saved.get('sample_halo_fraction',.03)}
        if self.key=='histogram' and hasattr(self,'channels'):
            values=super().values();values.pop('auto_target',None)
            if len(values)==4:self.channels[self.current]=values
            return {'channels':self.channels,'auto_target':self.fields['auto_target'].value() if 'auto_target' in self.fields else DEFAULT_TARGET}
        return super().values()
    def switch_channel(self,key):
        self.guard=True;self.current=key
        for name,field in self.fields.items():
            if name=='auto_target':continue
            value=self.channels.get(key,{}).get(name,{'black':0,'white':1,'mid':.5,'curve':'0:0;1:1'}[name])
            field.setText(value) if isinstance(field,QLineEdit) else field.setValue(value)
        self.guard=False;self.plot.channel=self.channel.currentIndex();self.plot.update()
        for name,ru,en in [('black','Чёрная точка','Black point'),('white','Белая точка','White point')]:
            caption=self.form.labelForField(self.fields[name]);caption.setText(self.tr(ru,en)+(' (0…1)' if key!='All' else self.tr(' (данные)',' (data units)')))
    def set_tool_mode(self,mode):
        if self.key!='histogram':return
        from core.tool_modes import ToolMode
        quick=mode==ToolMode.QUICK
        if self.quick_histogram==quick:return
        self.clear_inline_stretch()
        if quick:
            self.standard_channels=self.values()['channels']
            self.channels={}
        else:self.channels=self.standard_channels
        self.quick_histogram=quick
        for field in self.fields.values():self.form.setRowVisible(field,not quick)
        for widget in self.histogram_full_controls:widget.setVisible(not quick)
        self.auto_button.setChecked(False);self.auto_button.setCheckable(not quick)
        self.switch_channel(self.channel.currentData())
        self.plot.drag=None;self.plot.values=None;self.plot.views.clear();self.plot.update()
        self.histogram_generation+=1;self.histogram_timer.start(0)

    def toggle_auto(self):
        if self.quick_histogram:
            self.execute(True,quick_auto=True);return
        if not self.auto_button.isChecked():
            if self.auto_before is not None:self.channels=self.auto_before;self.switch_channel(self.current);self.save()
            self.execute(False);return
        source,record=self.target()
        if record is None:self.auto_button.setChecked(False);return
        self.values();before=json.loads(json.dumps(self.channels));data=record['data'];target=self.auto_target.value()
        def done(settings):
            self.auto_before=before;self.channels=settings['channels'];self.switch_channel('All');self.channel.setCurrentIndex(0);self.save();self.auto_button.setChecked(True);QTimer.singleShot(25,self,lambda:self.execute(False))
        if not launch(self.window,self.tr('Авторастяжка','Auto stretch'),lambda job:auto_settings(data,target),done,128*1024**2,quiet=True):self.auto_button.setChecked(False)

    def stop_histogram(self):
        self.histogram_active=False
        self.histogram_generation+=1
        self.histogram_timer.stop()
        self.histogram_source=None

    def showEvent(self,event):
        super().showEvent(event)
        if getattr(self,'histogram_active',False):self.histogram_timer.start(0)

    def sync_histogram(self):
        if not isValid(self) or not isValid(self.window) or not self.histogram_active or not self.isVisible():return
        preview_source=getattr(self,'inline_stretch_source',None)
        if preview_source is not None and preview_source is not self.window.mdi.activeSubWindow():
            self.clear_inline_stretch()
        if getattr(self.window,'project_io',False) or getattr(self.window,'_restoring_project',False):
            self.histogram_timer.start(200)
            return
        from core.resources import heavy_job_running
        record=self.window.documents.get(self.window.mdi.activeSubWindow())
        if record is None or (self.plot.values and self.histogram_source and self.histogram_source() is record['data']):return
        self.plot.values=None
        self.plot.update()
        queue=getattr(self.window,'task_queue',None)
        if heavy_job_running(self.window) or (queue is not None and (queue.pending or queue.dispatching)):
            self.histogram_timer.start(200)
        else:self.load_histogram()

    def load_histogram(self,set_range=False):
        if not isValid(self) or not isValid(self.window) or not self.histogram_active:return
        if getattr(self.window,'project_io',False) or getattr(self.window,'_restoring_project',False):return
        source,record=self.target()
        if record is None:return
        data=record['data'];quick=self.quick_histogram
        history=record['history'];entry=history.entries[history.index]
        quick_state,baseline=self.quick_stretch_state(record) if quick else (None,history.index)
        channels=json.loads(json.dumps(quick_state['channels'])) if quick_state else {}
        master=(channels if quick else self.values()['channels']).get('All',{}).copy()
        baseline_entry=history.entries[baseline]
        generation=self.histogram_generation+1
        def work(job):
            original=data if entry is baseline_entry else np.load(baseline_entry['path'],mmap_mode='r',allow_pickle=False)
            value=engine.histogram(original)
            if original.ndim==3:
                step=max(1,int(np.ceil(max(original.shape[:2])/1200)));raw=original[::step,::step]
                sample=engine.transfer(raw.astype(float),master)
                for i in range(3):
                    channel=sample[...,i];valid=channel[np.isfinite(channel)].ravel()
                    value['bins'][i+1]=np.histogram(valid,256,range=(0,1))[0].tolist()
            return value
        def done(value):
            if not isValid(self) or not isValid(self.plot) or not isValid(self.window):return
            if not self.histogram_active or self.histogram_generation!=generation:return
            active=self.window.documents.get(self.window.mdi.activeSubWindow())
            if active is None or active['data'] is not data:return
            if quick:
                self.channels=channels;self.switch_channel(self.channel.currentData());self.plot.drag=None
            self.plot.values=value
            if not quick or getattr(self,'histogram_input',None) is not baseline_entry:self.plot.views.clear()
            self.histogram_input=baseline_entry;self.plot.update()
            if set_range:
                self.channel.setCurrentIndex(0);self.fields['black'].setValue(value['low']);self.fields['white'].setValue(value['high'] if value['high']>value['low'] else value['low']+1)
        import weakref
        if launch(self.window,self.tr('Гистограмма','Histogram'),work,done,64*1024**2,quiet=True):
            self.histogram_generation=generation
            self.histogram_source=weakref.ref(data)
    def select_region(self):
        source,record=self.target()
        if record is not None:record['image'].crop_enabled=True;record['image'].crop_ratio=0;self.roi_source=source;record['image'].update()
    def select_defect_sample(self):
        from core.resources import heavy_job_running
        if heavy_job_running(self.window):return
        source,record=self.target()
        if record is None:return
        old=getattr(self,'sample_view',None)
        if old is not None:
            try:old.regionSelected.disconnect(self.collect_sample)
            except (RuntimeError,TypeError):pass
        if source is not getattr(self,'roi_source',None) or record['data'] is not getattr(self,'sample_data',None):self.clear_samples()
        self.clear_preview();self.roi_source=source;self.sample_data=record['data'];self.sample_view=record['image']
        self.sample_selecting=True;self.sample_view.crop_rect=None;self.sample_view.crop_ratio=0;self.sample_view.crop_enabled=True
        self.sample_view.setCursor(Qt.CrossCursor);self.sample_view.regionSelected.connect(self.collect_sample);self.sample_view.update()
    def sync_selection(self,active):
        view=getattr(self,'sample_view',None)
        if view is not None:
            if self.window.documents.get(getattr(self,'roi_source',None),{}).get('data') is not getattr(self,'sample_data',None):self.clear_samples()
            view.crop_enabled=bool(active and self.sample_selecting and self.window.mdi.activeSubWindow() is self.roi_source)
            view.sample_rects=[QRect(*r) for r in self.sample_rectangles] if active else []
            view.update()
    def collect_sample(self):
        from core.resources import heavy_job_running
        if heavy_job_running(self.window):return
        if not self.sample_selecting:return
        rect=self.sample_view.crop_rect
        if rect is None:return
        values=rect.getRect();self.sample_view.crop_rect=None
        if max(values[2:])>64 or len(self.sample_rectangles)>=20:
            QMessageBox.information(self,'Astra',self.tr('До 20 рамок, каждая до 64×64 пикселей.','Up to 20 rectangles, each at most 64×64 pixels.'));return
        self.sample_rectangles.append(values);self.refresh_samples()
    def refresh_samples(self):
        self.sample_list.clear()
        for i,(x,y,w,h) in enumerate(self.sample_rectangles,1):self.sample_list.addItem(f'{i}: ({x}, {y}) {w}×{h}')
        self.update_sample_controls()
        self.sync_selection(self.window.tool_panel.pages.currentWidget() is self.window.tool_panel.entries.get('native:defects',(None,None))[0])
    def remove_sample(self):
        from core.resources import heavy_job_running
        if heavy_job_running(self.window) or not self.sample_rectangles:return
        index=self.sample_list.currentRow()
        self.sample_rectangles.pop(index if index>=0 else -1);self.clear_preview();self.refresh_samples()
    def clear_samples(self):
        self.sample_rectangles=[];self.sample_selecting=False
        if hasattr(self,'sample_list'):self.sample_list.clear()
        view=getattr(self,'sample_view',None)
        if view is not None:view.sample_rects=[];view.crop_rect=None;view.crop_enabled=False;view.update()
        self.update_sample_controls()
    def update_sample_controls(self):
        automatic=bool(self.sample_rectangles and self.fields['sample_auto'].isChecked())
        for key in ('hot','cold','sigma','radius','iterations'):self.fields[key].setEnabled(not automatic)
    def clear_sample_selection(self):
        from core.resources import heavy_job_running
        if heavy_job_running(self.window):return
        self.clear_samples();self.clear_preview()
    def cancel(self):
        if self.key=='defects':self.clear_samples()
        super().cancel()
    def use_region(self):
        source,record=self.target()
        if record is None:return
        rect=record['image'].crop_rect
        if source is not getattr(self,'roi_source',None) or rect is None:QMessageBox.information(self,'Astra',self.tr('Сначала выделите область на этом фото.','Select a region on this image first.'));return
        for key,value in zip(('x','y','width','height'),rect.getRect()):self.fields[key].setValue(value)
        record['image'].crop_enabled=False;record['image'].update()
    @staticmethod
    def quick_stretch_state(record):
        history=record['history'];state=record.get('quick_stretch')
        if state and history.entries[history.index] is state['result']:
            for index,entry in enumerate(history.entries[:history.index]):
                if entry is state['input']:return state,index
        return None,history.index

    def execute(self,apply,*,quick_auto=False,quick_manual=False):
        source,record=self.target()
        if record is None:return
        data=record['data'];settings={} if quick_auto else json.loads(json.dumps(self.values()));mask=record.get('mask') if record.get('mask_enabled') else None;report={}
        quick=quick_auto or quick_manual
        if quick:
            from core.resources import heavy_job_running
            if heavy_job_running(self.window):
                if quick_manual:self.clear_inline_stretch()
                return
            guided=self.window.guided_panel;history=record['history'];entry=history.entries[history.index]
            state,baseline=self.quick_stretch_state(record)
            if quick_auto:
                if state and state['automatic']:return
                anchor=guided.step_anchor(guided.current)
                if state is None and anchor is not None and anchor[0]<=history.index:baseline=anchor[0]
            baseline_entry=history.entries[baseline]
        samples=list(self.sample_rectangles) if self.key=='defects' and source is getattr(self,'roi_source',None) and data is getattr(self,'sample_data',None) else []
        if samples:
            self.sample_selecting=False;self.sample_view.crop_enabled=False;self.sample_view.update()
        def done(result):
            if source not in self.window.documents or self.window.documents[source]['data'] is not data:raise ValueError(localize('Фото изменилось.'))
            if quick:
                if not self.quick_histogram or self.window.mdi.activeSubWindow() is not source:return
                self.inline_stretch_source=None
                self.window.history_go(source,baseline)
                if history.index!=baseline:return
            if self.key=='defects':
                self.correction_status.setText(report.get('message',''))
                if apply:self.clear_samples()
            if apply:
                self.clear_preview()
                if self.key=='histogram':
                    record['stretch']=False
                    if source is self.window.mdi.activeSubWindow():self.window.set_preview_stretch(False)
                self.window.apply_image_result(source,result,{'histogram':'HT','color':'CC','defects':'CPC'}[self.key])
                if quick:record['quick_stretch']=dict(result=history.entries[history.index],input=baseline_entry,
                                                      channels=report['channels'],automatic=quick_auto)
            else:self.preview_result(source,data,result)
        def work(job):
            if quick:
                original=data if baseline_entry is entry else np.load(baseline_entry['path'],mmap_mode='r',allow_pickle=False)
                options=auto_settings(original) if quick_auto else settings
                report['channels']=options['channels']
                return engine.apply_operation(original,'histogram',options,mask,job.isInterruptionRequested,job.progress.emit)
            if samples:
                if settings.get('sample_auto',True):
                    from .defect_templates import correct_from_samples
                    result,matched=correct_from_samples(data,samples,mask,job.isInterruptionRequested,job.progress.emit,job.note.emit)
                    report['matched']=matched['matches']
                else:
                    from .defect_sample import calibrate_many,repair_confirmed
                    fitted,reports=calibrate_many(data,samples,job.isInterruptionRequested)
                    result=data
                    for index,options in enumerate(fitted,1):
                        result=engine.apply_operation(result,'defects',options,mask,job.isInterruptionRequested,job.progress.emit)
                    result=repair_confirmed(data,result,samples,reports,mask,job.isInterruptionRequested)
            else:result=engine.apply_operation(data,self.key,settings,mask,job.isInterruptionRequested,job.progress.emit)
            if self.key=='defects':
                hot=cold=0
                for y in range(0,data.shape[0],128):
                    if job.isInterruptionRequested():raise InterruptedError(localize('Отменено'))
                    before=data[y:y+128];after=result[y:y+128];valid=np.isfinite(before)&np.isfinite(after)
                    down=valid&(after<before);up=valid&(after>before)
                    if data.ndim==3:down=down.any(axis=-1);up=up.any(axis=-1)
                    hot+=int(down.sum());cold+=int(up.sum())
                message=self.tr('Исправлено: горячих пикселей ','Corrected hot pixels: ')+str(hot)+self.tr(', холодных ',', cold pixels: ')+str(cold)
                if 'matched' in report:message+=self.tr('. Найдено похожих дефектов: ','. Similar defects found: ')+str(report['matched'])
                if hot+cold==0:message+=self.tr('. Ничего не обнаружено. Уменьшите порог или увеличьте размер дефекта; проверьте активную маску.','. Nothing detected. Lower the threshold or increase the defect radius; check the active mask.')
                report['message']=message;job.note.emit(message)
            return result
        title=self.tr('Авторастяжка','Auto stretch') if quick_auto else self.tr('Обработка','Processing')
        estimated=engine.operation_memory(data,self.key)
        if quick_auto:estimated+=128*1024**2
        started=launch(self.window,title,work,done,estimated,quiet=self.key=='histogram',details=settings or None)
        if quick_manual:
            if started:self.window.native_job.finished.connect(self.clear_inline_stretch)
            else:self.clear_inline_stretch()
    def reset(self):
        self.cancel()
        if self.key=='histogram':self.channels={};self.switch_channel(self.current);self.save()
        elif self.key=='defects':
            self.saved['sample_halo_fraction']=.03
            for key,field in self.fields.items():
                if isinstance(field,QCheckBox):field.setChecked(key!='bayer')
                else:field.setValue(6 if key=='sigma' else 2 if key=='radius' else 1)
            self.save()
        else:
            for key,field in self.fields.items():
                if isinstance(field,QCheckBox):field.setChecked(True)
                else:field.setValue(1 if key in ('red','green','blue') else 0)

class MaskPanel(BasePanel):
    def __init__(self,window):
        super().__init__(window,'mask');self.kind=QComboBox();self.kind.addItem(self.tr('Яркость','Luminance'),'luminance');self.kind.addItem(self.tr('Звёзды','Stars'),'stars');self.kind.setCurrentIndex(max(0,self.kind.findData(self.saved.get('kind','luminance'))));self.form.addRow(self.tr('Тип маски','Mask type'),self.kind);self.kind.currentIndexChanged.connect(self.save)
        for key,ru,en,default,low,high in [('low','Нижняя граница','Lower bound',0,-1e30,1e30),('high','Верхняя граница','Upper bound',1,-1e30,1e30),('softness','Плавность в единицах данных','Softness in data units',.05,0,1e30),('sigma','Порог звёзд, σ','Star threshold, sigma',5,1,30),('size','Размер выделения звезды','Star mask size',2,.1,20)]:self.number(key,ru,en,default,low,high)
        self.number('radius','Радиус поиска звёзд, пикс.','Star search radius, px',3,1,20,True);self.check('invert','Инвертировать при создании','Invert on creation')
        self.note('Маска 0…1. Белое разрешает изменение; чёрное защищает. Поддерживается гистограммой/кривыми и цветокалибровкой. Создание маски не меняет пиксели фото.','Mask range 0…1. White permits changes; black protects. Supported by histogram/curves and color calibration. Creating a mask leaves image pixels intact.')
        self.button('Создать маску','Create mask',self.create);self.button('Просмотр маски','View mask',self.preview);self.button('Вернуться к фото','Back to image',self.clear_preview)
        self.button('Инвертировать готовую маску','Invert existing mask',self.invert)
        self.button('Включить / отключить маску','Enable / disable mask',self.toggle);self.button('Маска отдельным изображением','Mask as separate image',self.export)
        self.button('Отменить вычисление','Cancel calculation',self.cancel);self.status=self.note('','')
    def sync_status(self):
        record=self.window.documents.get(self.window.mdi.activeSubWindow(),{})
        self.status.setText(self.tr('Нет маски','No mask') if record.get('mask') is None else self.tr('Маска включена','Mask enabled') if record.get('mask_enabled') else self.tr('Маска отключена','Mask disabled'))
    def values(self):return {**super().values(),'kind':self.kind.currentData()}
    def create(self):
        source,record=self.target()
        if record is None:return
        data=record['data'];settings=self.values()
        def done(result):
            if source not in self.window.documents or self.window.documents[source]['data'] is not data:raise ValueError(localize('Фото изменилось.'))
            record['mask']=result;record['mask_enabled']=True;self.status.setText(self.tr('Маска создана и включена.','Mask created and enabled.'))
        launch(self.window,self.tr('Создание маски','Create mask'),lambda job:engine.make_mask(data,settings,job.isInterruptionRequested),done,data.size*8*20 if settings.get('kind')=='stars' else engine.operation_memory(data,'histogram'))
    def preview(self):
        source,record=self.target()
        if record is not None and record.get('mask') is not None:self.preview_result(source,record['data'],record['mask'])
    def invert(self):
        source,record=self.target()
        if record is not None and record.get('mask') is not None:
            record['mask']=1-record['mask'];record['mask'][~np.isfinite(engine.luminance(record['data']))]=0;self.preview()
    def toggle(self):
        source,record=self.target()
        if record is not None and record.get('mask') is not None:record['mask_enabled']=not record.get('mask_enabled',False);self.status.setText(self.tr('Маска включена','Mask enabled') if record['mask_enabled'] else self.tr('Маска отключена','Mask disabled'))
    def export(self):
        source,record=self.target()
        if record is not None and record.get('mask') is not None:self.window.data=record['mask'].copy();self.window.count=None;self.window.next_image_title=source.windowTitle()+' · Mask';self.window.showimage()

def __getattr__(name):
    if name=='PixelMathPanel':
        from .pixelmath_ui import PixelMathPanel
        return PixelMathPanel
    raise AttributeError(name)
