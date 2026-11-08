"""Document snapshots, internal copy drags and workspace drop targets."""
from core.responsive import set_em_size
from core.i18n import localize
import json
import uuid
import numpy as np
from PySide6.QtCore import Qt, QMimeData,QObject,QEvent,QPoint,QTimer
from PySide6.QtGui import QDrag, QPainter, QPalette,QCursor
from PySide6.QtWidgets import QListWidget, QMdiArea, QMenu, QInputDialog, QMessageBox, QSizeGrip, QMdiSubWindow, QStyle, QStyledItemDelegate,QApplication,QWidget
from core.resources import heavy_job_running

MIME='application/x-astra-checkpoint'
SHORT={'Автовыравнивание фона':'BN','Automatic background balance':'BN','Auto background balance':'BN','rcastro: bxt':'BXT','rcastro: nxt':'NXT','rcastro: sxt':'SXT',
       'graxpert: background-extraction':'GX-G','graxpert: denoising':'GX-N',
       'graxpert: deconv-obj':'GX-O','graxpert: deconv-stellar':'GX-S','StarNet':'SN'}

class CheckpointDropReceiver(QObject):
    """Accept copy drags over documents as well as empty MDI space."""
    def __init__(self,owner):
        super().__init__();self.owner=owner
    def eventFilter(self,watched,event):
        if event.type() not in (QEvent.DragEnter,QEvent.DragMove,QEvent.Drop):return False
        if not isinstance(watched,QWidget) or not event.mimeData().hasFormat(MIME):return False
        area=self.owner.mdi
        if watched is not area and not area.isAncestorOf(watched):return False
        parent=watched
        while parent is not None:
            if isinstance(parent,CheckpointList):return False
            parent=parent.parentWidget()
        try:
            payload=json.loads(bytes(event.mimeData().data(MIME)))
            match=next(((window,index) for window,record in self.owner.documents.items()
                        if record['id']==payload['document']
                        for index,entry in enumerate(record['history'].entries)
                        if entry.get('token')==payload['token']),None)
        except (ValueError,KeyError,TypeError):return False
        if match is None:return False
        event.setDropAction(Qt.CopyAction);event.accept()
        if event.type()==QEvent.Drop:
            point=area.viewport().mapFromGlobal(watched.mapToGlobal(event.position().toPoint()))
            window,index=match
            QTimer.singleShot(0,self.owner,lambda:self.owner.copy_checkpoint(window,index,point))
        return True

class CheckpointDelegate(QStyledItemDelegate):
    def initStyleOption(self,option,index):
        super().initStyleOption(option,index)
        option.state &= ~QStyle.State_HasFocus

class CheckpointList(QListWidget):
    def __init__(self,owner):
        super().__init__(); self.owner=owner; self.document=None
        self.setItemDelegate(CheckpointDelegate(self))
        self.setDragEnabled(True); self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.menu)
    def mousePressEvent(self,event):
        item=self.itemAt(event.position().toPoint())
        if item is not None and event.button()==Qt.LeftButton:
            if event.modifiers() & Qt.ControlModifier:
                from core.checkpoint_links import refresh
                selection=getattr(self.owner,'checkpoint_selection',{})
                token=self.owner.documents[self.document]['history'].entries[item.data(Qt.UserRole)].setdefault('token',uuid.uuid4().hex)
                if selection.get(self.document)==token:selection.pop(self.document,None)
                else:selection[self.document]=token
                self.owner.checkpoint_selection=selection
                if self.document in selection:self.owner.history_go(self.document,item.data(Qt.UserRole))
                refresh(self.owner);event.accept();return
            self.owner.checkpoint_selection={}
        if event.button()==Qt.RightButton:
            event.accept();return  # Keep cross-document Ctrl selection for the menu.
        super().mousePressEvent(event)
        if item is not None and event.button()==Qt.LeftButton:
            # Qt selects only this list on press. Restore the current steps in
            # linked documents after it has processed the click.
            from core.linked_views import active_group
            group=active_group(self.owner.documents.get(self.document))
            for window,record in self.owner.documents.items():
                if window is self.document:continue
                linked=bool(group and active_group(record)==group)
                listing=record['history_list']
                for row in range(listing.count()):
                    entry=listing.item(row)
                    entry.setSelected(linked and entry.data(Qt.UserRole)==record['history'].index)
    def startDrag(self,actions):
        item=self.currentItem()
        if item is None:return
        record=self.owner.documents[self.document]; index=item.data(Qt.UserRole)
        entry=record['history'].entries[index]
        token=entry.setdefault('token',uuid.uuid4().hex)
        mime=QMimeData(); mime.setData(MIME,json.dumps({'document':record['id'],'token':token}).encode())
        class Cancellation(CheckpointDropReceiver):
            cancelled=False
            def eventFilter(self,watched,event):
                if event.type()==QEvent.KeyPress and event.key()==Qt.Key_Escape:self.cancelled=True
                return super().eventFilter(watched,event)
        guard=Cancellation(self.owner);app=QApplication.instance();app.installEventFilter(guard)
        try:
            drag=QDrag(self);drag.setMimeData(mime);action=drag.exec(Qt.CopyAction)
        finally:app.removeEventFilter(guard)
        # Dropping over an image has no drop receiver. Treat release outside
        # this history panel as extraction, while honoring Escape and receivers.
        position=QCursor.pos();area=self.owner.mdi.viewport()
        if action==Qt.IgnoreAction and not guard.cancelled and area.rect().contains(area.mapFromGlobal(position)) and not self.rect().contains(self.mapFromGlobal(position)):
            owner=self.owner;document_id=record['id'];local=area.mapFromGlobal(position)
            def extract():
                for window,record in owner.documents.items():
                    if record['id']==document_id:
                        for index,entry in enumerate(record['history'].entries):
                            if entry.get('token')==token:owner.copy_checkpoint(window,index,local);return
            QTimer.singleShot(0,owner,extract)
    def menu(self,pos):
        item=self.itemAt(pos)
        if item is None:return
        index=item.data(Qt.UserRole); w=self.owner; menu=QMenu(self)
        from core.checkpoint_links import selected,link_selected,unlink
        entry=w.documents[self.document]['history'].entries[index]
        choices=selected(w)
        if any(window is self.document and i==index for window,i,_ in choices):
            action=menu.addAction(w.trtext('Связать слои','Link layers'))
            action.setEnabled(len(choices)>1 and not heavy_job_running(w))
            def connect_layers():
                try:link_selected(w)
                except Exception as error:QMessageBox.warning(w,'Astra',str(error))
            action.triggered.connect(connect_layers)
        group=entry.get('link_id')
        if group:
            menu.addAction(w.trtext('Развязать слои','Unlink layers'),lambda:unlink(w,group))
        menu.addSeparator()
        menu.addAction(w.trtext('Открыть копию','Open copy'),lambda:w.copy_checkpoint(self.document,index))
        delete=menu.addAction(w.trtext('Удалить этот и более новые снимки','Delete this and newer snapshots'),lambda:w.delete_checkpoints(self.document,index))
        delete.setEnabled(index>0 and not heavy_job_running(w))
        menu.exec(self.mapToGlobal(pos))

class DocumentWindow(QMdiSubWindow):
    def closeEvent(self,event):
        area=self.mdiArea()
        owner=getattr(area,'owner',None)
        if owner is not None and self in owner.documents:
            if heavy_job_running(owner):
                QMessageBox.information(owner,'Astra',owner.trtext('Дождитесь завершения обработки.','Wait for processing to finish.'))
                event.ignore();return
            if not owner.confirm_image_close(self):
                event.ignore();return
            record=owner.documents.pop(self)
            record['history'].close()
            self.hide()
            area.snap.slots.pop(self,None)
            area.removeSubWindow(self)
            self.deleteLater()
            if not owner.documents:
                owner.data=None;owner.count=None
                owner.image=owner.empty_image;owner.info=owner.empty_info;owner.viewwindow=owner.empty_viewwindow
                owner.tool_panel.sync_tool_title()
            event.accept();return
        super().closeEvent(event)
    def mousePressEvent(self, event):
        title_height = self.style().pixelMetric(QStyle.PM_TitleBarHeight, None, self)
        if event.button() == Qt.LeftButton and event.position().y() < title_height:
            right = self.width() - event.position().x()
            size = title_height
            if right <= size:
                self.close(); event.accept(); return
            if right <= size * 2:
                self.mdiArea().snap.toggle_maximized(self)
                event.accept(); return
            if right <= size * 3:
                if self.isMinimized(): self.showNormal()
                else: self.showMinimized()
                event.accept(); return
        if event.button() == Qt.LeftButton and event.position().y() < title_height:
            area = self.mdiArea()
            area.snap.begin(self)
            if self.isMaximized():
                fraction = event.position().x() / max(1, self.width())
                self.showNormal()
                cursor = area.viewport().mapFromGlobal(event.globalPosition().toPoint())
                self.move(cursor.x() - round(self.width() * fraction), cursor.y() - title_height // 2)
            self._caption_drag = (event.globalPosition().toPoint(), self.pos())
            area.setActiveSubWindow(self)
            self.raise_()
            if not self.isMinimized():area.snap.show_edge_hints()
            event.accept(); return
        super().mousePressEvent(event)
    def mouseDoubleClickEvent(self,event):
        title_height=self.style().pixelMetric(QStyle.PM_TitleBarHeight,None,self)
        if event.button()==Qt.LeftButton and event.position().y()<title_height:
            self._caption_drag=None
            self.mdiArea().snap.cancel()
            self.mdiArea().snap.toggle_maximized(self)
            event.accept();return
        super().mouseDoubleClickEvent(event)
    def mouseMoveEvent(self, event):
        if getattr(self, '_caption_drag', None) is not None:
            origin, position = self._caption_drag
            target = position + event.globalPosition().toPoint() - origin
            area = self.mdiArea().viewport().rect()
            self.move(max(0,min(target.x(),area.width()-self.width())),
                      max(0,min(target.y(),area.height()-self.height())))
            if not self.isMinimized():
                self.mdiArea().snap.update(self.mdiArea().viewport().mapFromGlobal(event.globalPosition().toPoint()))
            event.accept(); return
        super().mouseMoveEvent(event)
    def mouseReleaseEvent(self, event):
        if getattr(self, '_caption_drag', None) is not None:
            self._caption_drag = None
            self.mdiArea().snap.finish(self)
            event.accept(); return
        super().mouseReleaseEvent(event)

class Workspace(QMdiArea):
    def __init__(self,owner):
        super().__init__(); self.owner=owner; self.setAcceptDrops(True)
        from core.window_snap import WindowSnap
        self.snap=WindowSnap(self)
        self.subWindowActivated.connect(self.highlight_active_window)
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'snap'):self.snap.resize()
    def highlight_active_window(self,active):
        for window in self.subWindowList():
            selected=window is active
            if window.property('activeDocument')==selected:continue
            window.setProperty('activeDocument',selected)
            window.style().unpolish(window)
            window.style().polish(window)
            window.update()
    def addSubWindow(self, widget, flags=Qt.WindowFlags()):
        flags |= (Qt.SubWindow | Qt.WindowTitleHint | Qt.WindowSystemMenuHint |
                  Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        window = DocumentWindow(None, flags)
        window.setWidget(widget)
        super().addSubWindow(window)
        return window
    def dropped_images(self,event):
        from pathlib import Path
        from core.photo_io import extensions
        supported={'.fit','.fits','.fts','.tif','.tiff','.xisf',
                   '.cr2','.cr3','.nef','.arw','.dng','.raf','.rw2','.orf','.pef'}
        supported.update(extensions())
        return [url.toLocalFile() for url in event.mimeData().urls()
                if url.isLocalFile() and Path(url.toLocalFile()).is_file()
                and Path(url.toLocalFile()).suffix.lower() in supported]
    def dragEnterEvent(self,event):
        if event.mimeData().hasFormat(MIME) or self.dropped_images(event):event.setDropAction(Qt.CopyAction);event.accept()
        else:event.ignore()
    def dragMoveEvent(self,event):
        if event.mimeData().hasFormat(MIME) or self.dropped_images(event):
            event.setDropAction(Qt.CopyAction);event.accept()
        else:event.ignore()
    def dropEvent(self,event):
        if not event.mimeData().hasFormat(MIME):
            paths=self.dropped_images(event)
            if paths:
                from PySide6.QtCore import QTimer
                # Finish the Windows drag session before opening files or dialogs.
                event.setDropAction(Qt.CopyAction);event.accept()
                QTimer.singleShot(0,self,lambda:[self.owner.open_image_path(path) for path in paths])
                return
            event.ignore();return
        try:
            payload=json.loads(bytes(event.mimeData().data(MIME)))
            for window,record in list(self.owner.documents.items()):
                if record['id']!=payload['document']:continue
                for index,entry in enumerate(record['history'].entries):
                    if entry.get('token')==payload['token']:
                        self.owner.copy_checkpoint(window,index,event.position().toPoint())
                        event.setDropAction(Qt.CopyAction);event.accept();return
        except (ValueError,KeyError,TypeError):pass
        event.ignore()

class LeftSizeGrip(QSizeGrip):
    def __init__(self,window):
        super().__init__(window); self.target=window; set_em_size(self,'setFixedSize',1.0,1.0); self.setCursor(Qt.SizeBDiagCursor)
    def paintEvent(self,event):
        painter=QPainter(self); painter.setPen(self.palette().color(QPalette.Text))
        for length in (4,8,12):painter.drawLine(2,14-length,2+length,14)
    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:
            self.origin=event.globalPosition().toPoint(); self.bounds=self.target.geometry();event.accept()
    def mouseMoveEvent(self,event):
        if event.buttons() & Qt.LeftButton and hasattr(self,'origin'):
            delta=event.globalPosition().toPoint()-self.origin; rect=self.bounds
            width=max(self.target.minimumSizeHint().width(),240,rect.width()-delta.x())
            height=max(self.target.minimumSizeHint().height(),180,rect.height()+delta.y())
            self.target.setGeometry(rect.right()-width+1,rect.top(),width,height);event.accept()

class CheckpointMixin:
    def extract_luminance(self,window=None):
        window=window or self.mdi.activeSubWindow()
        if window not in self.documents:return
        data=self.documents[window]['data']
        if data.ndim!=3 or data.shape[-1]!=3:
            QMessageBox.information(self,'Astra',self.trtext('Нужно трёхканальное RGB-изображение.','A three-channel RGB image is required.'));return
        from core.resources import require_memory
        try:
            require_memory(data.shape[0]*data.shape[1]*8+16*1024**2,localize('Извлечение яркости'))
            result=np.empty(data.shape[:2],dtype=np.result_type(data.dtype,np.float32))
            # Linear Rec.709/sRGB luminance; bounded conversion temporaries.
            for y in range(0,data.shape[0],128):
                block=data[y:y+128].astype(result.dtype,copy=False)
                result[y:y+128]=block[...,0]*.2126+block[...,1]*.7152+block[...,2]*.0722
        except (MemoryError,ValueError) as error:
            QMessageBox.warning(self,'Astra',str(error));return
        self.data=result;self.count=None;self.next_image_title=window.windowTitle()+' · L';self.showimage()
    def copy_checkpoint(self,window,index,position=None):
        record=self.documents[window]
        try:data,count=record['history'].snapshot(index,record['data'],record['count'])
        except Exception as error:QMessageBox.warning(self,'Astra',str(error));return
        self.data,self.count=data,count; self.next_image_title=window.windowTitle()+self.trtext(' · копия',' · copy')+' · '+str(index)
        self.showimage(tile=False)
        self.documents[self.viewwindow]['channel']=record.get('channel');self.update_history(self.viewwindow)
        copy=self.viewwindow;copy.showNormal()
        area=self.mdi.viewport().size();copy.resize(round(area.width()*.55),round(area.height()*.6))
        self.documents[copy]['history_panel'].parentWidget().setSizes([115,400])
        if position is None:position=window.pos()+QPoint(24,24)
        copy.move(max(0,min(position.x(),area.width()-copy.width())),max(0,min(position.y(),area.height()-copy.height())))
        copy.raise_();self.mdi.setActiveSubWindow(copy)
    def delete_checkpoints(self,window,index):
        if index<=0 or heavy_job_running(self):return
        record=self.documents[window]; history=record['history']
        if QMessageBox.question(self,'Astra',self.trtext('Удалить выбранный снимок и все более новые?','Delete this snapshot and all newer snapshots?'))!=QMessageBox.Yes:return
        try:
            if history.index>=index:
                data,count=history.snapshot(index-1,record['data'],record['count'])
                history.index=index-1
                record.update(data=data,count=count)
                for key in ('preview_data','preview_owner','wcs_header','nebula_samples'):
                    record.pop(key,None)
                record['image'].annotations=[]
                record['image'].annotations_visible=False
                if record.get('mask') is not None and record['mask'].shape!=data.shape[:2]:
                    record.pop('mask',None);record['mask_enabled']=False
                record['info'].setText(f'{data.shape} · {data.dtype}')
            history.truncate(index-1)
        except Exception as error:
            QMessageBox.warning(self,'Astra',str(error));return
        self.checkpoint_selection={}
        from core.checkpoint_links import refresh
        refresh(self)
        self.mdi.setActiveSubWindow(window)
        self.activate_document(window)
        self.render()
    def unique_image_title(self,name,exclude=None):
        from pathlib import Path
        from core.photo_io import extensions
        suffix=Path(name).suffix
        if suffix.lower() in {'.fit','.fits','.fts','.xisf','.tif','.tiff',*extensions()}:
            name=name[:-len(suffix)]
        titles={w.windowTitle().casefold() for w in self.documents if w is not exclude}
        candidate=name
        number=2
        while candidate.casefold() in titles:
            candidate=name+self.trtext(' · копия ',' · copy ')+str(number)
            number+=1
        return candidate
    def rename_document(self,window=None):
        window=window or self.mdi.activeSubWindow()
        if window not in self.documents:return
        name,ok=QInputDialog.getText(self,self.trtext('Переименовать изображение','Rename image'),self.trtext('Название','Name'),text=window.windowTitle())
        if ok and name.strip():window.setWindowTitle(self.unique_image_title(name.strip(),window));self.activate_document(window)
    def split_rgb(self,window=None):
        window=window or self.mdi.activeSubWindow()
        if window not in self.documents:return
        record=self.documents[window]; data=record['data']; name=window.windowTitle()
        if data.ndim!=3 or data.shape[-1]!=3:
            QMessageBox.information(self,'RGB',self.trtext('Нужно трёхканальное RGB-изображение.','A three-channel RGB image is required.'));return
        from core.preview_levels import checkpoint_transfer,denoise_limits
        transfer=checkpoint_transfer(record) or record.get('display_transfer')
        if record.get('stretch',False) and transfer is None:
            limits=denoise_limits(record)
            if limits is not None:transfer=(*limits,record.get('strength',20))
        display={key:record.get(key,default) for key,default in
                 (('stretch',False),('strength',20),('auto_stretch',False))}
        display['transfer']=transfer if display['stretch'] else None
        for index,channel in enumerate('RGB'):
            self.data=data[...,index].copy(); self.count=None; self.next_image_title=name+' · '+channel
            created=self.showimage(tile=False,display=display)
            self.documents[created]['channel']=channel
            self.update_history(created)
        self.mdi.tileSubWindows()
