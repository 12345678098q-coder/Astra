import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from scipy.signal import convolve2d
from scipy.fft import rfft2,irfft2
from astropy.io import fits
from processes.native.motion import line_psf,correct_motion,estimate_motion,correct_stack_light
from processes.native.processing import apply_operation


def scene(shape=(256,320)):
    y,x=np.mgrid[:shape[0],:shape[1]];a=np.full(shape,.1)
    for cy in range(40,shape[0]-20,55):
        for cx in range(45,shape[1]-20,65):a+=np.exp(-((y-cy)**2+(x-cx)**2)/(2*1.8**2))
    return a


class MotionTests(unittest.TestCase):
    def test_recovery_and_auto(self):
        a=scene();b=convolve2d(a,line_psf(7,25),mode='same',boundary='symm')
        b+=np.random.default_rng(5).normal(0,.0005,a.shape);before=b.copy()
        estimate=estimate_motion(b)
        self.assertGreaterEqual(estimate['stars'],5);self.assertAlmostEqual(estimate['length'],7,delta=.7);self.assertAlmostEqual(estimate['angle'],25,delta=2)
        out=correct_motion(b,dict(auto=True,strength=1,regularization=.01))
        self.assertLess(np.mean((out-a)**2),np.mean((b-a)**2)*.4)
        wrong=correct_motion(b,dict(length=7,angle=115,strength=1,regularization=.01))
        self.assertLess(np.mean((out-a)**2),np.mean((wrong-a)**2))
        np.testing.assert_array_equal(b,before)

    def test_dc_rgb_nonfinite_mask_cancel_and_validation(self):
        a=np.full((64,90,3),[-20.,100.,10000.]);a[30,30,0]=np.nan;a[20,20,1]=np.inf
        out=correct_motion(a,dict(length=8,angle=45))
        np.testing.assert_allclose(out,a,atol=1e-10,equal_nan=True)
        b=scene();b[20,20]=np.nan
        np.testing.assert_array_equal(apply_operation(b,'motion',{},np.zeros(b.shape)),b)
        np.testing.assert_array_equal(correct_motion(b,dict(strength=0)),b)
        with self.assertRaises(InterruptedError):correct_motion(b,{},cancel=lambda:True)
        for settings in (dict(length=21),dict(regularization=0),dict(strength=-1),dict(angle=np.nan)):
            with self.assertRaises(ValueError):correct_motion(b,settings)
        with self.assertRaises(ValueError):estimate_motion(np.ones((64,64)))
        logs=[];self.assertIs(correct_stack_light(a,dict(motion_enabled=True,motion_auto=True),logs.append),a);self.assertTrue(logs)

    def test_tile_boundaries_match_full_fft(self):
        a=scene((580,660));psf=line_psf(7,32)
        b=convolve2d(a,psf,mode='same',boundary='symm');out=correct_motion(b,dict(length=7,angle=32,regularization=.03,strength=1))
        padded=np.pad(b,64,mode='reflect');kernel=np.zeros(padded.shape);kh,kw=psf.shape;kernel[:kh,:kw]=psf
        kernel=np.roll(kernel,(-(kh//2),-(kw//2)),axis=(0,1));transfer=rfft2(kernel)
        expected=irfft2(rfft2(padded)*1.03*transfer.conj()/(np.abs(transfer)**2+.03),s=padded.shape)[64:-64,64:-64]
        np.testing.assert_allclose(out,expected,atol=2e-5,rtol=0)

    def test_stack_applies_to_lights_only_and_never_trails(self):
        from modules.stacking.engine import stack
        a=scene((96,112)).astype('float32')
        with tempfile.TemporaryDirectory() as folder:
            files=[]
            for i in range(2):
                path=Path(folder)/f'light{i}.fits';fits.writeto(path,a+10);files.append(str(path))
            dark=Path(folder)/'dark.fits';fits.writeto(dark,np.full_like(a,10))
            groups={'Lights':files,'Darks':[str(dark)],'Flats':[],'Dark flats':[]}
            opts=dict(method='mean',align=False,normalize=False,hot=False,cold=False,auto_resources=False,save_masters=False,motion_enabled=True,motion_auto=False)
            inputs=[]
            def capture(data,options,log,cancel):inputs.append(data.copy());return data+2
            with patch('processes.native.motion.correct_stack_light',side_effect=capture):result,_=stack(groups,options=opts)
            self.assertEqual(len(inputs),2);np.testing.assert_allclose(inputs[0],a,atol=1e-6);np.testing.assert_allclose(result,a+2,atol=1e-6)
            with patch('processes.native.motion.correct_stack_light') as correction:stack(groups,options={**opts,'method':'trails'});correction.assert_not_called()
            np.testing.assert_array_equal(fits.getdata(files[0]),a+10)

    def test_gui_preview_apply_undo_and_single_light(self):
        from PySide6.QtWidgets import QApplication,QWidget,QPushButton,QMessageBox
        from PySide6.QtCore import QSettings
        from app import Window
        from processes.native.motion_ui import MotionPanel
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            w=Window();w.auto_update_tools=lambda:None
            with patch('app.QSettings',return_value=QSettings(folder+'/prefs.ini',QSettings.IniFormat)):w.setup_workspace()
            w.show();w.data=scene((100,120));old=w.data.copy();w.showimage();source=w.viewwindow;w.open_tool('native:motion')
            panel=w.tool_panel.entries['native:motion'][0].findChild(MotionPanel)
            errors=[]
            def wait():
                end=time.monotonic()+10
                while time.monotonic()<end:
                    app.processEvents();time.sleep(.01)
                    try:running=w.native_job.isRunning()
                    except (AttributeError,RuntimeError):running=False
                    if not running:app.processEvents();self.assertFalse(errors);return
                self.fail('timeout')
            with patch.object(QMessageBox,'warning',side_effect=lambda *args:errors.append(args[-1])):
                panel.execute(False);wait();np.testing.assert_array_equal(w.data,old)
                self.assertTrue(panel.temporary_preview.isVisible());self.assertEqual(len(w.documents),1)
                panel.cancel();self.assertFalse(panel.temporary_preview.isVisible())
                panel.execute(True);wait();self.assertEqual(w.documents[source]['history'].entries[-1]['label'],'MC')
                self.assertFalse(np.array_equal(w.data,old));w.history_step(-1);np.testing.assert_array_equal(w.data,old)
                footer=w.tool_panel.entries['native:motion'][0].findChild(QWidget,'actionFooter');buttons=footer.findChildren(QPushButton)
                self.assertEqual(buttons[0].text(),w.trtext('Предпросмотр','Preview'));self.assertEqual(buttons[-1].text(),w.trtext('Применить','Apply'))
                path=Path(folder)/'single.fits';fits.writeto(path,np.arange(40*60,dtype='float32').reshape(40,60))
                w.lists['Lights'].addItem(str(path));w.tables['Lights'].selectRow(0);w.bayer.setCurrentText('RGGB');w.open_motion_light();wait()
                self.assertEqual(w.data.shape,(40,60,3));self.assertEqual(len(w.documents),2);self.assertEqual(len(w.documents[w.viewwindow]['history'].entries),1)
                self.assertFalse(w.module.isVisible());w.grab().save('screenshots/motion-tool.png')
            w.close()

    def test_stack_settings_precision_and_dependencies(self):
        from PySide6.QtWidgets import QApplication,QDialog,QCheckBox,QDoubleSpinBox,QComboBox,QDialogButtonBox
        from PySide6.QtCore import QSettings,QTimer
        from app import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            w=Window();w.auto_update_tools=lambda:None
            with patch('app.QSettings',return_value=QSettings(folder+'/prefs.ini',QSettings.IniFormat)):w.setup_workspace()
            errors=[]
            def check_dialog():
                dialog=app.activeModalWidget()
                try:
                    self.assertIsInstance(dialog,QDialog)
                    enabled=dialog.findChild(QCheckBox,'motion_enabled');auto=dialog.findChild(QCheckBox,'motion_auto')
                    length=dialog.findChild(QDoubleSpinBox,'motion_length');noise=dialog.findChild(QDoubleSpinBox,'motion_regularization')
                    self.assertFalse(enabled.isChecked());self.assertAlmostEqual(noise.value(),.03)
                    enabled.setChecked(True);self.assertFalse(length.isEnabled());auto.setChecked(False);self.assertTrue(length.isEnabled())
                    noise.setValue(.017)
                    method=dialog.findChild(QComboBox,'method');method.setCurrentIndex(method.findData('trails'));self.assertFalse(enabled.isEnabled());self.assertFalse(noise.isEnabled())
                    method.setCurrentIndex(method.findData('mean'));self.assertTrue(noise.isEnabled())
                    dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Save).click()
                except BaseException as error:errors.append(error);dialog.reject()
            QTimer.singleShot(0,check_dialog);w.stacking_preferences()
            if errors:raise errors[0]
            self.assertAlmostEqual(w.stack_options['motion_regularization'],.017);self.assertTrue(w.stack_options['motion_enabled']);self.assertFalse(w.stack_options['motion_auto']);w.close()


if __name__=='__main__':unittest.main()
