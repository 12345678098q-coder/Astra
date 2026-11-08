import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import tifffile
from PySide6.QtCore import QProcess,QSettings
from PySide6.QtWidgets import QApplication,QLineEdit,QCheckBox,QPushButton
from app import Window
from processes.options import SCHEMAS,values_for
from processes.option_form import OptionForm
from processes import graxpert,rcastro
from processes.starnet.backend import command

class ProcessOptionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.w=Window();self.w.auto_update_tools=lambda:None
        with patch('app.QSettings',return_value=QSettings(self.temp.name+'/prefs.ini',QSettings.IniFormat)):self.w.setup_workspace()
        self.w.settings=QSettings(self.temp.name+'/prefs.ini',QSettings.IniFormat);self.w.show();self.app.processEvents()
    def tearDown(self):self.w.close();self.temp.cleanup()
    def test_forms_and_persistence(self):
        w=self.w
        self.assertFalse(w.tool_panel.entries)
        for key in ('stretch',*SCHEMAS):w.open_tool(key)
        self.assertEqual(len(w.tool_panel.entries),len(SCHEMAS)+1)
        bxt=w.tool_panel.forms['rcastro:bxt'];bxt.fields['sharpen_stars'].setValue(.2)
        self.assertEqual(OptionForm(w,'rcastro:bxt').values()['sharpen_stars'],.2)
        bxt.fields['auto_psf'].setChecked(False);bxt.fields['psf'].setValue(3)
        bxt.fields['auto_psf'].setChecked(True);self.assertEqual(bxt.values()['psf'],0)
        bxt.reset();self.assertEqual(bxt.values(),values_for('rcastro:bxt'))
        self.assertIsNotNone(w.tool_panel.entries['starnet'][0].findChild(OptionForm))
    def test_commands(self):
        bxt=rcastro.command('bxt','in.tif',{'auto_psf':False,'psf':3,'sharpen_stars':.1},'out.tif')
        self.assertIn('--no-auto-nonstellar-psf',bxt);self.assertEqual(bxt[bxt.index('--nonstellar-diameter')+1],'3')
        for op in ('background-extraction','denoising','deconv-obj','deconv-stellar'):
            args=graxpert.command(op,'in.tif','out')
            self.assertEqual(args[1],op)
        with self.assertRaises(ValueError):graxpert.command('denoising','in','out',{'strength':2})
        with self.assertRaises(ValueError):command('in','out',{'stride':255})
        args=command('in','out',{'mode':2,'upsample':True,'unscreen':True},'stars')
        self.assertIn('--unscreen',args);self.assertIn('--upsample',args);self.assertNotIn('--linear',args)
    def test_external_options_and_two_outputs(self):
        w=self.w;original=np.full((32,32,3),10,dtype=np.float32);w.data=original;w.showimage();target=w.viewwindow
        calls=[]
        def fake_start(proc,exe,args):
            calls.append(args)
            path=Path(args[args.index('--output')+1]);tifffile.imwrite(path,original+5,photometric='rgb')
            tifffile.imwrite(path.with_name(path.stem+'-stars.tif'),original-5,photometric='rgb')
            proc.finished.emit(0,QProcess.NormalExit)
        with patch('processes.tool_updates.find_tool',return_value=Path(sys.executable)),patch.object(QProcess,'start',fake_start):
            w.run_external('rcastro','sxt',{'stars':True,'unscreen':True})
        self.assertIn('--stars',calls[0]);self.assertNotIn('--unscreen',calls[0])
        np.testing.assert_array_equal(w.documents[target]['data'],original+5)
        self.assertEqual(len(w.documents),2)
        w.mdi.setActiveSubWindow(target);w.history_step(-1);np.testing.assert_array_equal(w.data,original)

    def test_starnet_embedded_execution(self):
        from processes.starnet import backend
        from astropy.io import fits
        w=self.w;original=np.linspace(.01,.8,512*512,dtype=np.float32).reshape(512,512)
        w.data=original;w.showimage();source=w.viewwindow
        source.setWindowTitle('nebula.FTS')
        # A stale configured output must never trigger writes to user files.
        old_output=Path(self.temp.name)/'starless.fits';old_output.write_bytes(b'untouched')
        w.settings.setValue('process_options/starnet_output',str(old_output))
        exe=Path(self.temp.name)/'starnet2.exe';exe.touch();exe.with_name('LICENSE.txt').write_text('Test license',encoding='utf-8')
        exe.with_name('StarNet2_weights.onnx').write_bytes(b'test model')
        w.open_tool('starnet');panel=w.tool_panel.entries['starnet'][0]
        self.assertIsNone(panel.findChild(QLineEdit,'starnet_output'))
        self.assertFalse(any('Выбрать файл' in button.text() or 'Choose file' in button.text() for button in panel.findChildren(QPushButton)))
        panel.findChild(QCheckBox,'starnet_license').setChecked(True)
        calls=[]
        def fake_start(proc,path,args):
            calls.append(args)
            fits.writeto(args[args.index('--output')+1],original*.8)
            fits.writeto(args[args.index('--mask')+1],original*.2)
            proc.finished.emit(0,QProcess.NormalExit)
        with patch.object(backend,'executable',return_value=exe),patch.object(QProcess,'start',fake_start):
            panel.findChild(QPushButton,'starnet_preview').click()
            self.assertEqual(len(w.documents),1);np.testing.assert_array_equal(w.documents[source]['data'],original)
            self.assertEqual(len(w.documents[source]['history'].entries),1);self.assertTrue(w.temporary_preview.isVisible())
            panel.findChild(QPushButton,'starnet_run').click()
        self.assertEqual(len(calls),2);self.assertEqual(old_output.read_bytes(),b'untouched')
        np.testing.assert_allclose(w.documents[source]['data'],original*.8)
        self.assertEqual(len(w.documents),2);self.assertIsNone(w.starnet_process)
        self.assertEqual(source.windowTitle(),'nebula.FTS');self.assertEqual(w.viewwindow.windowTitle(),'star_mask')
        np.testing.assert_allclose(w.data,original*.2)
        self.assertFalse(Path(calls[-1][calls[-1].index('--output')+1]).exists())
        w.mdi.setActiveSubWindow(source);w.history_step(-1);np.testing.assert_array_equal(w.data,original)

if __name__=='__main__':unittest.main()
