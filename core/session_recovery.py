"""Crash recovery via atomic background project snapshots and per-instance locks.

History files are pinned with hard links before the worker starts: branching or
closing a document cannot remove a snapshot that is being written.
"""
import copy
import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtCore import QObject,QTimer,QLockFile,QStandardPaths
from PySide6.QtWidgets import QMessageBox
from .project import save_archive,load_archive
from .project_ui import ProjectJob
from .resources import heavy_job_running


def ask_restore(owner):
    tr=owner.trtext
    dialog=QMessageBox(QMessageBox.Question,tr('Восстановление сеанса','Session recovery'),
        tr('Найден сеанс после аварийного завершения. Восстановить окна, инструменты и историю? Последние изменения после автосохранения могут отсутствовать.',
           'A session from an unexpected shutdown was found. Restore windows, tools and history? Changes after the last autosave may be missing.'),
        QMessageBox.Yes|QMessageBox.Cancel,owner)
    dialog.button(QMessageBox.Yes).setText(tr('Восстановить','Restore'))
    dialog.button(QMessageBox.Cancel).setText(tr('Отмена','Cancel'))
    dialog.setDefaultButton(QMessageBox.Yes);dialog.setEscapeButton(QMessageBox.Cancel)
    return dialog.exec()


def freeze_records(records):
    folder=tempfile.TemporaryDirectory(prefix='astra-recovery-pin-')
    frozen=[]
    try:
        for record in records:
            history=record['history'];entries=[]
            for entry in history.entries:
                item=dict(entry)
                for key in ('path','count_path'):
                    if entry[key] is not None:
                        target=Path(folder.name)/(uuid.uuid4().hex+'.npy')
                        os.link(entry[key],target);item[key]=target
                entries.append(item)
            frozen.append({**record,'history':SimpleNamespace(entries=entries,index=history.index)})
        return folder,frozen
    except Exception:
        folder.cleanup();raise


class SessionRecovery(QObject):
    def __init__(self,owner,root=None):
        super().__init__(owner);self.owner=owner;self.job=None;self.fingerprint=None;self.closing=False;self.claimed=[]
        base=Path(os.environ.get('LOCALAPPDATA') or QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation))
        self.root=Path(root) if root is not None else base/'Astra'/'recovery'
        self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/(uuid.uuid4().hex+'.astra')
        self.lock=QLockFile(str(self.path.with_suffix('.lock')));self.lock.setStaleLockTime(0)
        if not self.lock.tryLock(0):raise OSError('Recovery session lock unavailable')
        self.timer=QTimer(self);self.timer.setInterval(60000);self.timer.timeout.connect(self.checkpoint);self.timer.start()

    def offer_restore(self):
        for path in sorted(self.root.glob('*.astra'),key=lambda p:p.stat().st_mtime,reverse=True):
            if path==self.path:continue
            lock=QLockFile(str(path.with_suffix('.lock')));lock.setStaleLockTime(0)
            if not lock.tryLock(0):continue  # Another running Astra owns this session.
            tr=self.owner.trtext
            answer=ask_restore(self.owner)
            if answer==QMessageBox.No:
                path.unlink(missing_ok=True);lock.unlock();continue
            if answer==QMessageBox.Cancel:lock.unlock();break
            loaded=[]
            try:
                manifest,loaded=self.owner.project_work(tr('Восстановление сеанса','Restoring session'),lambda progress:load_archive(path,progress))
                self.owner.restore_project(manifest,loaded)
                saved_path=manifest.get('recovery_project_path')
                if saved_path:self.owner.project_path=saved_path
                self.claimed.append((path,lock));self.checkpoint();break
            except Exception as error:
                for record in loaded:
                    if not any(r['history'] is record['history'] for r in self.owner.documents.values()):record['history'].close()
                lock.unlock();QMessageBox.warning(self.owner,tr('Восстановление сеанса','Session recovery'),str(error));break

    def checkpoint(self):
        owner=self.owner
        if self.closing or self.job is not None or getattr(owner,'project_io',False) or heavy_job_running(owner):return
        # Empty sessions still contain tool and stacking settings.
        pins=None
        try:
            manifest,records=owner.capture_project()
            manifest['recovery_project_path']=str(getattr(owner,'project_path','') or '')
            identity=[(id(r['data']),id(r.get('mask')),[(str(e['path']),e['label'],e.get('token'),e.get('link_id')) for e in r['history'].entries]) for r in records]
            fingerprint=hashlib.sha256(json.dumps([manifest,identity],ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
            if fingerprint==self.fingerprint:return
            manifest=copy.deepcopy(manifest);pins,frozen=freeze_records(records)
            job=ProjectJob(lambda progress:save_archive(self.path,manifest,frozen,progress),owner)
            self.job=job
            def finished():
                pins.cleanup();self.job=None
                if job.error:
                    owner.statusBar().showMessage(owner.trtext('Не удалось сохранить аварийный сеанс: ','Could not save recovery session: ')+str(job.error),10000)
                else:
                    self.fingerprint=fingerprint
                    for path,lock in self.claimed:path.unlink(missing_ok=True);lock.unlock()
                    self.claimed=[]
                job.deleteLater()
                if self.closing:owner.close()
            job.finished.connect(finished);job.start()
        except Exception as error:
            if pins is not None:pins.cleanup()
            owner.statusBar().showMessage(owner.trtext('Автовосстановление: ','Session recovery: ')+str(error),10000)

    def clean_close(self):
        self.closing=True;self.timer.stop()
        if self.job is not None:return False
        self.path.unlink(missing_ok=True);self.lock.unlock()
        for path,lock in self.claimed:path.unlink(missing_ok=True);lock.unlock()
        self.claimed=[]
        return True


def start_recovery(owner):
    try:
        owner.session_recovery=SessionRecovery(owner)
        QTimer.singleShot(0,owner.session_recovery.offer_restore)
        QTimer.singleShot(15000,owner.session_recovery.checkpoint)
    except OSError as error:
        owner.statusBar().showMessage(owner.trtext('Автовосстановление недоступно: ','Session recovery unavailable: ')+str(error),10000)
