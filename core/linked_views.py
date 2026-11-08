"""Pixel-coordinate groups shared by navigation and tool application."""
import uuid
from PySide6.QtCore import QPointF


def active_group(record):
    if not record:return None
    history=record['history']
    return history.entries[history.index].get('link_id') or record.get('view_group')


def synchronize(owner, source):
    record=owner.documents.get(source)
    group=active_group(record)
    if not group:return
    image=record['image']
    if image.pixmap is None:return
    center=(QPointF(image.width()/2,image.height()/2)-image.offset)/image.scale
    for window,other in owner.documents.items():
        target=other['image']
        if window is source or active_group(other)!=group:continue
        if other['data'].shape[:2]!=record['data'].shape[:2]:continue
        target.scale=image.scale;target.fitted=False
        target.offset=QPointF(target.width()/2,target.height()/2)-center*image.scale
        target.constrain_offset()
        target.update()


def sync_button(owner):
    action=owner.actions.get('linked_views')
    if action is None:return
    source=owner.mdi.activeSubWindow();record=owner.documents.get(source)
    group=active_group(record)
    members=[w for w,r in owner.documents.items() if group and active_group(r)==group and r['data'].shape[:2]==record['data'].shape[:2]]
    linked=len(members)>1
    compatible=[w for w,r in owner.documents.items() if record and not w.isHidden() and r['data'].shape[:2]==record['data'].shape[:2]]
    action.blockSignals(True);action.setChecked(linked);action.setEnabled(linked or len(compatible)>1);action.blockSignals(False)
    tr=owner.trtext
    action.setText(tr('Отключить связь окон','Unlink views') if linked else tr('Связать окна','Link views'))
    if linked:
        names='\n'.join(w.windowTitle() for w in members[:6])
        action.setToolTip(tr('Окна связаны: масштаб, перемещение и применение инструментов общие. Нажмите, чтобы отключить связь.','Views are linked: zoom, pan and tool application are shared. Click to unlink.')+'\n'+names)
    else:
        action.setToolTip(tr('Связать все открытые фото такого же размера с текущим. Нужны минимум два фото.','Link all open images of the same dimensions as the current image. At least two images are required.'))


def toggle_link(owner,enabled):
    source=owner.mdi.activeSubWindow();record=owner.documents.get(source)
    if not record:return
    if not enabled:
        group=active_group(record)
        if record['history'].entries[record['history'].index].get('link_id'):
            from .checkpoint_links import unlink
            unlink(owner,group);return
        for other in owner.documents.values():
            if group and other.get('view_group')==group:other.pop('view_group',None)
    else:
        chosen=[w for w,r in owner.documents.items() if not w.isHidden() and r['data'].shape[:2]==record['data'].shape[:2]]
        if len(chosen)<2:sync_button(owner);return
        group=uuid.uuid4().hex
        for window in chosen:owner.documents[window]['view_group']=group
        synchronize(owner,source)
    sync_button(owner)
    for window in owner.documents:owner.update_history(window)


def join_opened(owner,window):
    record=owner.documents[window]
    for other_window,other in owner.documents.items():
        if other_window is not window and not other_window.isHidden() and other.get('view_group') and other['data'].shape[:2]==record['data'].shape[:2]:
            record['view_group']=other['view_group'];synchronize(owner,other_window);break
    sync_button(owner)
    for document in owner.documents:owner.update_history(document)
