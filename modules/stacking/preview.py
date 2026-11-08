from core.i18n import localize
from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage,QPixmap
from PySide6.QtWidgets import *
from core.image_io import read,debayer
FILTER='Астроизображения (*.fit *.fits *.fts *.tif *.tiff *.xisf);;RAW фотоаппаратов и другие файлы (*.*)'

def neutral_preview_background(image):
    if image.ndim!=3:return image
    rgb=image[...,:3]
    valid=np.isfinite(rgb).all(axis=-1)
    if not valid.any():return image
    # Use the same low-intensity pixels in all channels to avoid selecting stars.
    level=np.mean(rgb,axis=-1)
    cutoff=np.percentile(level[valid],40)
    mask=valid & (level<=cutoff)
    background=np.median(rgb[mask],axis=0)
    return rgb-background+np.median(background)

class StackPreviewMixin:
    def open_motion_light(self):
        """Load full-resolution data, never the subsampled display buffer."""
        name=self.current_category();row=self.tables[name].currentRow()
        if name!='Lights' or row<0:
            QMessageBox.information(self,'Astra',self.trtext('Выберите light-кадр в списке.','Select a light frame in the list.'));return
        path=self.lists[name].item(row).text();mode=self.bayer.currentData()
        from processes.native.jobs import launch
        from core.resources import require_memory
        def work(job):
            data,metadata=read(path);require_memory(data.size*8*5+128*1024**2,localize('Смаз'))
            pattern=metadata.get('BAYERPAT','') if mode=='RAW фотоаппарата' else mode
            if mode=='RAW фотоаппарата' and pattern not in ('RGGB','BGGR','GRBG','GBRG'):raise ValueError(localize('Не определена Bayer-матрица.'))
            if data.ndim==2 and pattern in ('RGGB','BGGR','GRBG','GBRG'):data=debayer(data,pattern)
            return data
        def done(data):
            self.data=data;self.count=None;self.next_image_title=Path(path).name;self.showimage()
            self.module.hide();self.open_tool('native:motion')
            from processes.native.motion_ui import MotionPanel
            panel=self.tool_panel.entries['native:motion'][0].findChild(MotionPanel)
            for key,field in panel.fields.items():
                value=self.stack_options.get('motion_'+key)
                if value is not None:
                    if isinstance(field,QCheckBox):field.setChecked(value)
                    else:field.setValue(value)
            panel.status.setText(self.trtext('Открыт исходный light с выбранным дебаером. Мастер-кадры здесь не применялись.','Source light opened with the selected debayer. Calibration masters have not been applied here.'))
        launch(self,self.trtext('Открытие light-кадра','Opening light frame'),work,done,128*1024**2)

    def update_stack_stretch(self,value):
        self.stack_stretch_value.setText(str(value))
        if hasattr(self,'preview_source') and self.preview_source is not None:self.render_frame_preview()

    def select_preview(self):
        name=self.current_category(); table=self.tables[name]
        if table.rowCount():
            if table.currentRow()<0:table.selectRow(0)
            else:self.preview_file(name)
        else:
            self.preview_source=None
            if hasattr(self,'preview_pixmap'):del self.preview_pixmap
            self.stack_preview.clear(); self.stack_preview.setText(localize('Добавьте кадры для просмотра'))
            self.preview_info.setText(localize('Предпросмотр'))

    def preview_file(self,name):
        if name!=self.current_category():return
        row=self.tables[name].currentRow()
        if row<0 or row>=self.lists[name].count():return
        path=self.lists[name].item(row).text()
        try:
            # Release the previous preview before decoding another full frame.
            self.preview_source=None
            self.stack_preview.clear()
            a,metadata=read(path)
            if a.ndim==2:
                # Reduce by complete Bayer cells, preserving all four colour phases.
                step=max(1,int(np.ceil(max(a.shape)/2048)))
                ys=np.arange(0,a.shape[0]//2,step)*2; xs=np.arange(0,a.shape[1]//2,step)*2
                yy=np.column_stack((ys,ys+1)).ravel(); xx=np.column_stack((xs,xs+1)).ravel()
                a=a[np.ix_(yy,xx)].copy()
            else:
                step=max(1,int(np.ceil(max(a.shape[:2])/2048))); a=a[::step,::step].copy()
            self.preview_source=a; self.preview_metadata=metadata; self.preview_path=path
            self.render_frame_preview()
        except Exception as e:
            self.stack_preview.clear(); self.stack_preview.setText(str(e))

    def render_frame_preview(self,*args):
        if getattr(self,'preview_source',None) is None:return
        try:
            a=self.preview_source; mode=self.bayer.currentData(); pattern=mode
            if mode=='RAW фотоаппарата':
                pattern=str(self.preview_metadata.get('BAYERPAT','')).strip().upper()
                if not (self.preview_metadata.get('RAW_CAMERA') or self.preview_metadata.get('MASTER')):raise ValueError(localize('Для этого файла выберите Моно или Bayer-паттерн.'))
            if a.ndim==2 and pattern in ('RGGB','BGGR','GRBG','GBRG'): a=debayer(a,pattern)
            elif mode=='RAW фотоаппарата':raise ValueError(localize('Не удалось определить Bayer-паттерн RAW.'))
            if self.preview_neutral.isChecked():a=neutral_preview_background(a)
            finite=a[np.isfinite(a)]
            if not finite.size:raise ValueError(localize('Нет конечных значений пикселей.'))
            strength=self.stack_stretch.value()
            lo,hi=np.percentile(finite,[0.2,99.8])
            a=np.clip((a-lo)/max(float(hi-lo),1e-9),0,1)
            if strength:a=np.arcsinh(strength*a)/np.arcsinh(strength)
            if a.ndim==2:a=np.repeat(a[...,None],3,axis=2)
            a=np.ascontiguousarray(np.nan_to_num(a[...,:3])*255,dtype=np.uint8)
            q=QImage(a.data,a.shape[1],a.shape[0],a.strides[0],QImage.Format_RGB888).copy()
            self.preview_pixmap=QPixmap.fromImage(q)
            self.stack_preview.setPixmap(self.preview_pixmap)
            self.preview_info.setText(f'{Path(self.preview_path).name}\n{self.bayer.currentText()}'+(f' ({pattern})' if mode=='RAW фотоаппарата' else ''))
            self.preview_info.setToolTip(self.preview_path)
        except Exception as e:self.stack_preview.clear(); self.stack_preview.setText(str(e))

