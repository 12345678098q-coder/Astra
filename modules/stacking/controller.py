from core.responsive import fit_screen
from core.i18n import localize
from PySide6.QtCore import Qt
from pathlib import Path
from core.resources import heavy_job_running
from PySide6.QtWidgets import *
from modules.stacking.workers import Job,FrameCheckJob
FILTER='Астроизображения (*.fit *.fits *.fts *.tif *.tiff *.xisf);;RAW фотоаппаратов и другие файлы (*.*)'

class StackControllerMixin:
    def run(self):
        if heavy_job_running(self):
            QMessageBox.information(self,localize('Ресурсы'),localize('Дождитесь завершения текущей обработки.')); return
        groups={n:[l.item(i).text() for i in range(l.count()) if l.item(i).data(Qt.UserRole) is not False] for n,l in self.lists.items()}
        if self.stack_options.get('selection_enabled'):
            import json
            from .quality import analyze_paths,rank_frames
            from processes.native.jobs import launch
            from PySide6.QtCore import QTimer
            try:review=json.loads(self.settings.value('stack/review','{}'))
            except (ValueError,TypeError):review={}
            if not isinstance(review,dict):review={}
            detection=dict(sigma=review.get('sigma',5),radius=review.get('radius',3));percent=self.stack_options.get('selection_percent',100);mode=self.bayer.currentData()
            if not hasattr(self,'light_quality_cache'):self.light_quality_cache={}
            def work(job):
                results=analyze_paths(groups['Lights'],mode,detection,self.light_quality_cache,job.isInterruptionRequested,job.progress.emit)
                selected,scores,reasons=rank_frames(groups['Lights'],results,percent,review.get('min_stars',5),review.get('max_fwhm',20),review.get('max_ecc',.8))
                return selected,scores,reasons,results
            outcome={}
            def done(value):outcome['value']=value
            if not launch(self,self.trtext('Анализ Light-кадров','Light frame analysis'),work,done):return
            job=self.native_job
            def analyzed():
                self.runbtn.setEnabled(True)
                if job.isInterruptionRequested() or job.property('astra_cancelled') or 'value' not in outcome:return
                selected,scores,reasons,results=outcome['value']
                reference=self.stack_reference_path()
                lights=self.lists['Lights']
                explicit=any(lights.item(i).text()==reference and lights.item(i).data(Qt.UserRole+3) for i in range(lights.count()))
                if explicit and reference not in selected:
                    QMessageBox.warning(self,'Astra',self.trtext('Опорный кадр исключён отбором. Выберите другой опорный кадр или измените настройки отбора.','The reference frame was rejected. Choose another reference or adjust frame selection.'));return
                if hasattr(self,'review_dialog'):self.review_dialog.results=results;self.review_dialog.refresh()
                report=[localize('Отбор: {0}/{1} ({2}% лучших пригодных)').format(len(selected), len(groups['Lights']), percent)]
                report += [localize('Исключён: {0}: {1}').format(Path(p).name, reason) for p,reason in reasons.items()]
                self.selection_report=report
                if len(selected)<2:
                    self.log_overlay.display();self.log_overlay.append('\n'.join(report));QMessageBox.warning(self,'Astra',self.trtext('После отбора осталось меньше двух кадров. Измените процент или пороги качества.','Fewer than two frames remain. Adjust the percentage or quality limits.'));return
                groups['Lights']=selected
                QTimer.singleShot(0,self,lambda:self.run_selected(groups,report))
            self.runbtn.setEnabled(False);job.finished.connect(analyzed);return
        self.run_selected(groups)

    def run_selected(self,groups,selection_report=None):
        folder=self.settings.value('stack/autosave_dir','')
        if not folder or not Path(folder).is_dir():
            folder=QFileDialog.getExistingDirectory(self,localize('Папка автосохранения сложенного фото'),str(folder))
            if not folder:return
            self.settings.setValue('stack/autosave_dir',folder)
        self.stack_autosave_dir=str(folder)
        self.progress_dialog=QDialog(self); self.progress_dialog.setWindowTitle(self.trtext('Сложение кадров','Stacking')); fit_screen(self.progress_dialog,0.484,0.389)
        progress_layout=QVBoxLayout(self.progress_dialog); self.phase_label=QLabel(self.trtext('Подготовка','Preparing')); progress_layout.addWidget(self.phase_label)
        self.progress_bar=QProgressBar(); self.progress_bar.setRange(0,0); progress_layout.addWidget(self.progress_bar)
        try:self.log.textChanged.disconnect(self.mirror_stack_log)
        except (RuntimeError,TypeError):pass
        self.log.setParent(self.progress_dialog); self.log.clear(); progress_layout.addWidget(self.log,1)
        if selection_report:self.log.appendPlainText('\n'.join(selection_report))
        self.apply_workspace_theme(); self.log_overlay.begin(self.trtext('Сложение кадров','Stacking'))
        self.log.textChanged.connect(self.mirror_stack_log)
        self._stack_mirrored_length=0
        self.mirror_stack_log()
        self.runbtn.setEnabled(False); self.job=FrameCheckJob(groups,self.master_paths())
        self.job.progress.connect(self.update_progress); self.job.error.connect(self.stack_error)
        result={}
        self.job.done.connect(lambda report:result.update(report))
        def checked():
            self.runbtn.setEnabled(True)
            if self.job.isInterruptionRequested() or self.job.property('astra_cancelled'):
                self.log_overlay.end(self.trtext('Сложение отменено','Stacking cancelled'));return
            if not result:self.log_overlay.end(); return
            if result['errors']:
                self.phase_label.setText(localize('Проверка не пройдена')); self.progress_bar.setRange(0,1); self.progress_bar.setValue(0)
                self.log.appendPlainText('\n'.join(result['errors']+result['dark_issues']))
                box=QMessageBox(QMessageBox.Warning,localize('Несовместимые кадры'),localize('Обнаружены несовместимые или нечитаемые кадры. Исправьте список файлов перед сложением.'),parent=self); box.setDetailedText('\n'.join(result['errors']+result['dark_issues'])); box.exec(); self.log_overlay.end(); return
            if result['dark_issues']:
                self.log.appendPlainText('\n'.join(result['dark_issues']))
                box=QMessageBox(QMessageBox.Warning,localize('Проверка дарков'),localize('Дарки несовместимы с light-кадрами или выдержку нельзя проверить. Продолжить без дарков?'),parent=self)
                box.setDetailedText('\n'.join(result['dark_issues'])); proceed=box.addButton(localize('Работать без дарков'),QMessageBox.AcceptRole); cancel=box.addButton(localize('Отмена'),QMessageBox.RejectRole); box.setDefaultButton(cancel); box.exec()
                if box.clickedButton()!=proceed:self.phase_label.setText(localize('Сложение отменено')); self.log_overlay.end(localize('Сложение отменено')); return
                groups['Darks']=[]; self.log.appendPlainText(localize('Продолжаем без дарков. Список файлов не изменён.'))
            else:self.log.appendPlainText(localize('Размеры кадров и совместимость калибровки проверены.'))
            self.start_stack(groups)
        self.job.finished.connect(checked); self.job.start()

    def start_stack(self,groups):
        reference=self.stack_reference_path()
        if reference in groups['Lights']:
            groups={**groups,'Lights':[reference]+[path for path in groups['Lights'] if path!=reference]}
        if len(groups['Lights'])<5 and self.stack_options['method'] in ('mad','sigma','winsorized'): self.log.appendPlainText(localize('Менее 5 lights: обычное среднее, без надёжной сигма-отбраковки.'))
        self.runbtn.setEnabled(False); self.job=Job(groups,{**self.stack_options,"bayer":self.bayer.currentData(),"master_paths":self.master_paths(),"autosave_dir":self.stack_autosave_dir,"frame_weights":{self.lists['Lights'].item(i).text():self.lists['Lights'].item(i).data(Qt.UserRole+2) or 1 for i in range(self.lists['Lights'].count())}}); self.job.note.connect(self.log.appendPlainText); self.job.progress.connect(self.update_progress); self.job.done.connect(self.finished); self.job.error.connect(self.stack_error); self.job.finished.connect(lambda:self.runbtn.setEnabled(True)); self.job.finished.connect(self.log_overlay.end); self.job.start()

    def mirror_stack_log(self):
        content=self.log.toPlainText(); old=getattr(self,'_stack_mirrored_length',0)
        if len(content)<old:old=0
        addition=content[old:].strip()
        if addition:self.log_overlay.append(addition)
        self._stack_mirrored_length=len(content)

    def update_progress(self,current,total,phase):
        self.log_overlay.set_progress(current,total,phase)
        self.phase_label.setText(phase); self.progress_bar.setRange(0,total); self.progress_bar.setValue(current)

    def stack_error(self,error):
        if self.job.isInterruptionRequested() or self.job.property('astra_cancelled'):
            self.log_overlay.end(self.trtext('Сложение отменено','Stacking cancelled'));return
        self.phase_label.setText(self.trtext('Ошибка','Error')); self.log.appendPlainText(error); self.progress_bar.setFormat(self.trtext('Ошибка','Error'))
        self.log_overlay.end()
        QMessageBox.warning(self,self.trtext('Ошибка стека','Stacking error'),error)

    def finished(self,result):
        if self.job.isInterruptionRequested() or self.job.property('astra_cancelled'):
            self.log_overlay.end(self.trtext('Сложение отменено','Stacking cancelled'));return
        self.phase_label.setText(self.trtext('Готово','Complete')); self.progress_bar.setRange(0,100); self.progress_bar.setValue(100)
        self.log_overlay.end(localize('Сложение завершено'))
        self.data,self.count=result; self.progress_dialog.hide(); self.module.hide(); self.showimage(); self.mdi.tileSubWindows(); self.mdi.setActiveSubWindow(self.viewwindow); self.render()

