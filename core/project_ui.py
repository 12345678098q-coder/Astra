"""Project commands and workspace restoration."""
from core.i18n import localize
import json
from pathlib import Path
from astropy.io import fits
from PySide6.QtCore import Qt,QThread,Signal,QByteArray,QPointF,QRect
from PySide6.QtWidgets import QFileDialog,QMessageBox,QProgressDialog,QListWidgetItem,QSplitter,QMdiArea,QLineEdit
from .resources import heavy_job_running
from .project import save_archive,load_archive

PREFIXES=('process_options/','crop/','astrometry/','stack/','quick/','annotation/')
KEYS=('tools/pinned','preview_auto','preview_target','stretch_strength','workspace_color','file_presets')

class ProjectJob(QThread):
    note=Signal(str)
    def __init__(self,callback,parent):super().__init__(parent);self.callback=callback;self.value=None;self.error=None
    def run(self):
        try:self.value=self.callback(self.note.emit)
        except Exception as error:self.error=error

class ProjectMixin:
    def project_busy(self):
        if heavy_job_running(self) or (getattr(self,'tool_update_job',None) and self.tool_update_job.isRunning()):
            QMessageBox.information(self,localize('Проект'),localize('Дождитесь завершения обработки или обновления.'));return True
        return False

    def project_work(self,title,callback):
        dialog=QProgressDialog(title,'',0,0,self);dialog.setWindowTitle(localize('Открытие...'));dialog.setCancelButton(None);dialog.setWindowModality(Qt.ApplicationModal);dialog.setMinimumDuration(0)
        job=ProjectJob(callback,self);job.note.connect(dialog.setLabelText);job.finished.connect(dialog.accept)
        self.project_io=True
        try:job.start();dialog.exec();job.wait();value,error=job.value,job.error
        finally:self.project_io=False;job.deleteLater()
        if error:raise error
        return value

    def capture_project(self):
        documents=[];records=[];windows=list(self.documents)
        for window,record in self.documents.items():
            image=record['image'];rect=window.normalGeometry() if window.isMaximized() or window.isMinimized() else window.geometry()
            documents.append({'title':window.windowTitle(),'index':record['history'].index,'geometry':[rect.x(),rect.y(),rect.width(),rect.height()],
                'channel':record.get('channel'),
                'view_group':record.get('view_group'),
                'preview_ranges':record.get('preview_ranges',{}),
                'reference_background_regions':record.get('reference_background_regions',{}),
                'reference_background_shape':record.get('reference_background_shape'),
                'graxpert_points':record.get('graxpert_points',[]),'graxpert_points_shape':record.get('graxpert_points_shape'),
                'visible':not window.isHidden(),'maximized':window.isMaximized(),'minimized':window.isMinimized(),
                'stretch':record['stretch'],'strength':record['strength'],'auto_stretch':record.get('auto_stretch',False),
                'scale':image.scale,'offset':[image.offset.x(),image.offset.y()],'fitted':image.fitted,
                'annotations':image.annotations,'annotation_options':image.annotation_options,'annotations_visible':image.annotations_visible,
                'crop':list(image.crop_rect.getRect()) if image.crop_rect else None,
                'nebula_samples':record.get('nebula_samples',[[],[],[],[]]),
                'split':record['history_panel'].parentWidget().sizes(),
                'wcs':record['wcs_header'].tostring() if record.get('wcs_header') is not None else None})
            records.append(record)
        settings={key:self.settings.value(key) for key in self.settings.allKeys() if key in KEYS or key.startswith(PREFIXES)}
        # Capture editable paths even if focus has not yet left the field.
        from processes.astrometry import AstrometryPanel
        for panel in self.tool_panel.findChildren(AstrometryPanel):settings['astrometry/executable']=panel.path.text().strip()
        stack={name:[{'path':lst.item(i).text(),'checked':bool(lst.item(i).data(Qt.UserRole)),'master':bool(lst.item(i).data(Qt.UserRole+1)),'weight':lst.item(i).data(Qt.UserRole+2) or 1,'reference':bool(lst.item(i).data(Qt.UserRole+3))} for i in range(lst.count())] for name,lst in self.lists.items()}
        manifest={'documents':documents,'settings':settings,'tools':list(self.tool_panel.entries),
            'selected_tool':next((key for key,(page,_) in self.tool_panel.entries.items() if page is self.tool_panel.pages.currentWidget()),None),
            'active':windows.index(self.mdi.activeSubWindow()) if self.mdi.activeSubWindow() in windows else None,
            'main_geometry':bytes(self.saveGeometry().toBase64()).decode(),'main_state':bytes(self.saveState().toBase64()).decode(),
            'history_visible':self.history_view_action.isChecked(),'tools_visible':not self.tools_dock.isHidden(),
            'tabbed':self.mdi.viewMode()==QMdiArea.TabbedView,
            'toolbar':[key for key,action in self.actions.items() if action in self.toolbar.actions()],
            'stack':stack,'stack_options':self.stack_options,'bayer':self.bayer.currentData(),
            'stack_category':self.categories.currentRow(),'stack_stretch':self.stack_stretch.value(),'stack_neutral':self.preview_neutral.isChecked(),
            'stack_rows':{name:table.currentRow() for name,table in self.tables.items()},
            'log_text':self.log_overlay.text.toPlainText(),'log_title':self.log_overlay.title.text(),'log_visible':self.log_overlay.isVisible(),
            'stack_log':self.log.toPlainText(),
            'module_geometry':bytes(self.module.saveGeometry().toBase64()).decode(),'module_visible':not self.module.isHidden()}
        nmb=getattr(self,'nebula_mask_module',None)
        if nmb is not None:manifest['nebula_mask_builder']={'visible':nmb.isVisible(),'geometry':bytes(nmb.saveGeometry().toBase64()).decode(),'target':windows.index(nmb.source) if nmb.source in windows else None,'class':nmb.classes.currentIndex()}
        return manifest,records

    def save_project(self,save_as=False):
        if self.project_busy():return
        path=getattr(self,'project_path',None)
        if save_as or not path:
            path,_=QFileDialog.getSaveFileName(self,self.trtext('Сохранить проект','Save project'),str(path or ''),localize('Проект Astra (*.astra)'))
        if not path:return
        if not str(path).lower().endswith('.astra'):path=str(path)+'.astra'
        try:
            manifest,documents=self.capture_project()
            self.project_work(localize('Сохранение проекта…'),lambda progress:save_archive(path,manifest,documents,progress))
            self._project_saved=True;self.project_path=str(path);self.statusBar().showMessage(localize('Проект сохранён: ')+str(path))
        except Exception as error:QMessageBox.warning(self,localize('Проект'),str(error))

    def open_project(self):
        if self.project_busy():return
        folder=str(self.settings.value('project/last_open_folder',''))
        path,_=QFileDialog.getOpenFileName(self,self.trtext('Открыть проект','Open project'),folder,localize('Проект Astra (*.astra)'))
        if not path:return
        self.settings.setValue('project/last_open_folder',str(Path(path).resolve().parent))
        if self.documents:
            answer=QMessageBox.question(self,localize('Проект'),localize('Сохранить текущий проект перед открытием другого?'),QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel)
            if answer==QMessageBox.Cancel:return
            if answer==QMessageBox.Save:
                # A cancelled/failed save must not discard the workspace.
                if not self.save_project_checked():return
        loaded=[]
        try:
            manifest,loaded=self.project_work(localize('Открытие проекта…'),lambda progress:load_archive(path,progress))
            self.restore_project(manifest,loaded);self.project_path=path
            missing=[entry['path'] for group in manifest.get('stack',{}).values() for entry in group if not Path(entry['path']).is_file()]
            self.statusBar().showMessage(localize('Проект открыт: ')+path)
            if missing:QMessageBox.information(self,localize('Проект'),localize('Восстановлены ссылки на кадры сложения. Не найдены файлы: {0}.\n').format(len(missing))+'\n'.join(missing[:10]))
        except Exception as error:
            for document in loaded:
                if not any(record['history'] is document['history'] for record in self.documents.values()):document['history'].close()
            QMessageBox.warning(self,localize('Проект'),str(error))

    def save_project_checked(self):
        self._project_saved=False;self.save_project();return self._project_saved

    def restore_project(self,manifest,loaded):
        self._restoring_project=True
        try:
            return self._restore_project(manifest,loaded)
        finally:
            self._restoring_project=False

    def _restore_project(self,manifest,loaded):
        self.checkpoint_selection={}
        old_windows=list(self.documents);created=[]
        try:
            for document in loaded:
                self.data=document['data'];self.count=document['count'];self.next_image_title=document['title'];self.showimage(tile=False)
                window=self.viewwindow;created.append(window);record=self.documents[window];record['history'].close()
                record.update({key:document[key] for key in ('history','data','count','strength','stretch','auto_stretch')})
                record['channel']=document.get('channel') if document.get('channel') in ('R','G','B') else None
                record['view_group']=document.get('view_group')
                record['preview_ranges']=document.get('preview_ranges',{})
                record['reference_background_regions']=document.get('reference_background_regions',{})
                record['reference_background_shape']=document.get('reference_background_shape')
                record['graxpert_points']=document.get('graxpert_points',[]);record['graxpert_points_shape']=document.get('graxpert_points_shape')
                if document.get('mask') is not None:record['mask']=document['mask'];record['mask_enabled']=document.get('mask_enabled',False)
                if document.get('wcs'):record['wcs_header']=fits.Header.fromstring(document['wcs'])
                self.activate_document(window);self.render()
        except Exception:
            for window in created:
                record=self.documents.pop(window);record['history'].close();self.mdi.removeSubWindow(window);window.deleteLater()
            if old_windows:self.mdi.setActiveSubWindow(old_windows[0]);self.activate_document(old_windows[0])
            raise
        if not created:
            self.data=None;self.count=None;self.image=self.empty_image;self.info=self.empty_info;self.viewwindow=self.empty_viewwindow
            self.activate_document(self.empty_viewwindow);self.target_label.setText(self.trtext('Активное изображение: -','Active image: -'))
        for window in old_windows:
            record=self.documents.pop(window);record['history'].close();self.mdi.removeSubWindow(window);window.deleteLater()
        for key in list(self.tool_panel.entries):self.tool_panel.close_tool(key)
        for key in self.settings.allKeys():
            if key in KEYS or key.startswith(PREFIXES):self.settings.remove(key)
        for key,value in manifest.get('settings',{}).items():
            if key in KEYS or key.startswith(PREFIXES):self.settings.setValue(key,value)
        self.apply_workspace_theme();self.toolbar.clear()
        for key in manifest.get('toolbar',[]):
            if key in self.actions:self.toolbar.addAction(self.actions[key])
        self.restoreGeometry(QByteArray.fromBase64(manifest['main_geometry'].encode()));self.restoreState(QByteArray.fromBase64(manifest['main_state'].encode()))
        self.mdi.setViewMode(QMdiArea.TabbedView if manifest.get('tabbed') else QMdiArea.SubWindowView)
        self.history_view_action.setChecked(manifest.get('history_visible',True))
        for window,document in zip(created,loaded):
            window.showNormal();window.setGeometry(*document['geometry']);record=self.documents[window];record['history_panel'].parentWidget().setSizes(document['split'])
            record['nebula_samples']=document.get('nebula_samples',[[],[],[],[]])
            self.mdi.setActiveSubWindow(window);self.activate_document(window);self.render()
            image=record['image'];image.fitted=document['fitted']
            if image.fitted:image.fit_image()
            else:image.scale=document['scale'];image.offset=QPointF(*document['offset']);image.constrain_offset();image.update()
            image.annotations=document.get('annotations',[]);image.annotation_options=document.get('annotation_options',{});image.annotations_visible=document.get('annotations_visible',False);image.update()
            image.crop_rect=QRect(*document['crop']) if document.get('crop') else None
            if document.get('maximized'):window.showMaximized()
            elif document.get('minimized'):window.showMinimized()
            window.setVisible(document['visible'])
        active=manifest.get('active')
        if isinstance(active,int) and 0<=active<len(created):self.mdi.setActiveSubWindow(created[active]);self.activate_document(created[active])
        if not created:self.data=None;self.count=None
        nmb_state=manifest.get('nebula_mask_builder')
        nmb=getattr(self,'nebula_mask_module',None)
        if nmb is not None:nmb.close();nmb.deleteLater();del self.nebula_mask_module
        if isinstance(nmb_state,dict):
            from modules.nebula_mask_builder.ui import NebulaMaskDialog
            nmb=NebulaMaskDialog(self);self.nebula_mask_module=nmb
            if nmb_state.get('geometry'):nmb.restoreGeometry(QByteArray.fromBase64(nmb_state['geometry'].encode()))
            index=nmb_state.get('target')
            if isinstance(index,int) and 0<=index<len(created):nmb.targets.setCurrentIndex(nmb.targets.findData(created[index]))
            nmb.classes.setCurrentIndex(nmb_state.get('class',0));nmb.setVisible(bool(nmb_state.get('visible')))
        for key in manifest.get('tools',[]):
            try:self.open_tool(key)
            except KeyError:continue
        selected=manifest.get('selected_tool')
        if selected in self.tool_panel.entries:self.open_tool(selected)
        self.tools_dock.setVisible(manifest.get('tools_visible',True))
        from modules.stacking.engine import DEFAULT_STACK_OPTIONS
        self.stack_options={**DEFAULT_STACK_OPTIONS,**manifest.get('stack_options',self.stack_options)};self.bayer.setCurrentIndex(max(0,self.bayer.findData(manifest.get('bayer','Моно'))))
        self.selection_check.blockSignals(True);self.selection_percent.blockSignals(True);self.selection_check.setChecked(self.stack_options['selection_enabled']);self.selection_percent.setValue(self.stack_options['selection_percent']);self.selection_percent.setEnabled(self.selection_check.isChecked());self.selection_check.blockSignals(False);self.selection_percent.blockSignals(False)
        self.settings.setValue('stack_options',json.dumps(self.stack_options))
        for name,lst in self.lists.items():
            lst.blockSignals(True);lst.clear()
            for entry in manifest.get('stack',{}).get(name,[]):
                item=QListWidgetItem(entry['path']);item.setData(Qt.UserRole,entry['checked']);item.setData(Qt.UserRole+1,entry['master']);item.setData(Qt.UserRole+2,entry.get('weight',1));item.setData(Qt.UserRole+3,entry.get('reference',False));lst.addItem(item)
            lst.blockSignals(False)
        self.refresh_presets();self.refresh_files()
        self.stack_stretch.setValue(manifest.get('stack_stretch',20));self.preview_neutral.setChecked(manifest.get('stack_neutral',True))
        self.categories.setCurrentRow(manifest.get('stack_category',0))
        for name,row in manifest.get('stack_rows',{}).items():
            if name in self.tables and 0<=row<self.tables[name].rowCount():self.tables[name].selectRow(row)
        self.select_preview()
        self.module.restoreGeometry(QByteArray.fromBase64(manifest['module_geometry'].encode()));self.module.setVisible(manifest.get('module_visible',False))
        self.log.setPlainText(manifest.get('stack_log',''))
        self.log_overlay.end();self.log_overlay.text.setPlainText(manifest.get('log_text',''));self.log_overlay.title.setText(manifest.get('log_title',localize('Журнал')))
        if manifest.get('log_visible'):self.log_overlay.display()
