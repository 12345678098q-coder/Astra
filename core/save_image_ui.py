"""Save format selection and unsaved-image confirmation."""
from pathlib import Path
import numpy as np
from PySide6.QtWidgets import QDialog,QFormLayout,QComboBox,QLabel,QDialogButtonBox,QFileDialog,QMessageBox
from core.image_save import write_image


class SaveImageMixin:
    def confirm_image_close(self,window):
        record=self.documents.get(window)
        if record is None:return True
        history=record['history']
        if record.get('saved_entry') is history.entries[history.index]:return True
        tr=self.trtext
        dialog=QMessageBox(QMessageBox.Question,'Astra',
            tr('Сохранить изменения в фото «','Save changes to “')+window.windowTitle()+tr('»?','”?'),
            QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel,self)
        for role,ru,en in ((QMessageBox.Save,'Сохранить','Save'),(QMessageBox.Discard,'Не сохранять','Don’t save'),(QMessageBox.Cancel,'Отмена','Cancel')):
            dialog.button(role).setText(tr(ru,en))
        dialog.setDefaultButton(QMessageBox.Save)
        dialog.setEscapeButton(QMessageBox.Cancel)
        answer=dialog.exec()
        if answer==QMessageBox.Cancel:return False
        return self.save_document(window) if answer==QMessageBox.Save else True

    def save_document(self,window):
        record=self.documents.get(window)
        if record is None:return False
        tr=self.trtext
        path,selected=QFileDialog.getSaveFileName(self,tr('Сохранить изображение','Save image'),record.get('file_path',window.windowTitle()),'FITS (*.fits);;TIFF (*.tiff)')
        if not path:return False
        suffix='.tiff' if selected.startswith('TIFF') else '.fits'
        accepted=('.tif','.tiff') if suffix=='.tiff' else ('.fit','.fits','.fts')
        if Path(path).suffix.lower() not in accepted:
            path+=suffix
            if Path(path).exists() and QMessageBox.question(self,'Astra',tr('Заменить файл?','Replace file?')+'\n'+path)!=QMessageBox.Yes:return False
        dialog=QDialog(self)
        dialog.setWindowTitle(tr('Параметры сохранения','Save options'))
        form=QFormLayout(dialog)
        depth=QComboBox()
        for label,value in [('32 бит float','float32'),('64 бит float','float64'),('8 бит','uint8'),('16 бит','uint16'),('32 бит integer','uint32')]:
            depth.addItem(label,value)
        default='float64' if record['data'].dtype.itemsize>4 else 'float32'
        depth.setCurrentIndex(max(0,depth.findData(self.settings.value('files/save_depth',default))))
        form.addRow(tr('Битность','Bit depth'),depth)
        ranges=QComboBox()
        for ru,en,value in [('0…1 → полный диапазон','0…1 → full range','unit'),('Сохранить значения пикселей','Keep pixel values','raw'),('Мин…макс → полный диапазон','Min…max → full range','image')]:
            ranges.addItem(tr(ru,en),value)
        sample=record['data'][::max(1,record['data'].shape[0]//128),::max(1,record['data'].shape[1]//128)]
        finite=sample[np.isfinite(sample)]
        ranges.setCurrentIndex(0 if finite.size and finite.min()>=0 and finite.max()<=1 else 1)
        form.addRow(tr('Преобразование в целые числа','Integer conversion'),ranges)
        note=QLabel(tr('При сохранении в целых числах значения вне выбранного диапазона обрезаются.','Integer saving clips values outside the selected range.'))
        note.setWordWrap(True)
        form.addRow(note)
        def update():
            integer=depth.currentData().startswith('uint')
            ranges.setEnabled(integer)
            note.setVisible(integer)
        depth.currentIndexChanged.connect(update)
        update()
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(tr('Сохранить','Save'))
        buttons.button(QDialogButtonBox.Cancel).setText(tr('Отмена','Cancel'))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec()!=QDialog.Accepted:return False
        try:
            from core.resources import require_memory
            bytes_per_pixel=24 if depth.currentData().startswith('uint') else np.dtype(depth.currentData()).itemsize*2
            require_memory(record['data'].size*bytes_per_pixel,tr('Сохранение изображения','Saving image'))
            write_image(path,record['data'],depth.currentData(),ranges.currentData(),record['count'],record.get('wcs_header'))
        except Exception as error:
            QMessageBox.warning(self,tr('Ошибка сохранения','Save error'),str(error))
            return False
        history=record['history']
        record['saved_entry']=history.entries[history.index]
        record['file_path']=path
        self.settings.setValue('files/save_depth',depth.currentData())
        self.statusBar().showMessage(tr('Сохранено: ','Saved: ')+path)
        return True
