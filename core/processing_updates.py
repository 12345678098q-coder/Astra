"""Reload processing code and recreate open tool panels for development."""
import importlib
import importlib.abc
import importlib.util
from pathlib import Path
import sys

# These objects are part of Window's inheritance or live background services.
KEEP = {'processes', 'processes.stretch', 'processes.starnet',
        'processes.starnet.ui', 'processes.external', 'processes.tool_settings',
        'processes.tool_updates', 'processes.tooltips'}


def reload_tools(owner):
    from core.resources import heavy_job_running
    if heavy_job_running(owner) or (getattr(owner, 'tool_update_job', None) and owner.tool_update_job.isRunning()):
        raise ValueError(owner.trtext('Дождитесь завершения обработки или обновления.', 'Wait for processing or updates to finish.'))
    root = Path(__file__).resolve().parents[1]
    names = [name for name in sys.modules
             if (name.startswith('processes.') and name not in KEEP)
             or name.startswith('PaletteLab.')
             or name in {'experiments.signal_booster.multiscale',
                         'experiments.signal_booster.contrast_response',
                         'experiments.signal_booster.gpu_backend'}]
    # Check source before touching live controls. Compile source directly to avoid
    # Python's timestamp/size bytecode cache missing rapid edits during testing.
    code = {}
    for name in names:
        module = sys.modules[name]
        filename = getattr(module, '__file__', None)
        if filename and Path(filename).suffix == '.py':
            code[name] = compile(Path(filename).read_bytes(), filename, 'exec')
    panel = owner.tool_panel
    keys = list(panel.entries)
    selected = next((key for key,(page,_) in panel.entries.items()
                     if page is panel.pages.currentWidget()), None)
    visible = owner.tools_dock.isVisible()
    guided = getattr(owner,'guided_panel',None)
    embedded = guided is not None and guided.embedded_panel is panel
    if embedded:guided.unmount_tools()
    for key in keys:
        panel.close_tool(key)
    for name in sorted(names, key=lambda name: name.count('.'), reverse=True):
        module = sys.modules.pop(name, None)
        parent, _, child = name.rpartition('.')
        parent_module = sys.modules.get(parent)
        if parent_module and getattr(parent_module, child, None) is module:
            delattr(parent_module, child)
    importlib.invalidate_caches()
    # A scoped finder ensures even same-second, same-size source edits are used.
    class FreshSource(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def find_spec(self, fullname, path=None, target=None):
            if fullname not in code:
                return None
            source = root.joinpath(*fullname.split('.'))
            filename = source / '__init__.py' if source.is_dir() else source.with_suffix('.py')
            return importlib.util.spec_from_file_location(fullname, filename, loader=self,
                submodule_search_locations=[str(source)] if source.is_dir() else None)
        def create_module(self, spec):
            return None
        def exec_module(self, module):
            exec(code[module.__name__], module.__dict__)
    finder = FreshSource()
    sys.meta_path.insert(0, finder)
    try:
        from processes.panel import ToolPanel
        replacement = ToolPanel(owner)
        owner.tools_dock.setWidget(replacement)
        owner.tool_panel = replacement
        owner.target_label = replacement.target
        replacement.sync_target()
        for key in keys:
            owner.open_tool(key)
        if selected:
            owner.open_tool(selected)
        owner.tools_dock.setVisible(visible)
        if embedded:guided.mount_tools();guided.refresh()
    finally:
        sys.meta_path.remove(finder)
    return len(keys)


def restart_session(owner):
    """Persist the live session before replacing the entire Python process."""
    import os
    import tempfile
    import subprocess
    import json
    import time
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox
    from core.project import save_archive
    from core.resources import heavy_job_running
    recovery=getattr(owner,'session_recovery',None)
    if (getattr(owner,'restart_pending',False) or heavy_job_running(owner) or getattr(owner,'project_io',False)
        or (getattr(owner,'tool_update_job',None) and owner.tool_update_job.isRunning())
        or (recovery is not None and recovery.job is not None)):
        QMessageBox.information(owner,'Astra',owner.trtext(
            'Дождитесь завершения обработки, обновления или автосохранения.',
            'Wait for processing, updates or autosave to finish.'))
        return
    path=None
    try:
        manifest,records=owner.capture_project()
        manifest['recovery_project_path']=str(getattr(owner,'project_path','') or '')
        descriptor,filename=tempfile.mkstemp(prefix='astra-restart-',suffix='.astra')
        os.close(descriptor);path=Path(filename)
        owner.project_work(owner.trtext('Сохранение сеанса перед перезапуском','Saving session before restart'),
            lambda progress:save_archive(path,manifest,records,progress))
        owner.settings.sync()
        executable=Path(sys.executable)
        if executable.name.lower()=='python.exe' and executable.with_name('pythonw.exe').exists():
            executable=executable.with_name('pythonw.exe')
        root=Path(__file__).resolve().parents[1]
        command=[str(executable)]
        if not getattr(sys,'frozen',False):command.append(str(getattr(owner,'restart_entrypoint',root/'app.py')))
        command+=['--restore-session',str(path)]
        process=subprocess.Popen(command,cwd=str(root),close_fds=True,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except Exception as error:
        if path is not None:path.unlink(missing_ok=True)
        QMessageBox.warning(owner,'Astra',str(error));return
    # Starting Python does not guarantee that the replacement has restored the
    # workspace. Keep the live histories until the new process acknowledges it.
    status_path=path.with_suffix('.status')
    enabled=owner.isEnabled();owner.setEnabled(False);owner.restart_pending=True
    owner.statusBar().showMessage(owner.trtext('Восстановление фото и историй в новом окне…',
                                               'Restoring images and histories in the new window…'))
    recovery_active=recovery is not None and recovery.timer.isActive()
    if recovery_active:recovery.timer.stop()
    timer=QTimer(owner);timer.setInterval(100);owner.restart_monitor=timer
    deadline=time.monotonic()+600
    def finish(error=None):
        timer.stop();timer.deleteLater();owner.restart_monitor=None
        owner.restart_pending=False;owner.setEnabled(enabled)
        try:status_path.unlink(missing_ok=True)
        except OSError:pass
        if error is not None:
            if recovery_active:recovery.timer.start()
            owner.statusBar().clearMessage()
            QMessageBox.warning(owner,'Astra',owner.trtext(
                'Не удалось перезапустить программу. Открытые фото и истории сохранены в текущем окне. Сеанс: ',
                'Could not restart. Open images and histories remain in this window. Session: ')+str(path)+'\n'+str(error))
            return
        owner.image_close_approved=True
        if not owner.close():
            owner.image_close_approved=False
            if recovery_active:recovery.timer.start()
    def check():
        try:
            if status_path.exists():
                status=json.loads(status_path.read_text(encoding='utf-8'))
                if status.get('ready'):finish()
                else:finish(status.get('error','Session restoration failed'))
            elif process.poll() is not None:
                finish(owner.trtext('Новый процесс завершился до восстановления сеанса.',
                                    'The new process exited before restoring the session.'))
            elif time.monotonic()>deadline:
                finish(owner.trtext('Не получено подтверждение восстановления сеанса.',
                                    'Session restoration was not acknowledged.'))
        except Exception as error:finish(error)
    timer.timeout.connect(check);timer.start()


def restore_restart_session(owner,filename):
    import json
    from core.project import load_archive
    from PySide6.QtWidgets import QMessageBox
    path=Path(filename)
    def report(status):
        target=path.with_suffix('.status');temporary=target.with_suffix('.status.partial')
        temporary.write_text(json.dumps(status,ensure_ascii=False),encoding='utf-8')
        temporary.replace(target)
    loaded=[]
    try:
        manifest,loaded=owner.project_work(owner.trtext('Восстановление сеанса','Restoring session'),
            lambda progress:load_archive(path,progress))
        owner.restore_project(manifest,loaded)
        records=list(owner.documents.values())
        if len(records)!=len(loaded) or any(record['history'] is not document['history']
                                           or record['history'].index!=document['index']
                                           or len(record['history'].entries)!=len(document['states'])
                                           for record,document in zip(records,loaded)):
            raise ValueError(owner.trtext('Фото или истории восстановлены не полностью.',
                                         'Images or histories were not fully restored.'))
        active=manifest.get('active')
        if isinstance(active,int) and 0<=active<len(records):
            window=list(owner.documents)[active]
            owner.mdi.setActiveSubWindow(window);owner.activate_document(window)
        owner.project_path=manifest.get('recovery_project_path') or None
        report({'ready':True})
        try:path.unlink(missing_ok=True)
        except OSError:pass
    except Exception as error:
        for record in loaded:
            if not any(r['history'] is record['history'] for r in owner.documents.values()):record['history'].close()
        try:report({'error':str(error)})
        except OSError:pass
        QMessageBox.warning(owner,'Astra',owner.trtext(
            'Не удалось восстановить сеанс. Сохранённый сеанс: ',
            'Could not restore session. Saved session: ')+str(path)+'\n'+str(error))


def show_update_dialog(owner):
    owner.restart_application()
