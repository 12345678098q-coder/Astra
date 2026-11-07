"""Persistent application-wide interface density and text size."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QFontDatabase, QFontMetricsF
from PySide6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QComboBox,QDoubleSpinBox,QDialogButtonBox,QLabel,QWidget,QLayout

PRESETS={
 'compact':dict(vertical=2,horizontal=6,list_pad=3,header_pad=3,indicator=14,tool_pad=2,icon=18,gap=4),
 'normal':dict(vertical=6,horizontal=10,list_pad=7,header_pad=6,indicator=18,tool_pad=5,icon=24,gap=8),
 'spacious':dict(vertical=10,horizontal=14,list_pad=10,header_pad=9,indicator=22,tool_pad=8,icon=28,gap=12)}

def metrics(settings):
 key=str(settings.value('interface/density','normal'))
 try:font=max(10,min(18,int(settings.value('interface/font_size',12))))
 except (ValueError,TypeError):font=12
 values={**PRESETS.get(key,PRESETS['normal']),'min_height':14 if key=='compact' else 24 if key=='spacious' else 20}
 system=QFontDatabase.systemFont(QFontDatabase.GeneralFont)
 points=system.pointSizeF() if system.pointSizeF()>0 else 9.
 system.setPointSizeF(points*font/12)
 unit=QFontMetricsF(system).height()/16
 return {**{name:round(value*unit) for name,value in values.items()},'font':font,'font_points':points*font/12,'em':QFontMetricsF(system).height()}

def adjust_widgets(window):
 values=metrics(window.settings);factor=values['gap']/8
 window.toolbar.setIconSize(QSize(values['icon'],values['icon']))
 for layout in window.findChildren(QLayout):
  # Preserve intentional zero spacing and custom sizes. Store the baseline
  # once, so repeated theme/density changes cannot compound rounding.
  if layout.property('astra_base_spacing') is None:layout.setProperty('astra_base_spacing',layout.spacing())
  baseline=layout.property('astra_base_spacing')
  if baseline>=0:layout.setSpacing(round(baseline*factor))
  if layout.property('astra_base_margins') is None:
   margins=layout.contentsMargins();layout.setProperty('astra_base_margins',[margins.left(),margins.top(),margins.right(),margins.bottom()])
  layout.setContentsMargins(*(round(value*factor) for value in layout.property('astra_base_margins')))
 if hasattr(window,'tool_panel'):
  for page,button in window.tool_panel.entries.values():
   from core.responsive import set_em_size
   set_em_size(button,'setFixedWidth',3.45)
  window.tool_panel.fit_action_width()
  previous=window.tool_panel.property('interfaceFont')
  if previous is not None and previous!=values['font']:
   window.resizeDocks([window.tools_dock],[round(window.tools_dock.width()*values['font']/previous)],Qt.Horizontal)
  window.tool_panel.setProperty('interfaceFont',values['font'])
 for document in getattr(window,'documents',{}):window.update_history(document)

def show_interface_settings(window):
 settings=window.settings;tr=window.trtext
 original=(settings.value('interface/density','normal'),settings.value('interface/font_size',12))
 dialog=QDialog(window);dialog.setWindowTitle(tr('Настройка интерфейса','Interface settings'));layout=QVBoxLayout(dialog);form=QFormLayout();layout.addLayout(form)
 density=QComboBox()
 for key,ru,en in [('compact','Компактный','Compact'),('normal','Обычный','Normal'),('spacious','Просторный','Spacious')]:density.addItem(tr(ru,en),key)
 density.setCurrentIndex(max(0,density.findData(original[0])));form.addRow(tr('Плотность элементов','Control density'),density)
 font=QDoubleSpinBox();font.setRange(10/12,18/12);font.setDecimals(2);font.setSingleStep(1/12);font.setValue(metrics(settings)['font']/12);font.setSuffix(' ×');form.addRow(tr('Масштаб текста','Text scale'),font)
 note=QLabel(tr('Изменения видны сразу. Обычный режим сохраняет прежние размеры. Размер текста настраивается отдельно от плотности.','Changes appear immediately. Normal preserves previous dimensions. Text size is independent of control density.'));note.setWordWrap(True);layout.addWidget(note)
 def update():
  settings.setValue('interface/density',density.currentData());settings.setValue('interface/font_size',round(font.value()*12));window.apply_workspace_theme()
 density.currentIndexChanged.connect(update);font.valueChanged.connect(update)
 buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel|QDialogButtonBox.RestoreDefaults);layout.addWidget(buttons)
 buttons.button(QDialogButtonBox.Cancel).setText(tr('Отмена','Cancel'));buttons.button(QDialogButtonBox.RestoreDefaults).setText(tr('По умолчанию','Defaults'))
 buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
 buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(lambda:(density.setCurrentIndex(density.findData('normal')),font.setValue(1)))
 if dialog.exec()!=QDialog.Accepted:
  settings.setValue('interface/density',original[0]);settings.setValue('interface/font_size',original[1]);window.apply_workspace_theme()
