"""Display-only diagnostics. Thresholds describe display clipping, not sensor saturation."""
from core.i18n import localize
import numpy as np


def paint_quality(source,rgb,mode,lo,hi,previous=None):
    counts={'black':0,'white':0,'invalid':0}
    if mode=='difference' and (previous is None or previous.shape!=source.shape):
        raise ValueError(localize('Нет совместимой предыдущей контрольной точки'))
    limit=1.
    if mode=='difference':
        step=max(1,int(np.ceil(max(source.shape[:2])/1000)))
        delta=np.asarray(source[::step,::step],dtype=np.float64)-previous[::step,::step]
        finite=np.abs(delta[np.isfinite(delta)])
        limit=max(float(np.percentile(finite,99.5)) if finite.size else 0.,1e-15)
    for y in range(0,len(source),128):
        a=source[y:y+128]
        valid=np.isfinite(a);bad=~valid if a.ndim==2 else ~valid.all(axis=2)
        counts['invalid']+=int(bad.sum())
        if mode=='difference':
            d=(np.asarray(a,dtype=np.float64)-previous[y:y+128])/limit
            d=np.nan_to_num(np.clip(.5+.5*d,0,1),nan=.5)
            if d.ndim==2:d=d[...,None]
            rgb[y:y+128]=d[...,:3]*255
        else:
            black=(a<=lo)&valid;white=(a>=hi)&valid
            if a.ndim==3:black=black.any(axis=2);white=white.any(axis=2)
            counts['black']+=int((black&~bad).sum());counts['white']+=int((white&~bad).sum())
            rgb[y:y+128][black]=[70,125,255]
            rgb[y:y+128][white]=[255,80,55]
        rgb[y:y+128][bad]=[255,0,255]
    return counts


def set_mode(owner,mode):
    window=owner.mdi.activeSubWindow();record=owner.documents.get(window)
    if not record:return
    if mode=='difference':
        history=record['history']
        if history.index<1:
            owner.statusBar().showMessage(owner.trtext('Нет предыдущего шага для сравнения.','No previous checkpoint to compare.'),5000);sync_actions(owner,record);return
        entry=history.entries[history.index-1]
        previous=np.load(entry['path'],mmap_mode='r',allow_pickle=False)
        if previous.shape!=record['data'].shape:
            owner.statusBar().showMessage(owner.trtext('Размеры текущего и предыдущего шага различаются.','Current and previous checkpoint dimensions differ.'),5000);sync_actions(owner,record);return
    record['quality_mode']=mode;sync_actions(owner,record);owner.render()


def sync_actions(owner,record):
    from core.linked_views import sync_button
    sync_button(owner)
    for key,mode in [('quality_limits','limits'),('quality_difference','difference')]:
        action=owner.actions[key];action.blockSignals(True)
        action.setChecked(bool(record) and record.get('quality_mode')==mode);action.setEnabled(bool(record));action.blockSignals(False)


def install_quick_controls(owner):
    from PySide6.QtGui import QAction
    from core.quick_icons import document_icon
    from core.linked_views import toggle_link
    tr=owner.trtext
    for key,ru,en,callback in [
        ('linked_views','Связать окна','Link views',lambda checked:toggle_link(owner,checked)),
        ('quality_limits','Пределы отображения и некорректные пиксели','Display limits and invalid pixels',lambda checked:set_mode(owner,'limits' if checked else None)),
        ('quality_difference','Разница с предыдущим шагом','Difference from previous checkpoint',lambda checked:set_mode(owner,'difference' if checked else None))]:
        action=QAction(document_icon(key,'#dddddd'),tr(ru,en),owner)
        action.setCheckable(True)
        action.triggered.connect(callback);owner.actions[key]=action
        if owner.settings.value('quick/'+key,True,type=bool):owner.toolbar.addAction(action)
    owner.actions['quality_limits'].setToolTip(tr('Пределы отображения: синий - тени, красный - света, пурпурный - NaN/Inf. Не измеряет насыщение сенсора. Данные не меняются.',
        'Display limits: blue - shadows, red - highlights, magenta - NaN/Inf. Does not measure sensor saturation. Data are unchanged.'))
    owner.actions['quality_difference'].setToolTip(tr('Разница с предыдущим шагом: серый - без изменений, светлее - добавлено, темнее - удалено. Контраст разницы усилен автоматически.',
        'Difference from previous checkpoint: gray - unchanged, lighter - added, darker - removed. Difference contrast is amplified automatically.'))
    sync_actions(owner,None)
