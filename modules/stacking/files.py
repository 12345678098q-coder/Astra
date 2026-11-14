from core.i18n import localize
import json
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import *
from astropy.io import fits
from core.image_io import read
from .masters import category_label, is_master
FILTER='Астроизображения (*.fit *.fits *.fts *.tif *.tiff *.xisf);;RAW фотоаппаратов и другие файлы (*.*)'

class StackFilesMixin:
    def stack_reference_path(self):
        lights=self.lists['Lights']
        checked=[lights.item(i) for i in range(lights.count()) if lights.item(i).data(Qt.UserRole) is not False]
        reference=next((item for item in checked if item.data(Qt.UserRole+3)),checked[0] if checked else None)
        return reference.text() if reference else None

    def stack_file_context_menu(self,name,pos):
        table=self.tables[name];item=table.itemAt(pos)
        if name!='Lights' or item is None:return
        row=item.row();menu=QMenu(table)
        action=menu.addAction(self.trtext('Сделать опорным кадром','Set as reference frame'))
        if menu.exec(table.viewport().mapToGlobal(pos))==action:
            lights=self.lists['Lights']
            for i in range(lights.count()):lights.item(i).setData(Qt.UserRole+3,i==row)
            lights.item(row).setData(Qt.UserRole,True)
            self.refresh_files();table.selectRow(row)

    def master_paths(self):
        return [lst.item(i).text() for lst in self.lists.values() for i in range(lst.count()) if lst.item(i).data(Qt.UserRole+1)]

    def add_master(self):
        name=self.current_category()
        if name=='Lights':
            QMessageBox.information(self,localize('Мастер-кадр'),localize('Выберите дарки, флеты или дарк-флеты.', 'Select Darks, Flats or Dark flats.')); return
        path,_=QFileDialog.getOpenFileName(self,localize('Готовый мастер ')+category_label(name),str(self.settings.value('stack/folders/'+name,'')),localize(FILTER))
        if not path:return
        lst=self.lists[name]
        if lst.count() and QMessageBox.question(self,localize('Мастер-кадр'),localize('Заменить кадры этой категории готовым мастером?'))!=QMessageBox.Yes:return
        self.settings.setValue('stack/folders/'+name,str(Path(path).parent))
        lst.clear(); item=QListWidgetItem(path); item.setData(Qt.UserRole+1,True); lst.addItem(item)
        self.refresh_files(); self.select_preview()

    def current_category(self): return list(self.lists)[max(0,self.categories.currentRow())]

    def refresh_files(self,*args):
        if not hasattr(self,'tables'):return
        for index,(name,lst) in enumerate(self.lists.items()):
            self.categories.item(index).setText(f'{category_label(name)} ({lst.count()})')
            table=self.tables[name]; table.blockSignals(True); table.setRowCount(lst.count())
            for row in range(lst.count()):
                source=lst.item(row); path=source.text()
                if source.data(Qt.UserRole) is None: source.setData(Qt.UserRole,True)
                if path not in self.metadata:
                    try:
                        size=Path(path).stat().st_size/1048576; exposure=gain=dimensions='-'
                        if path.lower().endswith(('.fit','.fits','.fts')):
                            h=fits.getheader(path); exposure=str(h.get('EXPTIME',h.get('EXPOSURE','-'))); gain=str(h.get('ISOSPEED',h.get('GAIN','-'))); dimensions=f"{h.get('NAXIS1','?')} × {h.get('NAXIS2','?')}"
                        self.metadata[path]=(exposure,gain,dimensions,f'{size:.1f}')
                    except Exception:self.metadata[path]=('-','-','-','-')
                try:master=is_master(path,self.master_paths())
                except Exception:master=False
                reference=name=='Lights' and path==self.stack_reference_path()
                prefix=self.trtext('★ Опорный · ','★ Reference · ') if reference else localize('★ Мастер · ') if master else ''
                values=[prefix+Path(path).name,*self.metadata[path],str(Path(path).parent)]
                for column,value in enumerate(values):
                    item=QTableWidgetItem(value); item.setToolTip(path)
                    if reference:
                        font=item.font();font.setBold(True);item.setFont(font)
                        color=table.palette().highlight().color();color.setAlpha(60);item.setBackground(color)
                    if column==0:
                        item.setFlags(item.flags()|Qt.ItemIsUserCheckable); item.setCheckState(Qt.Checked if source.data(Qt.UserRole) else Qt.Unchecked)
                    table.setItem(row,column,item)
            table.blockSignals(False)

    def check_file(self,name,item):
        if item.column()==0:self.lists[name].item(item.row()).setData(Qt.UserRole,item.checkState()==Qt.Checked)
        if name=='Lights':self.refresh_files()

    def remove_files(self):
        name=self.current_category(); rows=sorted({i.row() for i in self.tables[name].selectedIndexes()},reverse=True)
        for row in rows:self.lists[name].takeItem(row)
        self.select_preview()

    def mark_files(self,value):
        name=self.current_category()
        for row in range(self.lists[name].count()):self.lists[name].item(row).setData(Qt.UserRole,value)
        self.refresh_files()

    def clear_files(self):
        if QMessageBox.question(self,'Astra',self.trtext('Очистить текущую категорию?','Clear this category?'))==QMessageBox.Yes:
            self.lists[self.current_category()].clear(); self.select_preview()

    def refresh_presets(self):
        self.file_presets=json.loads(self.settings.value('file_presets','{}'))
        self.presets.clear(); self.presets.addItems(sorted(self.file_presets))

    def save_list(self):
        name,ok=QInputDialog.getText(self,self.trtext('Сохранить список','Save file list'),self.trtext('Название','Name'))
        if not ok or not name.strip(): return
        name=name.strip()
        if name in self.file_presets and QMessageBox.question(self,'Astra',self.trtext('Заменить существующий список?','Replace existing list?'))!=QMessageBox.Yes:return
        self.file_presets[name]={n:[{'path':l.item(i).text(),'master':bool(l.item(i).data(Qt.UserRole+1)),'checked':l.item(i).data(Qt.UserRole) is not False,'weight':l.item(i).data(Qt.UserRole+2) or 1,'reference':bool(l.item(i).data(Qt.UserRole+3))} for i in range(l.count())] for n,l in self.lists.items()}
        self.settings.setValue('file_presets',json.dumps(self.file_presets,ensure_ascii=False)); self.refresh_presets(); self.presets.setCurrentText(name)

    def load_list(self):
        value=self.file_presets.get(self.presets.currentText())
        if value is None:return
        if any(l.count() for l in self.lists.values()) and QMessageBox.question(self,'Astra',self.trtext('Заменить текущие списки файлов?','Replace current file lists?'))!=QMessageBox.Yes:return
        missing=[]
        for name,l in self.lists.items():
            l.clear()
            for entry in value.get(name,[]):
                path=entry['path'] if isinstance(entry,dict) else entry
                item=QListWidgetItem(path); item.setData(Qt.UserRole+1,bool(entry.get('master')) if isinstance(entry,dict) else False); item.setData(Qt.UserRole,entry.get('checked',True) if isinstance(entry,dict) else True);item.setData(Qt.UserRole+2,entry.get('weight',1) if isinstance(entry,dict) else 1);item.setData(Qt.UserRole+3,entry.get('reference',False) if isinstance(entry,dict) else False);l.addItem(item)
                if not Path(path).is_file():missing.append(path)
        self.select_preview()
        if missing: QMessageBox.warning(self,self.trtext('Файлы не найдены','Missing files'),'\n'.join(missing))

    def delete_list(self):
        name=self.presets.currentText()
        if name in self.file_presets and QMessageBox.question(self,'Astra',self.trtext('Удалить сохранённый список?','Delete saved file list?'))==QMessageBox.Yes:
            del self.file_presets[name]; self.settings.setValue('file_presets',json.dumps(self.file_presets,ensure_ascii=False)); self.refresh_presets()

    def add(self,name):
        selected=localize('RAW фотоаппаратов и другие файлы (*.*)') if self.bayer.currentData()=='RAW фотоаппарата' else localize('Астроизображения (*.fit *.fits *.fts *.tif *.tiff *.xisf)')
        paths,_=QFileDialog.getOpenFileNames(self,localize('Выбрать ')+category_label(name),str(self.settings.value('stack/folders/'+name,'')),localize(FILTER),selected); l=self.lists[name]
        if paths:self.settings.setValue('stack/folders/'+name,str(Path(paths[0]).parent))
        existing={l.item(i).text() for i in range(l.count())}
        l.addItems([p for p in paths if p not in existing])
        self.select_preview()

    def auto(self):
        lights=self.lists['Lights']
        if not lights.count():
            QMessageBox.information(self,localize('Авто'),localize('Сначала добавьте light-кадры.')); return
        try:
            a,h=read(lights.item(0).text())
            value=str(h.get('BAYERPAT','')).upper().strip()
            if not value and isinstance(h.get('FITSKeywords'),dict):
                values=h['FITSKeywords'].get('BAYERPAT',[])
                if values: value=str(values[0].get('value','')).upper().strip()
            if h.get('RAW_CAMERA'): self.bayer.setCurrentIndex(self.bayer.findData('RAW фотоаппарата'))
            elif value in ('RGGB','BGGR','GRBG','GBRG'): self.bayer.setCurrentText(value)
            elif a.ndim==3:
                QMessageBox.information(self,localize('Авто'),localize('Цветной трёхканальный кадр. В настройках сложения доступны моно, RAW фотоаппарата и Bayer-кадры.')); return
            else:
                QMessageBox.information(self,localize('Авто'),localize('В файле нет BAYERPAT. Для моно выберите «Моно», для сырого цвета укажите паттерн камеры вручную.')); return
            self.stack_options['hot']=True; self.stack_options['cold']=True
            self.log.appendPlainText(localize('Авто: ')+self.bayer.currentText()+localize(', коррекция горячих и холодных пикселей включена.'))
        except Exception as e: QMessageBox.warning(self,localize('Авто'),str(e))
