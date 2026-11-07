"""Independent links between immutable history checkpoints in different documents."""
import uuid
import hashlib
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor


def selected(owner):
    selection=getattr(owner,'checkpoint_selection',{})
    result=[]
    for window,record in owner.documents.items():
        token=selection.get(window)
        for index,entry in enumerate(record['history'].entries):
            if token and entry.get('token')==token:result.append((window,index,entry));break
    return result


def refresh(owner):
    # A surviving single checkpoint no longer represents a link.
    groups={}
    for window,record in owner.documents.items():
        for entry in record['history'].entries:
            if entry.get('link_id'):groups.setdefault(entry['link_id'],set()).add(window)
    for record in owner.documents.values():
        for entry in record['history'].entries:
            if entry.get('link_id') and len(groups[entry['link_id']])<2:entry.pop('link_id',None);entry.pop('link_number',None)
    selection=getattr(owner,'checkpoint_selection',{})
    owner.checkpoint_selection={w:token for w,token in selection.items() if w in owner.documents and any(e.get('token')==token for e in owner.documents[w]['history'].entries)}
    for window in owner.documents:owner.update_history(window)
    from .linked_views import sync_button
    sync_button(owner)


def link_selected(owner):
    choices=selected(owner)
    if len(choices)<2:raise ValueError(owner.trtext('Выберите с Ctrl шаги истории минимум двух разных фото.','Ctrl-select checkpoints in at least two different images.'))
    shapes=[]
    for window,index,entry in choices:
        record=owner.documents[window]
        data=np.load(entry['path'],mmap_mode='r',allow_pickle=False) if entry['path'] else record['data']
        shapes.append(data.shape[:2])
    if any(shape!=shapes[0] for shape in shapes):raise ValueError(owner.trtext('Для связи нужны кадры одинаковой ширины и высоты.','Linked checkpoints must have matching width and height.'))
    group=uuid.uuid4().hex
    number=1+max((e.get('link_number',0) for r in owner.documents.values() for e in r['history'].entries),default=0)
    for window,index,entry in choices:
        entry['link_id']=group;entry['link_number']=number
        owner.documents[window].pop('view_group',None)
    owner.checkpoint_selection={}
    refresh(owner)
    from .linked_views import synchronize
    synchronize(owner,choices[-1][0])
    return group


def unlink(owner,group):
    for record in owner.documents.values():
        for entry in record['history'].entries:
            if entry.get('link_id')==group:entry.pop('link_id',None);entry.pop('link_number',None)
    refresh(owner)


def marker(owner,group):
    groups=[]
    number=None
    for record in owner.documents.values():
        for entry in record['history'].entries:
            if entry.get('link_id') and entry['link_id'] not in groups:groups.append(entry['link_id'])
            if entry.get('link_id')==group:number=entry.get('link_number')
    return number or groups.index(group)+1,QColor.fromHsv(int(hashlib.sha256(group.encode()).hexdigest()[:8],16)%360,140,230)
