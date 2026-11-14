"""Debounced user-driven application of tools in the guided workspace."""
from PySide6.QtCore import QObject, QEvent, QTimer
from PySide6.QtWidgets import (QApplication, QAbstractSpinBox, QComboBox,
    QAbstractSlider, QCheckBox, QLineEdit)
from shiboken6 import isValid
from core.resources import heavy_job_running


class GuidedApply(QObject):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel; self.owner = panel.owner
        self.identity = None; self.page = None; self.action = None
        self.footers = {}; self.last = None; self.pending = False; self.force = False
        self.restore = None
        self.invoking=False
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(650)
        self.timer.timeout.connect(self.flush)
        QApplication.instance().installEventFilter(self)

    def manual(self):
        key = self.panel.route[self.panel.current]['tool']
        form = self.owner.tool_panel.forms.get(key)
        from .tool_modes import profile_for,ToolMode
        profile=profile_for(key)
        values={k:form.fields[k].currentData() for k in profile.manual_when} if form is not None and profile.manual_when else {}
        return profile.needs_apply(ToolMode.QUICK,values)

    def configure(self):
        from processes.action_footer import AdaptiveFooter, RESET
        source = self.owner.mdi.activeSubWindow()
        step = self.panel.route[self.panel.current]
        page = self.owner.tool_panel.entries.get(step['tool'], (None,))[0]
        identity = (source, step['id'], step['tool'], page)
        if identity != self.identity:
            self.timer.stop(); self.pending = False; self.force = False; self.restore = None
            self.identity = identity; self.page = page; self.action = None; self.last = None
        if page is None: return
        footer = page.findChild(AdaptiveFooter)
        if footer is None: return
        histogram=step['tool']=='native:histogram'
        if footer not in self.footers:
            self.footers[footer] = [(b, b.text(), not b.isHidden()) for b in footer.controls]
            for button, text, _ in self.footers[footer]:
                if text in RESET: button.clicked.connect(lambda: self.schedule(True))
                if button.property('astraPrimaryAction'):
                    button.pressed.connect(lambda b=button:self.prepare_manual(b))
                    button.clicked.connect(lambda checked=False,b=button:self.manual_started(b))
        for button, text, _ in self.footers[footer]:
            primary = bool(button.property('astraPrimaryAction'))
            if primary and not histogram: self.action = button
            button.setVisible(not histogram and (text in RESET or primary))
            if text in RESET: button.setText(self.panel.tr('Сбросить', 'Reset'))
        footer.reflow()
        if self.last is None: self.last = self.fingerprint()

    def prepare_manual(self,button):
        if self.invoking or button is not self.action or heavy_job_running(self.owner):return
        self.timer.stop();self.pending=False;self.force=False
        self.last=self.fingerprint()
        source=self.owner.mdi.activeSubWindow();record=self.owner.documents.get(source)
        if record is None or self.identity[2]=='crop':return
        history=record['history'];previous=history.entries[history.index]
        anchor=self.panel.state()['anchors'].get(self.identity[1])
        if anchor is not None:
            index=next((i for i,e in enumerate(history.entries) if e is anchor[0]),None)
            if index is not None:self.owner.history_go(source,index)
        self.restore=(source,record['data'],previous)

    def manual_started(self,button):
        if self.invoking or button is not self.action:return
        self.pending=False;self.force=False;self.last=self.fingerprint()
        if self.restore is not None:self.timer.start(100)
        else:self.timer.stop()

    def detach(self):
        self.timer.stop(); self.pending = False; self.identity = None; self.page = None
        self.restore = None; self.force = False
        for footer, buttons in self.footers.items():
            if not isValid(footer): continue
            for button, text, visible in buttons:
                if isValid(button): button.setText(text); button.setVisible(visible)
            footer.reflow()
        self.footers.clear()

    def fingerprint(self):
        if self.page is None or not isValid(self.page): return None
        values = []
        for widget in self.page.findChildren(QObject):
            if isinstance(widget, QAbstractSpinBox): values.append(widget.text())
            elif isinstance(widget, QComboBox): values.append(widget.currentIndex())
            elif isinstance(widget, QAbstractSlider): values.append(widget.value())
            elif isinstance(widget, QCheckBox): values.append(widget.isChecked())
            elif isinstance(widget, QLineEdit): values.append(widget.text())
        record = self.owner.documents.get(self.owner.mdi.activeSubWindow())
        if record and self.panel.route[self.panel.current]['tool'] == 'crop':
            view = record['image']; rect = view.crop_rect
            values.append((rect.getRect() if rect is not None else None, view.crop_angle))
        if record and self.panel.route[self.panel.current]['tool'] == 'graxpert:background-extraction':
            values.append(record.get('graxpert_points', []))
        return repr(values)

    def eventFilter(self, obj, event):
        if not isValid(self.panel) or not isValid(self.owner): return False
        if self.page is None or not isValid(self.page) or not self.panel.isVisible(): return False
        if event.type() not in (QEvent.MouseButtonRelease, QEvent.KeyRelease, QEvent.Wheel): return False
        try:
            inside = obj is self.page or self.page.isAncestorOf(obj)
            record = self.owner.documents.get(self.owner.mdi.activeSubWindow())
            if record and self.panel.route[self.panel.current]['tool'] in ('crop','graxpert:background-extraction'):
                inside = inside or obj is record['image'] or record['image'].isAncestorOf(obj)
            if inside: self.schedule()
        except TypeError: pass  # Non-widget QObject events do not change tool parameters.
        return False

    def schedule(self, force=False):
        if not isValid(self.panel) or self.page is None or not self.panel.isVisible(): return
        if self.panel.route[self.panel.current]['tool'] in ('crop','native:histogram'):return
        from processes.quick_deconvolution import KEYS
        if self.panel.route[self.panel.current]['tool'] in KEYS:return
        self.pending = True; self.force = self.force or force; self.timer.start()
        if not self.manual(): self.panel.next.setEnabled(False)

    def flush(self):
        if not isValid(self.panel) or not self.panel.isVisible() or self.page is None or not isValid(self.page): return
        if self.owner.mdi.activeSubWindow() is not self.identity[0]: return
        if heavy_job_running(self.owner) or getattr(self.owner,'quick_deconv_pending',False): self.timer.start(250); return
        # A result can still be queued after its worker has stopped.
        job = getattr(self.owner, 'native_job', None)
        try:
            if job is not None and job.property('astra_result_pending'):
                self.timer.start(100); return
        except RuntimeError: pass
        if self.restore is not None:
            source, original, previous = self.restore; self.restore = None
            record = self.owner.documents.get(source)
            if record and record['data'] is original:
                history = record['history']
                index = next((i for i, e in enumerate(history.entries) if e is previous), None)
                if index is not None: self.owner.history_go(source, index)
            if not self.pending: self.last = self.fingerprint()
        if not self.pending: return
        value = self.fingerprint(); force = self.force
        self.pending = False; self.force = False
        if self.manual() or (not force and value == self.last): self.last = value; return
        if self.identity[2]=='crop':return
        self.last = value
        if self.action is None or not isValid(self.action) or not self.action.isEnabled(): return
        source = self.identity[0]; record = self.owner.documents.get(source)
        if record is None: return
        if self.identity[2] == 'graxpert:background-extraction':
            form = self.owner.tool_panel.forms[self.identity[2]]
            if form.fields['method'].currentData() == 'RBF' and len(record.get('graxpert_points', [])) < 6:
                return
        # Recompute a parameter adjustment from this step's input instead of
        # repeatedly sharpening/denoising an already processed result.
        history = record['history']; previous = history.entries[history.index]
        anchor = self.panel.state()['anchors'].get(self.identity[1])
        if anchor is not None and self.identity[2] != 'crop':
            index = next((i for i, e in enumerate(history.entries) if e is anchor[0]), None)
            if index is not None: self.owner.history_go(source, index)
        original = record['data']; self.restore = (source, original, previous)
        self.invoking=True
        try:self.action.click()
        finally:self.invoking=False
        self.timer.start(100)
