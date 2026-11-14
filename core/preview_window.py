"""Disposable, modeless preview; never registered as an image document."""
from core.responsive import fit_screen
import numpy as np
from PySide6.QtCore import Qt,QPoint
from PySide6.QtGui import QImage,QPixmap
from PySide6.QtWidgets import QDialog,QVBoxLayout,QApplication
from .image_view import ImageView

class PreviewWindow(QDialog):
    def __init__(self,window):
        super().__init__(window,Qt.Window);self.owner=window;fit_screen(self,0.641,0.689)
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0);self.image=ImageView();layout.addWidget(self.image,1)
        self.image.stretchRequested.connect(self.toggle_stretch);self.data=None
    def toggle_stretch(self,enabled):self.stretched=enabled;self.render()
    def display(self,data,title,stretched=False,source=None,display_range=None,display_stretch=None):
        was_visible=self.isVisible()
        self.data=data;self.stretched=stretched;self.display_range=display_range;self.display_stretch=display_stretch;self.setWindowTitle(self.owner.trtext('Временный предпросмотр · ','Temporary preview · ')+title)
        source=source or self.owner.mdi.activeSubWindow()
        self.source_window=source
        record=self.owner.documents.get(source,{})
        viewport=record.get('image')
        anchor=source.mapToGlobal(QPoint(0,0)) if source else self.owner.mapToGlobal(QPoint(0,0))
        screen=QApplication.screenAt(anchor) or self.owner.screen()
        available=screen.availableGeometry()
        # A floating preview must leave the processing controls accessible,
        # even when the source window is tiled near the tools dock.
        if viewport is not None:
            workspace=self.owner.mdi.viewport()
            workspace_rect=workspace.rect().translated(workspace.mapToGlobal(QPoint(0,0)))
            workspace_rect=available.intersected(workspace_rect)
            if workspace_rect.width()>=200 and workspace_rect.height()>=160:
                available=workspace_rect
        height,width=data.shape[:2]
        max_width=min(viewport.width() if viewport else round(available.width()*.75),round(available.width()*.96))
        max_height=min(viewport.height() if viewport else round(available.height()*.75),round(available.height()*.9))
        factor=min(max(1,max_width)/width,max(1,max_height)/height)
        self.showNormal();self.resize(max(1,round(width*factor)),max(1,round(height*factor)))
        self.image.fitted=True;self.render()
        # Position the decorated window over the original MDI window, keeping
        # the entire frame within the monitor's usable area (excluding taskbar).
        frame=self.frameGeometry();decoration=self.geometry().topLeft()-frame.topLeft()
        x=max(available.left(),min(anchor.x(),available.right()-frame.width()+1))
        y=max(available.top(),min(anchor.y(),available.bottom()-frame.height()+1))
        self.move(QPoint(x,y)+decoration);self.raise_()
        if not was_visible:self.activateWindow()
    def render(self,source_size=None):
        source=self.data
        if source is None:return
        # Bound display allocation. Numerical preview data retain original precision.
        step=1 if getattr(self,'full_resolution',False) else max(1,int(np.ceil(max(source.shape[:2])/2400)))
        sample=source[::step,::step]
        strength=0
        if self.stretched:
            from processes.stretch import automatic_strength
            finite=sample[np.isfinite(sample)]
            if not finite.size:finite=np.array([0.,1.])
            lo,hi=self.display_stretch[:2] if self.display_stretch is not None else np.percentile(finite,[.2,99.8])
            strength=self.display_stretch[2] if self.display_stretch is not None else automatic_strength(finite,lo,hi)
        else:
            lo,hi=self.display_range or (0.,1.)
        rgb=np.empty((*sample.shape[:2],3),dtype=np.uint8)
        for top in range(0,sample.shape[0],128):
            block=np.clip((sample[top:top+128]-lo)/max(float(hi-lo),1e-12),0,1)
            if strength:block=np.arcsinh(strength*block)/np.arcsinh(strength)
            if block.ndim==2:block=block[...,None]
            rgb[top:top+128]=np.nan_to_num(block[...,:3])*255
        self.image.stretched=self.stretched
        self.image.setPixmap(QPixmap.fromImage(QImage(rgb.data,rgb.shape[1],rgb.shape[0],rgb.strides[0],QImage.Format_RGB888).copy()),source_size)

def show_preview(owner,data,title,stretched=None,source=None,display_range=None,display_stretch=None,*,inherit_source=True,full_resolution=False):
    from .preview_levels import source_display
    record=owner.documents.get(source or owner.mdi.activeSubWindow(),{}) if inherit_source else {}
    if stretched is None:stretched=record.get('stretch',True)
    if display_range is None or (stretched and display_stretch is None):
        settings=getattr(owner,'settings',None)
        target=float(settings.value('preview_target',.2)) if settings is not None else .2
        original_range,original_transfer=source_display(record,target)
        if display_range is None:display_range=original_range
        if stretched and display_stretch is None:display_stretch=original_transfer
    dialog=getattr(owner,'temporary_preview',None)
    if dialog is None:dialog=PreviewWindow(owner);owner.temporary_preview=dialog
    dialog.tool_owner=None
    dialog.full_resolution=full_resolution
    dialog.display(data,title,stretched,source,display_range,display_stretch);return dialog
