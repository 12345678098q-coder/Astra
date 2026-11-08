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
        record=self.owner.documents.get(source,{})
        viewport=record.get('image')
        anchor=source.mapToGlobal(QPoint(0,0)) if source else self.owner.mapToGlobal(QPoint(0,0))
        screen=QApplication.screenAt(anchor) or self.owner.screen()
        available=screen.availableGeometry()
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
    def render(self):
        source=self.data
        if source is None:return
        # Bound display allocation. Numerical preview data retain original precision.
        step=max(1,int(np.ceil(max(source.shape[:2])/2400)));sample=source[::step,::step];finite=sample[np.isfinite(sample)]
        if not finite.size:return
        lo,hi=(self.display_stretch[:2] if self.display_stretch is not None else np.percentile(finite,[.2,99.8])) if self.stretched else (self.display_range or (0.,1.))
        a=np.clip((sample-lo)/max(float(hi-lo),1e-15),0,1)
        if self.stretched:
            from processes.stretch import automatic_strength
            strength=self.display_stretch[2] if self.display_stretch is not None else automatic_strength(finite,lo,hi)
            if strength:a=np.arcsinh(strength*a)/np.arcsinh(strength)
        if a.ndim==2:a=np.repeat(a[...,None],3,axis=-1)
        rgb=(np.nan_to_num(a[...,:3])*255).astype(np.uint8)
        self.image.stretched=self.stretched
        self.image.setPixmap(QPixmap.fromImage(QImage(rgb.data,rgb.shape[1],rgb.shape[0],rgb.strides[0],QImage.Format_RGB888).copy()))

def show_preview(owner,data,title,stretched=False,source=None,display_range=None,display_stretch=None):
    if stretched and display_stretch is None:
        from .preview_levels import checkpoint_transfer
        record=owner.documents.get(source or owner.mdi.activeSubWindow(),{})
        display_stretch=checkpoint_transfer(record)
    dialog=getattr(owner,'temporary_preview',None)
    if dialog is None:dialog=PreviewWindow(owner);owner.temporary_preview=dialog
    dialog.display(data,title,stretched,source,display_range,display_stretch);return dialog
