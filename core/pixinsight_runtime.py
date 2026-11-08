"""Small, explicit PJSR UI subset. Runs in its own disposable process."""
from pathlib import Path
import re
import sys
from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import (QApplication, QWidget, QDialog, QLabel, QPushButton,
    QCheckBox, QRadioButton, QGroupBox, QComboBox, QLineEdit, QDoubleSpinBox,
    QVBoxLayout, QHBoxLayout, QMessageBox)
from PySide6.QtQml import QJSEngine


def preprocess(path, root, seen=None):
    path = Path(path).resolve(); root = Path(root).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Include outside the imported package: '+str(path))
    seen = set() if seen is None else seen
    if path in seen: raise ValueError('Recursive include: '+str(path))
    seen.add(path)
    result = []
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        directive = line.strip()
        if not directive.startswith('#'):
            result.append(line); continue
        if re.match(r'#(?:engine|feature-id|feature-info)\b',directive):
            result.append(''); continue
        include = re.fullmatch(r'#include\s+["<]([^">]+)[">]\s*(?://.*)?',directive)
        if include:
            name = include[1].replace('\\','/')
            if name.startswith('pjsr/'):
                supported = {'Sizer.jsh','StdButton.jsh','StdIcon.jsh','TextAlign.jsh'}
                if name.split('/')[-1] not in supported:
                    raise ValueError('Unsupported PixInsight header: '+name)
                result.append('')
            else:
                result.append(preprocess(path.parent/name,root,seen))
            continue
        define = re.fullmatch(r'#define\s+([A-Za-z_]\w*)\s+(.+)',directive)
        if define:
            result.append('var '+define[1]+' = '+define[2]+';'); continue
        raise ValueError('Unsupported PixInsight directive: '+directive)
    seen.remove(path)
    return '\n'.join(result)


class Bridge(QObject):
    def __init__(self, engine):
        super().__init__(); self.engine = engine; self.items = []; self.dialogs = []

    @Slot(str,int,result=int)
    def create(self, kind, parent):
        owner = self.items[parent] if 0 <= parent < len(self.items) and isinstance(self.items[parent],QWidget) else None
        classes = {'Dialog':QDialog,'Control':QWidget,'Label':QLabel,'PushButton':QPushButton,
                   'ToolButton':QPushButton,'CheckBox':QCheckBox,'RadioButton':QRadioButton,
                   'GroupBox':QGroupBox,'ComboBox':QComboBox,'Edit':QLineEdit,
                   'NumericControl':QDoubleSpinBox,'NumericEdit':QDoubleSpinBox}
        if kind == 'VerticalSizer': item = QVBoxLayout()
        elif kind == 'HorizontalSizer': item = QHBoxLayout()
        elif kind=='NumericControl':
            item=QGroupBox(owner);row=QHBoxLayout(item)
            item._numeric=QDoubleSpinBox(item);row.addWidget(item._numeric)
        else: item = classes[kind](owner)
        index = len(self.items); self.items.append(item)
        if isinstance(item,QDialog):
            self.dialogs.append(item); item.setMinimumWidth(320)
        if isinstance(item,QDoubleSpinBox): item.setRange(-1e12,1e12); item.setDecimals(4)
        if hasattr(item,'_numeric'):
            item._numeric.setRange(-1e12,1e12)
            item._numeric.valueChanged.connect(lambda value,i=index:self.callback(i,'onValueUpdated',value))
        if isinstance(item,QPushButton): item.clicked.connect(lambda checked=False,i=index:self.callback(i,'onClick'))
        if isinstance(item,QCheckBox): item.toggled.connect(lambda value,i=index:self.callback(i,'onCheck',value))
        if isinstance(item,QComboBox): item.currentIndexChanged.connect(lambda value,i=index:self.callback(i,'onItemSelected',value))
        if isinstance(item,QDoubleSpinBox): item.valueChanged.connect(lambda value,i=index:self.callback(i,'onValueUpdated',value))
        return index

    def callback(self,index,event,*args):
        import json
        values=','.join(json.dumps(v) for v in args)
        result=self.engine.evaluate(f'if(typeof __objects[{index}].{event} === "function") __objects[{index}].{event}({values});')
        if result.isError(): self.report(result)

    @Slot(int,str,'QVariant')
    def set(self,index,name,value):
        item=self.items[index]
        if name=='value' and hasattr(item,'_numeric'):item=item._numeric
        setters={'text':'setText','title':'setTitle','windowTitle':'setWindowTitle',
                 'toolTip':'setToolTip','enabled':'setEnabled','visible':'setVisible',
                 'checked':'setChecked','currentItem':'setCurrentIndex','value':'setValue',
                 'minWidth':'setMinimumWidth','minHeight':'setMinimumHeight',
                 'maxWidth':'setMaximumWidth','maxHeight':'setMaximumHeight',
                 'spacing':'setSpacing'}
        if name=='sizer': item.setLayout(self.items[int(value)])
        elif name=='margin': item.setContentsMargins(*([int(value)]*4))
        elif name in setters and hasattr(item,setters[name]): getattr(item,setters[name])(value)

    @Slot(int,str,result='QVariant')
    def get(self,index,name):
        item=self.items[index]
        if name=='value' and hasattr(item,'_numeric'):item=item._numeric
        getters={'text':'text','title':'title','windowTitle':'windowTitle','enabled':'isEnabled',
                 'visible':'isVisible','checked':'isChecked','currentItem':'currentIndex',
                 'value':'value','width':'width','height':'height'}
        method=getters.get(name)
        return getattr(item,method)() if method and hasattr(item,method) else None

    @Slot(int,int,int)
    def add(self,layout,child,stretch):
        layout=self.items[layout];item=self.items[child]
        if isinstance(item,QWidget): layout.addWidget(item,stretch)
        else: layout.addLayout(item,stretch)

    @Slot(int,int)
    def stretch(self,index,value): self.items[index].addStretch(value)

    @Slot(int,str,'QVariant',result='QVariant')
    def call(self,index,name,value):
        item=self.items[index]
        if name in ('setRange','setPrecision') and hasattr(item,'_numeric'):item=item._numeric
        if name=='execute': return item.exec()==QDialog.Accepted
        if name=='show': item.show()
        elif name=='hide': item.hide()
        elif name=='ok': item.accept()
        elif name=='cancel': item.reject()
        elif name=='adjustToContents': item.adjustSize()
        elif name=='setRange': item.setRange(float(value[0]),float(value[1]))
        elif name=='setPrecision': item.setDecimals(int(value))
        elif name=='addItem': item.addItem(str(value))
        elif name=='addSpacing': item.addSpacing(int(value))

    @Slot(str)
    def log(self,text): print(text,flush=True)

    @Slot(str,str,result=int)
    def message(self,text,title):
        QMessageBox.information(None,title,text); return 1

    def report(self,result):
        from core.i18n import localize
        QMessageBox.warning(None,'PixInsight',localize('Скрипт использует неподдерживаемую функцию или содержит ошибку.\n',
            'The script uses an unsupported feature or contains an error.\n')+result.toString()+'\n'+result.property('stack').toString())


def main():
    app=QApplication(sys.argv)
    from core.i18n import configure_interface,localize
    from PySide6.QtCore import QSettings
    configure_interface(QSettings('Astra','Astra'))
    if len(sys.argv)>2: app.setStyleSheet(Path(sys.argv[2]).read_text(encoding='utf-8'))
    engine=QJSEngine();bridge=Bridge(engine)
    engine.globalObject().setProperty('__bridge',engine.newQObject(bridge))
    shim=Path(__file__).with_name('pixinsight_ui.js').read_text(encoding='utf-8')
    result=engine.evaluate(shim,'astra-pjsr-ui')
    if result.isError(): bridge.report(result); return
    path=Path(sys.argv[1]).resolve()
    root=path.parent
    imported=Path(__file__).resolve().parents[1]/'modules'/'imported_pixinsight'
    if path.is_relative_to(imported): root=imported/path.relative_to(imported).parts[0]
    try: code=preprocess(path,root)
    except (OSError,ValueError) as error:
        QMessageBox.warning(None,'PixInsight',str(error));return
    result=engine.evaluate(code,str(path))
    if result.isError(): bridge.report(result); return
    if any(dialog.isVisible() for dialog in bridge.dialogs): app.exec()
    elif not bridge.dialogs:
        QMessageBox.information(None,'PixInsight',localize('Скрипт завершился без открытия окна.', 'The script finished without opening a window.'))


if __name__=='__main__': main()
