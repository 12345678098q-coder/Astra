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
             or name.startswith('PaletteLab.')]
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
    finally:
        sys.meta_path.remove(finder)
    return len(keys)


def show_update_dialog(owner):
    from PySide6.QtWidgets import QMessageBox
    try:
        reload_tools(owner)
    except Exception as error:
        QMessageBox.warning(owner, 'Astra', str(error))
        return
    owner.statusBar().showMessage(owner.trtext(
        'Код инструментов перезагружен. Открытые фото и история сохранены.',
        'Tool code reloaded. Open images and history preserved.'), 8000)
