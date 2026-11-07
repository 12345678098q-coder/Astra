"""Local ASTAP plate solving, with per-image WCS output."""
from core.i18n import localize
from pathlib import Path
import tempfile
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_scales
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QWidget,QVBoxLayout,QFormLayout,QLineEdit,QPushButton,QDoubleSpinBox,QSpinBox,QLabel,QFileDialog,QMessageBox
from core.resources import heavy_job_running,configure_external

def solution(header,shape):
    wcs=WCS(header).celestial
    if not wcs.has_celestial:raise ValueError(localize('Решение не содержит небесной системы координат WCS.'))
    center=wcs.pixel_to_world((shape[1]-1)/2,(shape[0]-1)/2)
    scale=proj_plane_pixel_scales(wcs)*3600
    north=wcs.pixel_to_world((shape[1]-1)/2,(shape[0]-1)/2+1)
    angle=center.position_angle(north).degree
    if not np.isfinite([center.ra.degree,center.dec.degree,*scale,angle]).all():raise ValueError(localize('Некорректное WCS-решение.'))
    return wcs.to_header(relax=True),localize('RA: {0}\nDec: {1}\nМасштаб: {2:.3f} × {3:.3f} ″/px\nУгол оси Y к северу: {4:.2f}°').format(center.ra.to_string(unit='hour', sep=':', precision=2), center.dec.to_string(sep=':', precision=1, alwayssign=True), scale[0], scale[1], angle)

class AstrometryPanel(QWidget):
    def __init__(self,window):
        super().__init__();self.window=window
        layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form)
        from .tool_updates import find_tool
        self.astap_status=QLabel();self.astap_status.setOpenExternalLinks(False)
        self.astap_status.linkActivated.connect(lambda _: (window.preferences(),self.update_astap_status()))
        layout.insertWidget(0,self.astap_status);self.update_astap_status()
        refresh=QPushButton(window.trtext('Обновить координаты','Update coordinates'))
        refresh.setProperty('astra_stay_in_form',True)
        refresh.clicked.connect(self.solve);layout.insertWidget(1,refresh)
        self.fields={}
        for key,title,default,low,high in [('ra',localize('RA, часы'),0.,0,24),('dec',localize('Dec, градусы'),0.,-90,90),('radius',localize('Радиус поиска, °'),180.,.1,180),('fov',localize('Высота поля, ° (0 = авто)'),0.,0,180),('downsample',localize('Уменьшение (0 = авто)'),0,0,4)]:
            field=QSpinBox() if key=='downsample' else QDoubleSpinBox();field.setRange(low,high);field.setValue(float(window.settings.value('astrometry/'+key,default)) if key!='downsample' else int(window.settings.value('astrometry/'+key,default)));form.addRow(title,field);self.fields[key]=field
            field.setToolTip({'ra':localize('Приблизительное прямое восхождение центра поля в часах, от 0 до 24.'),'dec':localize('Приблизительное склонение центра поля в градусах.'),'radius':localize('Область поиска вокруг заданных координат. 180° включает поиск по всему небу.'),'fov':localize('Высота кадра на небе в градусах. 0 включает автоматический подбор масштаба.'),'downsample':localize('Уменьшение изображения перед поиском звёзд. 0 - автоматический выбор ASTAP.')}[key])
            field.valueChanged.connect(self.save_settings)
        self.solve_button=QPushButton();self.solve_button.clicked.connect(self.solve);layout.addWidget(self.solve_button)
        window.mdi.subWindowActivated.connect(lambda _:self.update_solve_button())
        self.update_solve_button()
        cancel=QPushButton(localize('Отменить'));cancel.clicked.connect(self.cancel);layout.addWidget(cancel)
        reset=QPushButton(localize('По умолчанию'));reset.clicked.connect(self.reset);layout.addWidget(reset)
        from .annotations import AnnotationPanel
        self.annotations_panel=AnnotationPanel(window);layout.addWidget(self.annotations_panel)
        self.save_button=QPushButton(window.trtext('Сохранить фото','Save image'));self.save_button.setObjectName('astrometry_save_image')
        self.save_button.setToolTip(window.trtext('Сохранить выбранное изображение в FITS или TIFF. FITS сохраняет найденные координаты WCS. Для подписей используйте «Сохранить фото с подписями».','Save the selected image as FITS or TIFF. FITS includes solved WCS coordinates. Use Save annotated image to export labels.'))
        self.save_button.clicked.connect(self.save_image);layout.addWidget(self.save_button)
        self.result=QLabel('');self.result.setWordWrap(True);layout.addWidget(self.result)
    def save_image(self):
        source=self.window.mdi.activeSubWindow()
        if source not in self.window.documents:
            QMessageBox.information(self,'Astra',self.window.trtext('Сначала выберите изображение.','Select an image first.'));return
        self.window.activate_document(source);self.window.save()
    def reset(self):
        for key,field in self.fields.items():field.setValue(180 if key=='radius' else 0)
    def update_astap_status(self):
        from .tool_updates import find_tool
        configured=str(self.window.settings.value('astrometry/executable','')).strip()
        found=find_tool('astap',configured)
        self.astap_status.setText(self.window.trtext('ASTAP выбран: ','ASTAP selected: ')+str(found) if found and found.is_file() else self.window.trtext('ASTAP не выбран. <a href="settings">Открыть настройки</a>','ASTAP not selected. <a href="settings">Open settings</a>'))
    def update_solve_button(self):
        source=self.window.mdi.activeSubWindow()
        solved=bool(self.window.documents.get(source,{}).get('wcs_header'))
        self.solve_button.setText(self.window.trtext('Обновить координаты','Update coordinates') if solved else self.window.trtext('Определить координаты','Solve coordinates'))
    def save_settings(self):
        for key,field in self.fields.items():self.window.settings.setValue('astrometry/'+key,field.value())
    def cancel(self):
        proc=getattr(self.window,'astrometry_process',None)
        if proc is not None and proc.state()!=QProcess.NotRunning:proc.kill()
    def solve(self):
        w=self.window;source=w.mdi.activeSubWindow()
        if heavy_job_running(w):QMessageBox.information(self,'Astra',localize('Дождитесь завершения текущей обработки.'));return
        if source not in w.documents:return
        from .tool_updates import find_tool
        exe=find_tool('astap',str(w.settings.value('astrometry/executable','')).strip());self.update_astap_status()
        if getattr(w,'tool_update_job',None) and w.tool_update_job.isRunning():QMessageBox.information(self,'ASTAP',localize('Дождитесь завершения обновления инструментов.'));return
        if not exe or not exe.is_file():QMessageBox.information(self,'ASTAP',localize('Установите ASTAP и звёздный каталог с hnsky.org/astap.htm, затем выберите astap.exe.'));return
        data=w.documents[source]['data'];proc=QProcess(w)
        try:
            plan=configure_external(proc,data.nbytes);folder=tempfile.TemporaryDirectory(prefix='astra-astrometry-');path=Path(folder.name)/'image.fits'
            mono=np.mean(data,axis=-1,dtype=np.float32) if data.ndim==3 else data
            fits.writeto(path,mono,overwrite=True)
        except Exception as error:QMessageBox.warning(self,'ASTAP',str(error));return
        self.save_settings();v={key:field.value() for key,field in self.fields.items()}
        args=['-f',str(path),'-ra',str(v['ra']),'-spd',str(v['dec']+90),'-r',str(v['radius']),'-fov',str(v['fov']),'-z',str(v['downsample']),'-wcs']
        from .astap_updates import HOME
        if (HOME/'catalog/installed.json').is_file():args+=['-d',str(HOME/'catalog')]
        w.astrometry_process=proc;w.log_overlay.begin(localize('Астрометрия · ASTAP'));w.log_overlay.append(plan.description());self.result.setText(localize('Выполняется решение…'))
        proc.setProcessChannelMode(QProcess.MergedChannels);proc.readyReadStandardOutput.connect(lambda:w.log_overlay.append(bytes(proc.readAllStandardOutput()).decode(errors='replace')))
        done=[False]
        def finish(code=1,*unused):
            if done[0]:return
            done[0]=True
            try:
                if proc.property('astra_cancelled'):
                    self.result.setText(w.trtext('Обработка отменена','Processing cancelled'));return
                if code!=0 or not path.with_suffix('.wcs').exists():raise ValueError(localize('Решение не найдено или обработка отменена. Проверьте каталог, высоту поля и журнал.'))
                header,text=solution(fits.getheader(path.with_suffix('.wcs')),data.shape)
                if source not in w.documents or w.documents[source]['data'] is not data:raise ValueError(localize('Исходное фото изменилось. Повторите решение.'))
                w.documents[source]['wcs_header']=header;self.result.setText(source.windowTitle()+'\n'+text);w.log_overlay.append(text);self.update_solve_button()
            except Exception as error:self.result.setText(str(error));w.log_overlay.append(str(error))
            finally:folder.cleanup();w.log_overlay.end();w.astrometry_process=None;proc.deleteLater()
        proc.finished.connect(finish);proc.errorOccurred.connect(lambda error:finish() if error==QProcess.FailedToStart else None)
        proc.start(str(exe),args)
