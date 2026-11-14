"""A configurable guided workspace over Astra's existing processing tools."""
from core.i18n import localize
import copy
import json

from PySide6.QtCore import Qt, QTimer, QEvent, QPointF, QRect, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QComboBox, QDockWidget, QDialog, QMenu, QFrame, QProgressBar,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QCheckBox,
    QSizePolicy, QVBoxLayout, QWidget, QMdiArea, QInputDialog, QGraphicsOpacityEffect)

from core.resources import heavy_job_running
from .guided_hints import HINTS_RU

QUICK_EXCLUDED_TOOLS = {'native:signal_booster'}

# Default processing stages for the guided workspace.
STAGES = [
    ('load', 'Открыть фото', 'Open photo', 'open',
     'Начните с готового сложенного кадра в FITS, XISF или TIFF.',
     'Start with a stacked FITS, XISF or TIFF image.'),
    ('crop', 'Кроп', 'Crop', 'crop',
     'Выберите рамку мышью. Обрезка выполнится, когда вы нажмёте «Продолжить».', 'Draw your frame. Cropping is applied when you select Continue.'),
    ('background', 'Коррекция фона', 'Background correction', 'graxpert:background-extraction',
     'Уберите неравномерную засветку неба.',
     'Remove uneven sky brightness.'),
    ('color', 'Цветокалибровка', 'Colour calibration', 'local:background',
     'Нейтрализуйте цвет фона RGB/LRGB. Для ручного баланса выберите цветокалибровку. Для SHO/HOO пропустите этот этап, чтобы сохранить палитру.',
     'Neutralize the RGB/LRGB background. Select colour calibration for manual balance. Skip for SHO/HOO to preserve the palette.'),
    ('detail', 'Деконволюция', 'Deconvolution', 'rcastro:bxt',
     'Уменьшите размытие деталей и звёзд. Выберите интенсивность обработки. Инструмент можно заменить в настройках быстрого режима.',
     'Reduce blur in details and stars. Choose the processing intensity. You can change the tool in quick mode settings.'),
    ('noise', 'Шумоподавление', 'Noise reduction', 'rcastro:nxt',
     'Сгладьте зернистость, сохраняя мелкие детали.',
     'Smooth the grain while retaining fine detail.'),
    ('stretch', 'Растяжение', 'Stretch', 'native:histogram',
     'Нажмите «Авторастяжка» в гистограмме.',
     'Use Auto stretch in the histogram.'),
    ('polish', 'Кривые', 'Curves', 'native:curves',
     'Настройте кривые и цвет. Добавьте шаги для палитры, отделения звёзд или локального контраста при необходимости.',
     'Adjust curves and colour. Add palette, star separation or local contrast steps as needed.'),
    ('export', 'Экспорт', 'Export', 'export',
     'Сохраните JPEG или PNG, чтобы поделиться фото. Для дальнейшей обработки сохраните исходное качество или проект с историей.',
     'Save a JPEG or PNG to share. To continue editing later, save full-quality data or a project with history.'),
]

# Recommendations are shortcuts to existing Astra tools, not new processing engines.
STAGE_TOOLS = {
    'load': ('open', 'native:palettes', 'native:star_alignment', 'native:analysis'),
    'crop': ('crop', 'native:edges'),
    'background': ('graxpert:background-extraction', 'native:reference_background'),
    'color': ('local:background', 'native:color'),
    'detail': ('rcastro:bxt', 'graxpert:deconv-obj', 'graxpert:deconv-stellar', 'native:motion'),
    'noise': ('rcastro:nxt', 'graxpert:denoising'),
    'stretch': ('native:histogram', 'stretch'),
    'polish': ('native:curves', 'native:palettes', 'native:narrowband', 'rcastro:sxt',
               'starnet', 'native:color', 'native:scnr', 'native:lhe', 'native:hdr',
               'native:mask', 'graxpert:denoising', 'rcastro:nxt'),
    'export': ('export', 'save', 'astrometry'),
}

# Processing intensity presets for Astra tools.
PROFILES = {
    'graxpert:background-extraction': ('smoothing', (.25, .5, .75)),
    'graxpert:denoising': ('strength', (.25, .5, .75)),
    'graxpert:deconv-obj': ('strength', (.25, .5, .75)),
    'graxpert:deconv-stellar': ('strength', (.25, .5, .75)),
    'rcastro:nxt': ('strength', (50, 75, 90)),
    'rcastro:bxt': ('sharpen_nonstellar', (.25, .5, .7)),
}


def default_route():
    return [dict(id=key, stage=key, tool=tool) for key, _, _, tool, _, _ in STAGES]


def validate_route(value, tools):
    if not isinstance(value, list) or not 1 <= len(value) <= 50:
        raise ValueError(localize('Число шагов должно быть от 1 до 50'))
    # Remove retired quick-mode tools from saved routes and presets without
    # discarding the user's other steps, names or ordering.
    value=[step for step in value if not isinstance(step,dict) or step.get('tool') not in QUICK_EXCLUDED_TOOLS]
    if not value:raise ValueError(localize('Нет шагов, поддерживаемых в быстром режиме'))
    ids = set()
    for step in value:
        if (not isinstance(step, dict) or not isinstance(step.get('id'), str)
                or step['id'] in ids or step.get('tool') not in tools
                or step.get('stage') not in {s[0] for s in STAGES} | {'custom'}):
            raise ValueError(localize('Некорректный шаг пошаговой обработки'))
        ids.add(step['id'])
        if 'title' in step and (not isinstance(step['title'],str) or not step['title'].strip() or len(step['title'])>160):
            raise ValueError(localize('Некорректное название шага'))
    return copy.deepcopy(value)


class GuidedPanel(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.tr = owner.trtext
        self.catalog = {key: localize(title) for key, (title, _, _) in owner.tool_entries().items()
                        if key not in QUICK_EXCLUDED_TOOLS}
        self.catalog.update(open=self.tr('Открыть изображение', 'Open image'),
                            export=self.tr('Экспорт', 'Export'), save=self.tr('Сохранить мастер', 'Save master'))
        try:
            self.route = validate_route(json.loads(owner.settings.value('guided/route', 'null')), self.catalog)
        except (ValueError, TypeError):
            self.route = default_route()
        self.current = 0
        self.states = {}  # Per-document UI state; never stores full-resolution copies.
        self.source = None
        self.empty_state = dict(index=0, marks={}, anchors={}, kind='linear')
        self.guard = False
        self.setObjectName('guidedPanel')
        self.setStyleSheet('''
            QLabel#guidedMuted {color:#aeb6c2;background:transparent;}
            QFrame#guidedPhoto {background:transparent;border:0;border-radius:0;}
            QFrame#guidedPhoto QLabel {background:transparent;border:0;}
            QPushButton#guidedPrimary {background:#5669ce;border:1px solid #7688ec;color:white;font-weight:600;}
            QPushButton#guidedPrimary:hover {background:#6579df;}
            QPushButton#guidedPrimary:disabled {background:#383e50;border-color:#454b5b;color:#9298aa;}
            QPushButton#guidedQuiet {background:transparent;border:0;color:#b8c3d6;text-align:left;}
            QPushButton#guidedQuiet:hover {color:#e3eaff;background:#3b414b;}
            QProgressBar {background:#414750;border:0;border-radius:2px;}
            QProgressBar::chunk {background:#8799f3;border-radius:2px;}
        ''')
        layout = QVBoxLayout(self); layout.setContentsMargins(14,14,14,12); layout.setSpacing(10)
        header = QWidget(); header.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Maximum); header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0,0,0,0); header_layout.setSpacing(6)
        navigation = QHBoxLayout()
        self.step_counter = QLabel(); self.step_counter.setObjectName('guidedMuted')
        self.jump = QPushButton(self.tr('Все шаги', 'All steps')); self.jump.setObjectName('guidedQuiet')
        self.jump.clicked.connect(self.jump_menu)
        navigation.addWidget(self.step_counter,1); navigation.addWidget(self.jump); header_layout.addLayout(navigation)
        self.progress = QProgressBar(); self.progress.setTextVisible(False); self.progress.setFixedHeight(4)
        header_layout.addWidget(self.progress)
        self.step_title = QLabel(); self.step_title.setWordWrap(True)
        self.step_title.setObjectName('toolsHeading'); header_layout.addWidget(self.step_title)
        layout.addWidget(header)
        self.photo_choice=QComboBox();self.photo_choice.setToolTip(self.tr('Открытые фотографии', 'Open photos'))
        self.photo_choice.currentIndexChanged.connect(self.select_photo);layout.addWidget(self.photo_choice)

        # A single expanding body absorbs spare height. Its contents stay at
        # the top even when a step has no embedded tool (load / save).
        self.body = QWidget(); body = QVBoxLayout(self.body)
        body.setContentsMargins(0,0,0,0); body.setSpacing(10); body.setAlignment(Qt.AlignTop)
        self.body.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Ignored)
        layout.addWidget(self.body,1)
        self.hint = QLabel(); self.hint.setWordWrap(True); self.hint.setObjectName('guidedMuted')
        self.hint.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Maximum); body.addWidget(self.hint)
        self.photo_card = QFrame(); self.photo_card.setObjectName('guidedPhoto')
        self.photo_card.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Maximum)
        photo_layout = QVBoxLayout(self.photo_card); photo_layout.setContentsMargins(0,4,0,6); photo_layout.setSpacing(3)
        self.photo_caption = QLabel(self.tr('Ваша фотография', 'Your photo')); self.photo_caption.setObjectName('guidedMuted')
        photo_layout.addWidget(self.photo_caption)
        self.target = QLabel(); self.target.setTextFormat(Qt.PlainText); self.target.setWordWrap(True); photo_layout.addWidget(self.target)
        self.photo_info = QLabel(); self.photo_info.setObjectName('guidedMuted'); photo_layout.addWidget(self.photo_info)
        body.addWidget(self.photo_card)
        self.run = QPushButton(); self.run.setProperty('astraPrimaryAction',True); self.run.clicked.connect(self.open_tool); body.addWidget(self.run)
        self.landing = QWidget(); landing = QVBoxLayout(self.landing); landing.setContentsMargins(0,0,0,0); landing.setSpacing(6)
        self.master_button = QPushButton(self.tr('Сохранить в FITS/TIF…', 'Save as FITS/TIF…'))
        self.master_button.setToolTip(self.tr('FITS, XISF или TIFF для дальнейшей обработки.', 'FITS, XISF or TIFF for further processing.'))
        self.master_button.clicked.connect(owner.save); landing.addWidget(self.master_button)
        self.project_button = QPushButton(self.tr('Сохранить проект и историю…', 'Save project and history…'))
        self.project_button.clicked.connect(owner.save_project); landing.addWidget(self.project_button); body.addWidget(self.landing)

        self.options = QWidget(); options = QVBoxLayout(self.options)
        self.options.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Maximum)
        options.setContentsMargins(0,0,0,0); options.setSpacing(6); body.addWidget(self.options)
        self.kind_caption=QLabel(self.tr('Как подготовлено фото', 'How the photo was prepared'))
        options.addWidget(self.kind_caption)
        self.kind = QComboBox()
        for key, ru, en in [('linear', 'RGB', 'RGB'),
                            ('narrow', 'Узкополосный фильтр', 'Narrowband filter'),
                            ('stretched', 'Растянутое фото', 'Stretched photo')]:
            self.kind.addItem(self.tr(ru, en), key)
        self.kind.setToolTip(self.tr('Если вы ещё не растягивали сложенный кадр, оставьте первый вариант.',
                                     'Keep the first option if you have not stretched the stack yet.'))
        options.addWidget(self.kind)
        self.mode_settings=QDialog(self);self.mode_settings.setWindowTitle(self.tr('Настройки быстрого режима', 'Quick mode settings'))
        mode_root=QVBoxLayout(self.mode_settings)
        columns=QHBoxLayout();mode_root.addLayout(columns,1)
        mode_layout=QVBoxLayout();columns.addLayout(mode_layout,1)
        mode_layout.addWidget(QLabel(self.tr('Пояснения ко всем шагам', 'Guidance for all steps')))
        self.experience = QComboBox()
        self.experience.addItems([self.tr('Показывать подсказки', 'Show guidance'), self.tr('Только инструменты', 'Tools only')])
        self.experience.setCurrentIndex(int(owner.settings.value('guided/compact', 0)))
        mode_layout.addWidget(self.experience)
        self.engine_choices={}
        self.engine_options={
            'detail': [('graxpert:deconv-obj','GraXpert'),('rcastro:bxt','RC-Astro')],
            'noise': [('graxpert:denoising','GraXpert'),('rcastro:nxt','RC-Astro')]}
        for stage,ru,en in [('detail','Деконволюция','Deconvolution'),('noise','Шумоподавление','Noise reduction')]:
            mode_layout.addWidget(QLabel(self.tr(ru,en)))
            choice=QComboBox();self.engine_choices[stage]=choice
            mode_layout.addWidget(choice)
        # Keep the selection model for saved routes; editing lives in RouteEditor.
        self.tool = QComboBox(self);self.tool.hide()
        self.tool.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.tool.setMinimumContentsLength(12)
        self.choice_stage = None
        self.populate_tools()
        route_layout=QVBoxLayout();columns.addLayout(route_layout,2)
        route_layout.addWidget(QLabel(self.tr('Шаги обработки', 'Processing steps')))
        from .guided_route import RouteEditor
        self.route_editor=RouteEditor(self,self.mode_settings)
        route_layout.addWidget(self.route_editor,1)
        preset_row = QHBoxLayout()
        self.route_presets = QComboBox()
        self.load_route_presets()
        for ru,en,fn in [('Загрузить','Load',self.load_route_preset), ('Сохранить…','Save…',self.save_route_preset)]:
            button=QPushButton(self.tr(ru,en));button.clicked.connect(fn);preset_row.addWidget(button)
        mode_layout.addWidget(QLabel(self.tr('Пресеты быстрых настроек','Quick settings presets')))
        mode_layout.addWidget(self.route_presets)
        mode_layout.addLayout(preset_row)
        from .responsive import fit_screen
        fit_screen(self.mode_settings,.9,.88)
        self.mode_settings.resize(min(1180,self.mode_settings.width()),self.mode_settings.height())
        modes_note=QLabel(self.tr('Обычный режим – все настройки инструментов. Быстрый режим – сокращённый интерфейс и автоматическое применение.',
                                'Standard mode provides all tool settings. Quick mode uses a reduced interface and automatic application.'))
        modes_note.setWordWrap(True);mode_layout.addWidget(modes_note)
        mode_layout.addStretch(1)
        done=QPushButton(self.tr('Готово', 'Done'));done.setObjectName('guidedPrimary')
        done.clicked.connect(self.save_mode_settings);mode_root.addWidget(done)
        self.rgb_balance=QCheckBox(self.tr('Выравнивание каналов', 'Channel alignment'))
        self.rgb_balance.setToolTip(localize(HINTS_RU['load:channel_alignment']))
        self.rgb_balance.toggled.connect(self.balance_rgb);body.addWidget(self.rgb_balance)
        self.profiles = QWidget(); profiles = QHBoxLayout(self.profiles); profiles.setContentsMargins(0,0,0,0)
        for i, (ru, en) in enumerate((('Низкая', 'Low'), ('Средняя', 'Medium'), ('Высокая', 'High'))):
            button = QPushButton(self.tr(ru, en)); button.setToolTip(self.tr(
                'Изменить силу обработки. Результат применится автоматически.',
                'Change processing strength. The result is applied automatically.'))
            button.clicked.connect(lambda checked=False, index=i: self.set_profile(index)); profiles.addWidget(button)
        body.addWidget(self.profiles)
        self.tool_host = QWidget(); self.tool_layout = QVBoxLayout(self.tool_host)
        self.tool_host.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Ignored)
        self.tool_layout.setContentsMargins(0,0,0,0); body.addWidget(self.tool_host,1)
        self.rest_space = QWidget(); body.addWidget(self.rest_space,1)
        self.embedded_panel = None; self.presented = None
        footer = QWidget(); footer.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Maximum)
        footer_layout = QVBoxLayout(footer); footer_layout.setContentsMargins(0,0,0,0); footer_layout.setSpacing(6)
        self.status = QLabel(); self.status.setWordWrap(True); self.status.setObjectName('guidedMuted'); footer_layout.addWidget(self.status)
        self.before_hold=None
        self.previous_preview = QPushButton(self.tr('До', 'Before'))
        self.previous_preview.setToolTip(self.tr('Удерживайте, чтобы увидеть предыдущий шаг на фото.', 'Hold to view the previous step in the workspace.'))
        self.previous_preview.pressed.connect(self.preview_previous)
        self.previous_preview.released.connect(self.end_previous)
        owner.installEventFilter(self)
        footer_layout.addWidget(self.previous_preview)
        self.rollback = QPushButton(self.tr('Откатиться к шагу…', 'Return to step…'))
        self.rollback.clicked.connect(self.rollback_menu)
        footer_layout.addWidget(self.rollback)
        self.reset = QPushButton(self.tr('Отменить изменения шага', 'Undo changes in this step'))
        self.reset.setToolTip(self.tr('Вернуть фото к состоянию перед этим шагом.', 'Restore the photo to its state before this step.'))
        self.reset.setObjectName('guidedQuiet'); self.reset.clicked.connect(self.reset_step); footer_layout.addWidget(self.reset)
        self.next = QPushButton(self.tr('Продолжить →', 'Continue →')); self.next.setObjectName('guidedPrimary')
        self.next.clicked.connect(lambda: self.advance(False)); footer_layout.addWidget(self.next)
        row = QHBoxLayout()
        self.back = QPushButton(self.tr('Назад', 'Back')); self.back.clicked.connect(lambda: self.navigate(-1))
        self.skip = QPushButton(self.tr('Пропустить шаг', 'Skip this step')); self.skip.clicked.connect(lambda: self.advance(True))
        row.addWidget(self.back); row.addWidget(self.skip); footer_layout.addLayout(row)
        self.mode_settings_button=QPushButton(self.tr('Настройки быстрого режима', 'Quick mode settings'))
        self.mode_settings_button.setObjectName('guidedQuiet');self.mode_settings_button.clicked.connect(self.open_mode_settings)
        footer_layout.addWidget(self.mode_settings_button)
        exit_button = QPushButton(self.tr('Выйти из пошагового режима', 'Leave guided mode')); exit_button.setObjectName('guidedQuiet')
        exit_button.clicked.connect(lambda: owner.guided_action.setChecked(False)); footer_layout.addWidget(exit_button)
        layout.addWidget(footer)
        self.tool.currentIndexChanged.connect(self.change_tool)
        self.kind.currentIndexChanged.connect(self.change_kind)
        self.experience.currentIndexChanged.connect(self.change_experience)
        from .guided_apply import GuidedApply
        self.auto_apply = GuidedApply(self)
        self.timer = QTimer(self); self.timer.setInterval(250); self.timer.timeout.connect(self.sync); self.timer.start()
        self.refresh(); self.sync()

    def state(self):
        record = self.owner.documents.get(self.owner.mdi.activeSubWindow())
        if record is None: return self.empty_state
        # Key by history identity so closed documents can be removed without Qt wrapper access.
        return self.states.setdefault(record['history'], dict(index=0, marks={}, anchors={}, kind='linear'))

    def persist(self):
        self.owner.settings.setValue('guided/route', json.dumps(self.route))

    def select_photo(self):
        if heavy_job_running(self.owner):return
        source=self.photo_choice.currentData()
        if source in self.owner.documents:self.owner.mdi.setActiveSubWindow(source)

    def balance_rgb(self, enabled):
        owner=self.owner;source=owner.mdi.activeSubWindow();record=owner.documents.get(source)
        state=self.state()
        if heavy_job_running(owner) or record is None:
            self.sync();return
        if not enabled:
            anchor=state.get('rgb_anchor');history=record['history']
            index=next((i for i,e in enumerate(history.entries) if e is anchor),None)
            if index is None:self.sync();return
            if history.entries[history.index] is not state.get('rgb_result'):
                if QMessageBox.question(self,'Astra',self.tr(
                    'Отключение выравнивания вернёт фото к состоянию перед ним. Последующие изменения останутся в истории до новой обработки. Продолжить?',
                    'Disabling alignment restores the photo to its earlier state. Later edits remain in history until new processing. Continue?'))!=QMessageBox.Yes:
                    self.sync();return
            owner.history_go(source,index)
            if history.index==index:state['rgb_enabled']=False
            self.sync();return
        data=record['data']
        if data.ndim!=3 or data.shape[-1]!=3:self.sync();return
        from processes.native.jobs import launch
        from modules.stacking.background import neutralize_background
        import numpy as np
        anchor=record['history'].entries[record['history'].index]
        def work(job):
            result=np.array(data,dtype=np.result_type(data.dtype,np.float32),copy=True)
            neutralize_background(result,log=job.note.emit)
            return result
        def done(result):
            if source not in owner.documents or record['data'] is not data:
                raise ValueError(self.tr('Фото изменилось. Повторите выравнивание.', 'Photo changed. Repeat RGB alignment.'))
            owner.apply_image_result(source,result,self.tr('Выравнивание каналов','Channel alignment'))
            state.update(rgb_enabled=True,rgb_anchor=anchor,rgb_result=record['history'].entries[record['history'].index])
        state['rgb_pending']=True
        if launch(owner,self.tr('Выравнивание каналов','Channel alignment'),work,done,data.size*8+64*1024**2):
            def finished():
                state.pop('rgb_pending',None);self.sync()
            owner.native_job.finished.connect(finished)
        else:state.pop('rgb_pending',None)
        self.sync()

    def title(self, step):
        if step.get('title'):return step['title']
        stage = next((s for s in STAGES if s[0] == step['stage']), None)
        return self.tr(stage[1], stage[2]) if stage else self.catalog[step['tool']]

    def refresh(self):
        self.current = min(self.current, len(self.route)-1)
        self.state()['index'] = self.current
        self.guard = True
        self.populate_tools()
        self.tool.setCurrentIndex(self.tool.findData(self.route[self.current]['tool']))
        self.guard = False
        self.sync()

    def populate_tools(self):
        stage = self.route[self.current]['stage']
        if self.choice_stage == stage: return
        previous_guard = self.guard; self.guard = True; self.tool.clear()
        recommended = [key for key in STAGE_TOOLS.get(stage, ()) if key in self.catalog]
        for key in recommended: self.tool.addItem(self.catalog[key], key)
        if recommended: self.tool.insertSeparator(self.tool.count())
        for key, title in self.catalog.items():
            if key not in recommended: self.tool.addItem(title, key)
        self.choice_stage = stage; self.guard = previous_guard

    def jump_menu(self):
        if heavy_job_running(self.owner): return
        menu = QMenu(self)
        for index, step in enumerate(self.route):
            action = menu.addAction(f'{index+1}. {self.title(step)}')
            action.setCheckable(True); action.setChecked(index == self.current)
            action.triggered.connect(lambda checked=False, i=index: self.select(i))
        menu.exec(self.jump.mapToGlobal(self.jump.rect().bottomLeft()))

    def open_mode_settings(self):
        if heavy_job_running(self.owner): return
        self.route_editor.load()
        self.refresh_engine_choices()
        self.mode_settings.exec()

    def save_mode_settings(self):
        if heavy_job_running(self.owner):return
        self.route_editor.rename()
        for stage,choice in self.engine_choices.items():
            key=choice.currentData()
            if key is not None:
                for step in self.route_editor.route:
                    if step['stage']==stage:step['tool']=key
        self.apply_route(self.route_editor.route)
        self.mode_settings.accept()

    def apply_route(self, route):
        if heavy_job_running(self.owner): return
        route = validate_route(route, self.catalog)
        # Track stable step ids so reordering preserves each photo's position.
        for state in [self.empty_state, *self.states.values()]:
            old_id = self.route[min(state['index'], len(self.route)-1)]['id']
            state['index'] = next((i for i, step in enumerate(route) if step['id'] == old_id), 0)
            ids = {step['id'] for step in route}
            for key in ('marks', 'anchors'):
                state[key] = {k: v for k, v in state[key].items() if k in ids}
        self.route = route; self.current = self.state()['index']; self.choice_stage = None
        self.persist(); self.refresh()

    def set_profile(self, index):
        if heavy_job_running(self.owner) or index not in (0,1,2): return
        key = self.route[self.current]['tool']
        form = self.owner.tool_panel.forms.get(key)
        if key in PROFILES and form is not None:
            field, values = PROFILES[key]
            if key == 'rcastro:bxt':
                form.fields['auto_settings'].setChecked(False)
                form.fields['correct_only'].setChecked(False)
                form.fields['sharpen_stars'].setValue((.2,.5,.7)[index])
            if key == 'graxpert:background-extraction':
                form.fields['method'].setCurrentIndex(form.fields['method'].findData('AI'))
            form.fields[field].setValue(values[index])
            self.auto_apply.schedule(True)

    def select(self, index):
        if self.guard or not 0 <= index < len(self.route): return
        if heavy_job_running(self.owner): return
        self.current = index; self.state()['index'] = index
        self.refresh()

    def mount_tools(self):
        panel = self.owner.tool_panel
        if self.embedded_panel is panel: return
        self.unmount_tools()
        self.embedded_panel = panel
        self.tool_size_policy = panel.sizePolicy()
        self.tool_visibility = [(widget,not widget.isHidden()) for widget in
                                (panel.target.parentWidget(),panel.rail_scroll,panel.separator)]
        panel.setParent(self.tool_host)
        self.placeholder = QWidget(); self.owner.tools_dock.setWidget(self.placeholder)
        self.tool_layout.addWidget(panel); panel.setProperty('guidedEmbedded',True)
        panel.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Ignored)
        for widget,_ in self.tool_visibility: widget.hide()
        from .tool_modes import configure_page, ToolMode
        for key,(page,_) in panel.entries.items():configure_page(page,key,ToolMode.QUICK)
        panel.show(); panel.fit_action_width(); self.owner.tools_dock.hide()
        self.presented = None

    def unmount_tools(self):
        self.end_previous()
        self.auto_apply.detach()
        panel = self.embedded_panel
        if panel is None: return
        self.tool_layout.removeWidget(panel); panel.setParent(self.owner.tools_dock)
        self.owner.tools_dock.setWidget(panel)
        self.placeholder.deleteLater()
        panel.setProperty('guidedEmbedded',False)
        from .tool_modes import configure_page, ToolMode
        for key,(page,_) in panel.entries.items():configure_page(page,key,ToolMode.FULL)
        panel.setSizePolicy(self.tool_size_policy)
        for widget,visible in self.tool_visibility: widget.setVisible(visible)
        # Reparenting into the dock hides the panel itself; showing the dock
        # alone does not undo that explicit hidden state.
        panel.show()
        panel.sync_crop()
        panel.fit_action_width(); self.embedded_panel = None; self.presented = None

    def available_engines(self,stage):
        from pathlib import Path
        from processes.tool_updates import find_tool
        available=[]
        for key,title in self.engine_options[stage]:
            tool=key.split(':')[0]
            executable=find_tool(tool,str(self.owner.settings.value('external/'+tool,'')))
            if executable and Path(executable).is_file():available.append((key,title))
        return available

    def refresh_engine_choices(self):
        for stage,choice in self.engine_choices.items():
            choice.clear()
            for key,title in self.available_engines(stage):choice.addItem(title,key)
            selected=next((step['tool'] for step in self.route_editor.route if step['stage']==stage),None)
            index=choice.findData(selected)
            if index>=0:choice.setCurrentIndex(index)
            if not choice.count():choice.addItem(self.tr('Нет доступных инструментов','No tools available'),None)
            choice.setEnabled(choice.currentData() is not None)

    def present_tool(self, source, record):
        self.mount_tools()
        step = self.route[self.current]; key = step['tool']
        if record is not None:
            history=record['history']
            self.state()['anchors'].setdefault(step['id'],(history.entries[history.index],record.get('stretch',True)))
        embedded = key not in ('open','export','save')
        self.tool_host.setVisible(embedded and record is not None)
        self.rest_space.setVisible(not embedded or record is None)
        self.photo_card.setVisible(record is not None and not embedded)
        self.run.setVisible(not embedded)
        self.landing.setVisible(step['stage']=='export' and not embedded)
        self.master_button.setVisible(key != 'save')
        self.master_button.setEnabled(record is not None)
        self.project_button.setEnabled(record is not None)
        self.profiles.setVisible(embedded and record is not None and key in PROFILES
                                and key not in ('graxpert:background-extraction','graxpert:denoising','rcastro:nxt',
                                                'rcastro:bxt','graxpert:deconv-stellar','graxpert:deconv-obj'))
        self.run.setText(self.tr('Выбрать другое фото…', 'Choose another photo…') if key=='open' and record else
                         self.tr('Выбрать фотографию…', 'Choose a photo…') if key=='open' else
                         self.tr('Сохранить JPEG или PNG…', 'Save JPEG or PNG…') if key=='export' else self.catalog[key])
        role = 'guidedPrimary' if key != 'open' or record is None else ''
        if self.run.objectName() != role:
            self.run.setObjectName(role); self.run.style().unpolish(self.run); self.run.style().polish(self.run)
        identity = (source,step['id'],key)
        if self.presented != identity:
            self.presented = identity
            if embedded and record is not None: self.open_tool()
        self.owner.tool_panel.sync_crop()
        self.auto_apply.configure()

    def sync(self):
        if not self.isVisible(): return
        if self.before_hold is not None:
            source=self.before_hold[0]
            if (not self.previous_preview.isDown() or source is not self.owner.mdi.activeSubWindow()
                    or source not in self.owner.documents or self.owner.documents[source]['data'] is not self.before_hold[1]):
                self.end_previous()
        focus=getattr(self.owner,'guided_workspace',None)
        if focus is not None:focus.focus()
        source = self.owner.mdi.activeSubWindow(); record = self.owner.documents.get(source)
        choices=[(window.windowTitle(),window) for window in self.owner.documents]
        previous=[(self.photo_choice.itemText(i),self.photo_choice.itemData(i)) for i in range(self.photo_choice.count())]
        self.photo_choice.blockSignals(True)
        if choices!=previous:
            self.photo_choice.clear()
            for title,window in choices:self.photo_choice.addItem(title,window)
        self.photo_choice.setCurrentIndex(self.photo_choice.findData(source))
        self.photo_choice.blockSignals(False);self.photo_choice.setVisible(len(choices)>1)
        histories = {r['history'] for r in self.owner.documents.values()}
        self.states = {h: s for h, s in self.states.items() if h in histories}
        state = self.state()
        if source is not self.source:
            self.source = source; self.current = min(state['index'], len(self.route)-1); self.refresh()
        self.target.setText(source.windowTitle() if record else '')
        if record:
            shape = record['data'].shape
            self.photo_info.setText(f'{shape[1]} × {shape[0]} · '+('RGB' if len(shape)==3 else self.tr('моно', 'mono')))
        busy = heavy_job_running(self.owner) or getattr(self.owner,'quick_deconv_pending',False)
        history=record['history'] if record else None
        result=state.get('rgb_result')
        state['rgb_enabled']=bool(result is not None and history is not None
                                  and any(e is result for e in history.entries[:history.index+1]))
        self.rgb_balance.blockSignals(True)
        self.rgb_balance.setChecked(bool(state.get('rgb_enabled') or state.get('rgb_pending')))
        self.rgb_balance.blockSignals(False)
        self.rgb_balance.setVisible(self.current==0)
        self.rgb_balance.setEnabled(not busy and record is not None and record['data'].ndim==3 and record['data'].shape[-1]==3)
        for widget in (self.tool, self.kind, self.back, self.skip, self.next, self.reset, self.run,
                       self.jump, self.mode_settings_button, self.profiles, self.landing):
            widget.setEnabled(not busy)
        self.previous_preview.setVisible(self.current > 0)
        self.previous_preview.setEnabled(not busy and not self.auto_apply.pending and self.auto_apply.restore is None
                                         and self.step_anchor(self.current) is not None)
        self.rollback.setEnabled(not busy and record is not None and not self.auto_apply.pending and self.auto_apply.restore is None)
        self.back.setEnabled(not busy and self.current > 0)
        self.skip.setEnabled(not busy and record is not None)
        self.next.setEnabled(not busy and record is not None and not self.auto_apply.pending
                             and self.auto_apply.restore is None)
        self.guard = True; self.kind.setCurrentIndex(self.kind.findData(state['kind'])); self.guard = False
        show_kind=self.current==0 and self.experience.currentIndex()==0
        self.kind_caption.setVisible(show_kind)
        self.kind.setVisible(show_kind)
        self.options.setVisible(show_kind)
        step = self.route[self.current]
        mark = state['marks'].get(step['id'],'')
        suffix = {'reviewed':' ✓','skipped':' ↷'}.get(mark,'')
        self.step_counter.setText(self.tr('Шаг {0} из {1}', 'Step {0} of {1}').format(self.current+1,len(self.route)))
        self.progress.setRange(0,len(self.route)); self.progress.setValue(self.current+1)
        self.step_title.setText((self.tr('Открыть фото', 'Open photo')
                                if record is not None and step['stage']=='load' and step['tool']=='open'
                                else self.title(step))+suffix)
        stage = next((s for s in STAGES if s[0] == step['stage']), None)
        hint = self.tr(stage[4], stage[5]) if stage else ''
        if step['stage']=='background':
            hint = self.tr('Настройте сглаживание – фон обновится автоматически. Для RBF при вычитании фона расставьте точки на чистом фоне.',
                           'Adjust smoothing to update the background automatically. For RBF subtraction, place points on clean background.')
        elif step['stage']=='stretch':
            hint = self.tr('Настройте авторастяжку в гистограмме – слабые детали сразу проявятся на фото.',
                           'Adjust auto stretch in the histogram to reveal faint details directly in your photo.')
        if step['tool'] in ('rcastro:bxt','graxpert:deconv-stellar','graxpert:deconv-obj'):
            hint=self.tr('Автоматическая деконволюция звёзд и туманности.',
                         'Automatic deconvolution of stars and nebulosity.')
        if step['stage']=='load' and record is not None and step['tool']=='open':
            hint = self.tr('Фото открыто. Укажите, как оно подготовлено, и переходите к обработке.',
                           'Your photo is open. Select how it was prepared, then continue to processing.')
        elif step['tool'] in HINTS_RU:
            hint = localize(HINTS_RU[step['tool']])
        if state['kind'] == 'narrow' and step['stage'] == 'color':
            hint = self.tr('SHO / HOO: рекомендуется пропустить калибровку широкополосного цвета.', 'SHO / HOO: skip broadband colour calibration.')
        if state['kind'] == 'stretched' and step['stage'] in ('background', 'color', 'noise', 'stretch'):
            hint = self.tr('Изображение уже растянуто: этот линейный этап рекомендуется пропустить.', 'Already stretched: skipping this linear stage is recommended.')
        self.hint.setText(hint); self.hint.setVisible(bool(hint) and (self.experience.currentIndex() == 0 or record is None))
        self.run.setEnabled(not busy and (record is not None or step['tool'] == 'open'))
        anchor = state['anchors'].get(step['id'])
        history = record['history'] if record else None
        retained = history is not None and anchor is not None and any(e is anchor[0] for e in history.entries)
        self.reset.setEnabled(not busy and retained and history.entries[history.index] is not anchor[0])
        self.reset.setVisible(retained and history.entries[history.index] is not anchor[0])
        status = ''
        if busy:
            status = self.tr('Обработка выполняется…', 'Processing…')
        elif record is not None and step['tool'] == 'crop':
            status = self.tr('Рамка применится при переходе дальше.', 'The crop is applied when you advance.')
        elif (record is not None and step['tool'] not in
              ('open', 'save', 'export', 'native:histogram', 'rcastro:bxt',
               'graxpert:deconv-stellar', 'graxpert:deconv-obj') and not self.auto_apply.manual()):
            status = self.tr('Изменения применяются автоматически.', 'Changes are applied automatically.')
        self.status.setText(status)
        self.status.setVisible(bool(status))
        self.next.setText(self.tr('Завершить', 'Finish') if self.current == len(self.route)-1 else self.tr('Продолжить →', 'Continue →'))
        self.next.setVisible(record is not None)
        self.back.setVisible(self.current > 0)
        self.skip.setVisible(record is not None and step['stage'] not in ('load','export'))
        if not busy: self.present_tool(source,record)

    def change_experience(self):
        self.owner.settings.setValue('guided/compact', self.experience.currentIndex()); self.sync()

    def change_kind(self):
        if not self.guard: self.state()['kind'] = self.kind.currentData(); self.sync()

    def change_tool(self):
        if self.guard or heavy_job_running(self.owner): return
        if self.tool.currentData() is None: return
        self.route[self.current]['tool'] = self.tool.currentData(); self.persist(); self.refresh()

    def adopt_tool(self, key):
        if key not in self.catalog or self.route[self.current]['tool']==key: return
        self.route[self.current]['tool']=key
        self.presented=(self.owner.mdi.activeSubWindow(),self.route[self.current]['id'],key)
        self.persist();self.refresh()

    def navigate(self, delta):
        if heavy_job_running(self.owner) or getattr(self.owner,'quick_deconv_pending',False):return
        index=max(0,min(len(self.route)-1,self.current+delta))
        if index==self.current:return
        if delta<0 and self.owner.mdi.activeSubWindow() in self.owner.documents:
            self.rollback_to(index,confirm=False)
        else:self.select(index)

    def advance(self, skip):
        if heavy_job_running(self.owner) or self.owner.mdi.activeSubWindow() not in self.owner.documents: return
        if not skip and self.route[self.current]['tool']=='crop':
            if not self.owner.tool_panel.crop_panel.apply():return
        self.state()['marks'][self.route[self.current]['id']] = 'skipped' if skip else 'reviewed'
        if self.current < len(self.route)-1: self.current += 1
        elif not skip: self.owner.guided_action.setChecked(False)
        self.refresh()

    def open_tool(self):
        if heavy_job_running(self.owner): return
        key = self.route[self.current]['tool']
        record = self.owner.documents.get(self.owner.mdi.activeSubWindow())
        if record:
            history = record['history']
            self.state()['anchors'].setdefault(self.route[self.current]['id'],
                                               (history.entries[history.index], record.get('stretch', True)))
        if key == 'open': self.owner.open()
        elif record is not None:
            if key == 'export': self.owner.export_image()
            elif key == 'save': self.owner.save()
            else:
                self.owner.open_tool(key)

    def load_route_presets(self):
        self.route_presets.clear()
        for key,ru,en in [('default','Полный маршрут','Full workflow'),('native','Без внешних инструментов','Built-in tools'),('finish','Готовое растянутое фото','Already stretched photo')]:
            self.route_presets.addItem(self.tr(ru,en),key)
        try:
            saved=json.loads(self.owner.settings.value('guided/presets','{}'))
            self.saved_presets=saved if isinstance(saved,dict) else {}
        except (ValueError,TypeError):self.saved_presets={}
        for name in self.saved_presets:self.route_presets.addItem(name,'user:'+name)

    def load_route_preset(self):
        key=self.route_presets.currentData()
        if key is None:return
        if key.startswith('user:'):
            value=self.saved_presets[key[5:]]
            try:route=validate_route(value['route'],self.catalog)
            except (ValueError,TypeError,KeyError):return
            compact=value.get('compact',0)
        else:
            route=default_route();compact=0
            if key=='native':
                route=[step for step in route if step['stage'] not in ('detail','noise')]
                for step in route:
                    if step['stage']=='background':step['tool']='native:reference_background'
            elif key=='finish':route=[step for step in route if step['stage'] in ('load','crop','polish','export')]
        self.route_editor.route=copy.deepcopy(route);self.route_editor.refresh(0)
        self.refresh_engine_choices()
        self.experience.setCurrentIndex(1 if compact==1 else 0)

    def save_route_preset(self):
        self.route_editor.rename()
        name,ok=QInputDialog.getText(self,self.tr('Сохранить пресет','Save preset'),self.tr('Название','Name'))
        name=name.strip()
        if not ok or not name:return
        if name in self.saved_presets and QMessageBox.question(self,'Astra',self.tr('Заменить существующий пресет?','Replace existing preset?'))!=QMessageBox.Yes:return
        self.saved_presets[name]=dict(route=validate_route(self.route_editor.route,self.catalog),compact=self.experience.currentIndex())
        self.owner.settings.setValue('guided/presets',json.dumps(self.saved_presets))
        self.load_route_presets();self.route_presets.setCurrentIndex(self.route_presets.findData('user:'+name))

    def step_anchor(self,index):
        record=self.owner.documents.get(self.owner.mdi.activeSubWindow())
        if record is None:return None
        anchor=self.state()['anchors'].get(self.route[index]['id'])
        if anchor is None:return None
        history=record['history']
        position=next((i for i,e in enumerate(history.entries) if e is anchor[0]),None)
        return (position,anchor) if position is not None else None

    def preview_previous(self):
        self.end_previous()
        if heavy_job_running(self.owner) or self.current<1 or self.auto_apply.pending or self.auto_apply.restore is not None:return
        retained=self.step_anchor(self.current)
        if retained is None:return
        source=self.owner.mdi.activeSubWindow();record=self.owner.documents[source]
        try:
            data,_=record['history'].snapshot(retained[0],record['data'],record.get('count'))
            view=record['image']
            state=dict(scale=view.scale,offset=QPointF(view.offset),fitted=view.fitted,
                       crop_rect=QRect(view.crop_rect) if view.crop_rect is not None else None,crop_angle=view.crop_angle)
            display=dict(record,data=data,stretch=retained[1][1],quality_mode=None)
            display.pop('preview_data',None);display.pop('preview_owner',None);display.pop('tone_preview',None)
            display['history']=copy.copy(record['history']);display['history'].index=retained[0]
            self.before_hold=(source,record['data'],state)
            self.owner.render(document=source,display_record=display)
        except (OSError,ValueError,MemoryError) as error:
            self.end_previous()
            QMessageBox.warning(self,'Astra',str(error))

    def end_previous(self):
        held=self.before_hold;self.before_hold=None
        if held is None:return
        source,data,state=held
        record=self.owner.documents.get(source)
        if record is None:return
        self.owner.render(document=source)
        if record['data'] is data:
            view=record['image']
            for key,value in state.items():setattr(view,key,value)
            view.update()

    def eventFilter(self,watched,event):
        if watched is self.owner and event.type() in (QEvent.WindowDeactivate,QEvent.Hide,QEvent.Close):
            self.end_previous()
        return super().eventFilter(watched,event)

    def rollback_menu(self):
        if heavy_job_running(self.owner) or self.auto_apply.pending or self.auto_apply.restore is not None:return
        menu=QMenu(self)
        for i,step in enumerate(self.route):
            action=menu.addAction(f'{i+1}. {self.title(step)}')
            action.setEnabled(self.step_anchor(i) is not None)
            action.triggered.connect(lambda checked=False,index=i:self.rollback_to(index))
        menu.exec(self.rollback.mapToGlobal(self.rollback.rect().bottomLeft()))

    def rollback_to(self,index,confirm=True):
        if (heavy_job_running(self.owner) or getattr(self.owner,'quick_deconv_pending',False)
                or self.auto_apply.restore is not None or (confirm and self.auto_apply.pending)):return
        retained=self.step_anchor(index)
        # A route jump can leave intermediate steps unvisited. Their input is
        # the last retained state before them, not the currently edited image.
        if retained is None and not confirm:
            retained=next((anchor for i in range(index-1,-1,-1)
                           if (anchor:=self.step_anchor(i)) is not None),None)
        if retained is None:return
        if confirm and QMessageBox.question(self,'Astra',self.tr(
            'Вернуться к началу шага «{0}»? Последующие изменения останутся в истории до новой обработки.',
            'Return to the start of “{0}”? Later changes remain in history until new processing.').format(self.title(self.route[index])),
            QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
        source=self.owner.mdi.activeSubWindow();record=self.owner.documents[source]
        self.end_previous()
        self.auto_apply.timer.stop();self.auto_apply.pending=False;self.auto_apply.force=False
        self.owner.history_go(source,retained[0])
        if record['history'].index!=retained[0]:return
        record['stretch']=retained[1][1];self.owner.set_preview_stretch(retained[1][1]);self.owner.render()
        state=self.state();keep={step['id'] for step in self.route[:index+1]}
        state['anchors']={k:v for k,v in state['anchors'].items() if k in keep}
        state['anchors'].setdefault(self.route[index]['id'],retained[1])
        state['marks']={k:v for k,v in state['marks'].items() if k in {s['id'] for s in self.route[:index]}}
        self.select(index)

    def reset_step(self):
        if heavy_job_running(self.owner): return
        source = self.owner.mdi.activeSubWindow(); record = self.owner.documents.get(source)
        anchor = self.state()['anchors'].get(self.route[self.current]['id'])
        if record is None or anchor is None: return
        history = record['history']
        index = next((i for i, entry in enumerate(history.entries) if entry is anchor[0]), None)
        if index is None: return
        if QMessageBox.question(self, 'Astra', self.tr(
                'Вернуться к состоянию перед этим шагом? Последующие изменения останутся в истории до нового применения.',
                'Return to the state before this step? Later changes stay in history until another tool is applied.')) != QMessageBox.Yes: return
        self.owner.history_go(source, index)
        if history.index == index:
            record['stretch'] = anchor[1]; self.owner.set_preview_stretch(anchor[1]); self.owner.render()
            self.state()['marks'].clear()
            # Later anchors refer to a branch that the user has now left.
            self.state()['anchors'] = {self.route[self.current]['id']: anchor}
        self.refresh()


def install_guided_mode(owner, viewmenu):
    from .guided_workspace import GuidedWorkspace
    owner.guided_workspace=GuidedWorkspace(owner)
    dock = QDockWidget(owner.trtext('Пошаговый режим', 'Guided mode'), owner)
    dock.setObjectName('guidedDock'); dock.setAllowedAreas(Qt.RightDockWidgetArea)
    dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
    panel = GuidedPanel(owner)
    dock.setWidget(panel); owner.addDockWidget(Qt.RightDockWidgetArea, dock); dock.hide()
    owner.guided_panel = panel; owner.guided_dock = dock
    action = QAction(owner.trtext('Пошаговый режим', 'Guided mode'), owner)
    action.setCheckable(True); action.setShortcut('Ctrl+J'); owner.guided_action = action
    viewmenu.addAction(action)
    saved = {}
    transition = None

    def clear_transition():
        nonlocal transition
        if transition is not None:
            overlay, animation = transition
            transition = None
            animation.stop()
            overlay.hide()
            overlay.deleteLater()

    def toggle(enabled):
        nonlocal transition
        clear_transition()
        snapshot = owner.grab() if owner.isVisible() and not owner.isMinimized() else None
        action.setText(owner.trtext('Пошаговый режим','Guided mode'))
        action.setToolTip(owner.trtext('Пошаговый режим включён. Нажмите для выхода.','Guided mode is on. Click to exit.') if enabled else owner.trtext('Включить пошаговый режим','Enable guided mode'))
        if enabled:
            saved.update(mode=owner.mdi.viewMode(), tools=owner.tools_dock.isVisible(),
                         tools_width=owner.tools_dock.width())
            owner.addDockWidget(Qt.RightDockWidgetArea,dock)
            saved['menus']=[(menu.menuAction(),menu.menuAction().isEnabled()) for menu in (owner.tools_menu,owner.plugins_menu)]
            for menu_action,_ in saved['menus']:menu_action.setEnabled(False)
            # The hidden placeholder used by the standard workspace must not
            # become an empty photo tab when Qt changes MDI view modes.
            saved['placeholder'] = owner.empty_viewwindow in owner.mdi.subWindowList()
            if saved['placeholder']:
                owner.mdi.removeSubWindow(owner.empty_viewwindow)
                owner.empty_viewwindow.setParent(owner); owner.empty_viewwindow.hide()
            owner.mdi.setViewMode(QMdiArea.SubWindowView)
            owner.set_history_visible(owner.history_view_action.isChecked()); panel.mount_tools(); dock.show()
            owner.guided_workspace.start()
            owner.resizeDocks([dock], [330], Qt.Horizontal); panel.sync()
        else:
            owner.guided_workspace.stop()
            panel.unmount_tools()
            dock.hide()
            if saved:
                for menu_action,was_enabled in saved['menus']:menu_action.setEnabled(was_enabled)
                owner.mdi.setViewMode(saved['mode'])
                if saved['placeholder']:
                    QMdiArea.addSubWindow(owner.mdi, owner.empty_viewwindow)
                    owner.empty_viewwindow.hide()
                owner.tools_dock.setVisible(saved['tools'] or bool(owner.tool_panel.entries))
                if owner.tools_dock.isVisible():
                    owner.resizeDocks([owner.tools_dock], [saved['tools_width']], Qt.Horizontal)
                owner.tool_panel.sync_crop()
            owner.set_history_visible(owner.history_view_action.isChecked())
        owner.arrange_workspace_layers()
        if snapshot is not None and not snapshot.isNull():
            overlay = QLabel(owner)
            overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
            overlay.setFocusPolicy(Qt.NoFocus)
            overlay.setGeometry(owner.rect())
            overlay.setPixmap(snapshot)
            effect = QGraphicsOpacityEffect(overlay)
            effect.setOpacity(1)
            overlay.setGraphicsEffect(effect)
            animation = QPropertyAnimation(effect, b'opacity', overlay)
            animation.setDuration(220)
            animation.setStartValue(1.0)
            animation.setEndValue(0.0)
            animation.setEasingCurve(QEasingCurve.OutCubic)
            animation.finished.connect(clear_transition)
            transition = overlay, animation
            overlay.show()
            overlay.raise_()
            animation.start()
    action.toggled.connect(toggle)
    # Session restore can override allowedAreas and show a previously saved dock.
    dock.dockLocationChanged.connect(lambda area:QTimer.singleShot(0,owner,
        lambda:owner.addDockWidget(Qt.RightDockWidgetArea,dock)) if area!=Qt.RightDockWidgetArea else None)
    def restore_visible_mode():
        if dock.isVisible() and not action.isChecked():action.setChecked(True)
    dock.visibilityChanged.connect(lambda visible:QTimer.singleShot(0,owner,restore_visible_mode) if visible else None)
