"""Persistent controls for supported process options."""
from core.responsive import set_em_size, FormCaption
from core.i18n import localize
import json
from PySide6.QtCore import Signal,Qt
from PySide6.QtWidgets import QWidget,QFormLayout,QCheckBox,QDoubleSpinBox,QSpinBox,QComboBox,QLineEdit,QLabel,QSlider,QHBoxLayout,QSizePolicy
from .options import SCHEMAS,values_for
from .tooltips import HELP

class OptionForm(QWidget):
    changed=Signal()
    def __init__(self,window,key):
        super().__init__(); self.window=window; self.key=key; self.fields={}
        try:saved=values_for(key,json.loads(window.settings.value('process_options/'+key,'{}')))
        except (ValueError,TypeError):saved=values_for(key)
        layout=QFormLayout(self);layout.setContentsMargins(0,0,0,0);layout.setRowWrapPolicy(QFormLayout.WrapLongRows);layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        for option in SCHEMAS[key]:
            label=window.trtext(option.ru,option.en)
            if option.choices:
                field=QComboBox()
                for title,value in option.choices:field.addItem(localize(title),value)
                field.setCurrentIndex(field.findData(saved[option.name]));signal=field.currentIndexChanged
            elif isinstance(option.default,bool):
                field=QCheckBox(label);field.setChecked(saved[option.name]);signal=field.toggled
            elif isinstance(option.default,(int,float)):
                field=QSpinBox() if isinstance(option.default,int) else QDoubleSpinBox()
                field.setRange(option.minimum,option.maximum);field.setSingleStep(option.step);field.setValue(saved[option.name]);signal=field.valueChanged
            else:
                field=QLineEdit(saved[option.name]);signal=field.textChanged
            field.setToolTip(localize(HELP.get(option.name,label)));
            field.setObjectName(option.name);self.fields[option.name]=field
            if isinstance(field,QCheckBox):layout.addRow(field)
            else:
                caption=FormCaption(label);caption.setWordWrap(True);caption.setToolTip(field.toolTip());layout.addRow(caption,field)
            if key=='rcastro:nxt' and option.name=='strength':
                layout.removeWidget(field)
                wrapper=QWidget();row=QHBoxLayout(wrapper);row.setContentsMargins(0,0,0,0)
                field.setSuffix(' %');field.setProperty('astra_keep_width',True)
                field.setSizePolicy(QSizePolicy.Fixed,QSizePolicy.Fixed)
                set_em_size(field,'setMinimumWidth',6.25)
                self.strength_slider=QSlider(Qt.Horizontal);self.strength_slider.setRange(0,100);self.strength_slider.setValue(saved['strength']);self.strength_slider.setToolTip(window.trtext('0 - без подавления, 100 - максимальная сила.','0 = no suppression, 100 = maximum strength.'))
                self.strength_slider.valueChanged.connect(field.setValue);field.valueChanged.connect(self.strength_slider.setValue)
                row.addWidget(self.strength_slider,1);row.addWidget(field);layout.setWidget(layout.rowCount()-1,QFormLayout.FieldRole,wrapper)
            signal.connect(self.updated)
        self.dependencies()
    def values(self):
        values={}
        for key,field in self.fields.items():
            values[key]=field.isChecked() if isinstance(field,QCheckBox) else field.currentData() if isinstance(field,QComboBox) else field.text().strip() if isinstance(field,QLineEdit) else field.value()
        return values_for(self.key,values)
    def dependencies(self):
        f=self.fields
        if self.key=='graxpert:background-extraction':
            rbf=f['method'].currentData()=='RBF'
            for key in ('sample_size','kernel'):self.layout().setRowVisible(f[key],rbf)
            for key in ('model','gpu'):self.layout().setRowVisible(f[key],not rbf)
        if self.key=='rcastro:bxt':
            automatic=f['auto_settings'].isChecked()
            f['auto_settings'].setToolTip(self.window.trtext('Astra анализирует звёзды и шум, подбирает силу и способ оценки PSF. Это эвристический подбор, а не гарантия оптимального результата. Для линейных кадров со звёздами.','Astra analyzes stars and noise and selects strengths and PSF mode. Heuristic selection, not a guarantee of optimal results. For linear images containing stars.'))
            for key,field in f.items():
                if key!='auto_settings':self.layout().setRowVisible(field,not automatic)
            f['psf'].setEnabled(not f['auto_psf'].isChecked())
            for key in ('sharpen_stars','sharpen_nonstellar'):f[key].setEnabled(not f['correct_only'].isChecked())
        if 'unscreen' in f:f['unscreen'].setEnabled(f['stars'].isChecked())
        if self.key=='starnet':
            for key in ('shadows','target'):f[key].setEnabled(f['mode'].currentData()==0)
    def updated(self,*args):
        self.dependencies()
        try:values=self.values()
        except ValueError:return
        self.window.settings.setValue('process_options/'+self.key,json.dumps(values));self.changed.emit()
    def reset(self):
        for option in SCHEMAS[self.key]:
            field=self.fields[option.name];field.blockSignals(True)
            if isinstance(field,QCheckBox):field.setChecked(option.default)
            elif isinstance(field,QComboBox):field.setCurrentIndex(field.findData(option.default))
            elif isinstance(field,QLineEdit):field.setText(option.default)
            else:field.setValue(option.default)
            field.blockSignals(False)
        if self.key=='rcastro:nxt':self.strength_slider.setValue(self.fields['strength'].value())
        self.updated()
