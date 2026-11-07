import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest,tempfile,time,io
from unittest.mock import patch
import numpy as np
from astropy.wcs import WCS,Sip
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from processes.reference_background import engine
from processes.reference_background.reference import geometry,fetch,load_file,SURVEYS
from astropy.io import fits


def scene():
    yy,xx=np.mgrid[:256,:256]
    nebula=.035*np.exp(-((xx-130)**2+(yy-130)**2)/(2*18**2))
    gradient=.09*xx/255-.04*yy/255
    return .2+gradient+nebula,nebula,gradient


class ReferenceEngineTest(unittest.TestCase):
    def test_automatic_prepare_fallback_and_cancellation(self):
        from processes.reference_background.automatic import prepare
        data,_,_=scene();reference={'data':np.ones((256,256)),'step':1};header={'solved':True}
        with patch('processes.reference_background.automatic.solve',return_value=header) as solve,patch('processes.reference_background.automatic.fetch',side_effect=[ValueError('no coverage'),reference]) as fetch:
            h,r,m=prepare(data,None,None,None,'',{'protect':[],'background':[]},None,lambda:False,lambda text:None,lambda a,b:None)
        self.assertIs(h,header);self.assertIs(r,reference);self.assertGreater(m['count'],16);self.assertEqual(fetch.call_count,2)
        with patch('processes.reference_background.automatic.solve',return_value=header):
            with self.assertRaises(InterruptedError):prepare(data,None,None,None,'',{'protect':[],'background':[]},None,lambda:True,lambda text:None,lambda a,b:None)
    def test_sip_download_reprojection_and_cache(self):
        import urllib.parse,json
        w=WCS(naxis=2);w.wcs.crpix=[1025.3,900.8];w.wcs.cdelt=[-.001,.001];w.wcs.crval=[80,-2];w.wcs.ctype=['RA---TAN-SIP','DEC--TAN-SIP']
        a=np.zeros((3,3));b=a.copy();a[2,0]=1e-6;b[0,2]=-2e-6;w.sip=Sip(a,b,None,None,w.wcs.crpix)
        header,step=geometry(w.to_header(relax=True),(2200,3000));small=WCS(header)
        points=np.array([[0,0],[200,100],[800,600]])
        np.testing.assert_allclose(small.all_pix2world(points,0),w.all_pix2world(points*step,0),atol=1e-9)
        def response(request,timeout):
            q=urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query);h=fits.Header(json.loads(q['wcs'][0]));self.assertNotIn('A_ORDER',h)
            array=np.ones((h['NAXIS2'],h['NAXIS1']));stream=io.BytesIO();fits.writeto(stream,array,h);return io.BytesIO(stream.getvalue())
        with tempfile.TemporaryDirectory() as folder:
            with patch('processes.reference_background.reference.urllib.request.urlopen',side_effect=response):
                result=fetch(w.to_header(relax=True),(2200,3000),SURVEYS['DSS2 Red'],cache_dir=folder)
            self.assertEqual(result['data'].shape,(734,1000));self.assertTrue(np.isfinite(result['data']).all())
            with patch('processes.reference_background.reference.urllib.request.urlopen',side_effect=AssertionError('cache missed')):
                cached=fetch(w.to_header(relax=True),(2200,3000),SURVEYS['DSS2 Red'],cache_dir=folder)
            self.assertTrue(cached['cached']);np.testing.assert_array_equal(cached['data'],result['data'])
    def test_gradient_and_unseen_nebula_manual_protection(self):
        data,nebula,gradient=scene();original=data.copy();reference={'data':np.full((256,256),.3),'step':1}
        model=engine.analyze(data,reference,protect=[[65,65,130,130]])
        result=engine.apply(data,model)
        np.testing.assert_array_equal(result[65:195,65:195],data[65:195,65:195])
        # Far from the protected region, the plane is removed to within 0.001.
        edge=np.zeros((256,256),bool);edge[:25]=True;edge[-25:]=True
        self.assertLess(np.std((result-nebula)[edge]),.001)
        np.testing.assert_array_equal(data,original)
    def test_rgb_mask_zero_nonfinite_cancel(self):
        data,_,_=scene();data=np.stack([data,data*2,data*.7],axis=-1);data[0,0]=np.nan
        reference={'data':np.ones((256,256)),'step':1};model=engine.analyze(data,reference)
        result=engine.apply(data,model,0);np.testing.assert_array_equal(result,data)
        result=engine.apply(data,model,mask=np.zeros((256,256)));np.testing.assert_array_equal(result,data)
        with self.assertRaises(InterruptedError):engine.apply(data,model,cancel=lambda:True)
        with self.assertRaises(ValueError):engine.apply(data,model,mask=np.full((256,256),np.nan))
    def test_insufficient_background_and_reference_values_not_transferred(self):
        data,_,_=scene();reference={'data':np.ones((256,256)),'step':1}
        with self.assertRaises(ValueError):engine.analyze(data,reference,background=[[0,0,20,20]])
        first=engine.analyze(data,reference)
        reference['data']*=90000
        second=engine.analyze(data,reference)
        np.testing.assert_allclose(first['model'],second['model'],atol=1e-12)
    def test_wcs_sampling_is_pixel_aligned(self):
        wcs=WCS(naxis=2);wcs.wcs.crpix=[1025.3,900.8];wcs.wcs.cdelt=[-.001,.001];wcs.wcs.crval=[80,-2];wcs.wcs.ctype=['RA---TAN','DEC--TAN']
        header,step=geometry(wcs.to_header(),(2200,3000));small=WCS(header)
        points=np.array([[0,0],[100,200],[999,700]])
        np.testing.assert_allclose(small.all_pix2world(points,0),wcs.all_pix2world(points*step,0),atol=1e-9)
    def test_fits_reference_and_service_response_validation(self):
        wcs=WCS(naxis=2);wcs.wcs.crpix=[16.5,16.5];wcs.wcs.cdelt=[-.001,.001];wcs.wcs.crval=[80,-2];wcs.wcs.ctype=['RA---TAN','DEC--TAN']
        header=wcs.to_header();data=np.arange(1024,dtype=float).reshape(32,32)
        payload=io.BytesIO();fits.writeto(payload,data,header)
        with patch('processes.reference_background.reference.urllib.request.urlopen',return_value=io.BytesIO(payload.getvalue())):
            result=fetch(header,data.shape,SURVEYS['DSS2 Red'],cache=False);np.testing.assert_array_equal(result['data'],data)
        wrong=header.copy();wrong['CRVAL1']+=2;payload=io.BytesIO();fits.writeto(payload,data,wrong)
        with patch('processes.reference_background.reference.urllib.request.urlopen',return_value=io.BytesIO(payload.getvalue())):
            with self.assertRaises(ValueError):fetch(header,data.shape,SURVEYS['DSS2 Red'],cache=False)
        with tempfile.TemporaryDirectory() as directory:
            path=directory+'/reference.fits';fits.writeto(path,data,header)
            result=load_file(path,header,data.shape)
            np.testing.assert_allclose(result['data'][1:-1,1:-1],data[1:-1,1:-1],atol=1e-7)


class ReferenceUiTest(unittest.TestCase):
    def test_review_required_apply_history_and_undo(self):
        from app import Window
        from processes.reference_background.ui import ReferenceBackgroundPanel
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            with patch('app.QSettings',return_value=QSettings(folder+'/p.ini',QSettings.IniFormat)):
                w=Window();w.auto_update_tools=lambda:None;w.setup_workspace()
            w.show();data,_,_=scene();w.data=data;w.showimage();source=w.viewwindow
            w.open_tool('native:reference_background');panel=w.tool_panel.findChild(ReferenceBackgroundPanel)
            panel.source=source;panel.data=data;panel.reference={'data':np.ones((256,256)),'step':1}
            panel.reference['header']=WCS(naxis=2).to_header()
            panel.add_region('protect',[80,80,60,60])
            manifest,_=w.capture_project()
            self.assertEqual(manifest['documents'][0]['reference_background_regions']['protect'],[[80,80,60,60]])
            self.assertEqual(manifest['documents'][0]['reference_background_shape'],[256,256])
            export=folder+'/saved-reference.fits'
            with patch('processes.reference_background.ui.QFileDialog.getSaveFileName',return_value=(export,'FITS')):panel.save_reference()
            with fits.open(export) as hdus:np.testing.assert_array_equal(hdus[0].data,panel.reference['data'])
            self.assertTrue(panel.apply_button.isEnabled());panel.execute(False)
            end=time.monotonic()+10
            while panel.model is None and time.monotonic()<end:app.processEvents();time.sleep(.01)
            self.assertIsNotNone(panel.model);self.assertTrue(panel.apply_button.isEnabled())
            from processes.reference_background.review import decide
            for i in range(len(panel.model['suspects'])):decide(panel.model,i,False)
            panel.comparison.render();panel.comparison.approve.setChecked(True);self.assertTrue(panel.apply_button.isEnabled())
            # Parameter changes invalidate the review.
            panel.fields['strength'].setValue(65);self.assertTrue(panel.apply_button.isEnabled())
            panel.execute(False)
            end=time.monotonic()+10
            while panel.model is None and time.monotonic()<end:app.processEvents();time.sleep(.01)
            for i in range(len(panel.model['suspects'])):decide(panel.model,i,False)
            panel.comparison.render();panel.comparison.approve.setChecked(True)
            # Drain finished notifications before launching the next worker.
            for _ in range(5):app.processEvents();time.sleep(.01)
            panel.execute(True);end=time.monotonic()+10
            while len(w.documents[source]['history'].entries)<2 and time.monotonic()<end:app.processEvents();time.sleep(.01)
            self.assertEqual(len(w.documents[source]['history'].entries),2)
            w.history_step(-1);np.testing.assert_array_equal(w.data,data)
            for _ in range(5):app.processEvents();time.sleep(.01)
            panel.cancel()
            reference={'data':np.ones((256,256)),'step':1};model=engine.analyze(data,reference)
            header=WCS(naxis=2).to_header()
            with patch('processes.reference_background.automatic.prepare',return_value=(header,reference,model)) as prepare:
                panel.start_auto(True)
                end=time.monotonic()+10
                while panel.model is None and time.monotonic()<end:app.processEvents();time.sleep(.01)
                self.assertTrue(prepare.called);self.assertIsNotNone(panel.comparison)
                self.assertFalse(panel.reviewed);self.assertEqual(len(w.documents[source]['history'].entries),2)
                for _ in range(5):app.processEvents();time.sleep(.01)
            panel.cancel()
            w.close()


if __name__=='__main__':unittest.main()
