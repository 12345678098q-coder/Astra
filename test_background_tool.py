import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import time,unittest
import numpy as np
from PySide6.QtWidgets import QApplication
from app import Window
from processes.background import run_background
from modules.stacking.background import neutralize_background

class BackgroundTest(unittest.TestCase):
    def test_linear_balance(self):
        y,x=np.mgrid[:128,:128];signal=(x+y)*.01
        image=signal[...,None]+np.array([10.,25.,13.])
        image[60,60]+=100
        result=neutralize_background(image.copy())
        np.testing.assert_allclose(np.median(result,axis=(0,1)),np.repeat(np.median(result,axis=(0,1))[0],3),atol=1e-10)
        np.testing.assert_allclose(result[60,60]-result[59,60],image[60,60]-image[59,60])
        np.testing.assert_array_equal(neutralize_background(image.copy(),strength=0),image)
    def test_tool_history(self):
        app=QApplication.instance() or QApplication([]);w=Window();w.auto_update_tools=lambda:None;w.setup_workspace()
        w.data=np.ones((128,128,3),dtype=np.float32)*[10,20,30];w.showimage();source=w.viewwindow
        w.open_tool('local:background');run_background(w,{})
        deadline=time.monotonic()+5
        while len(w.documents[source]['history'].entries)<2 and time.monotonic()<deadline:
            app.processEvents();time.sleep(.01)
        self.assertEqual(len(w.documents[source]['history'].entries),2)
        np.testing.assert_allclose(w.documents[source]['data'],20)
        w.local_process.wait();app.processEvents();w.history_step(-1)
        np.testing.assert_allclose(w.data[0,0],[10,20,30]);w.close()

if __name__=='__main__':unittest.main()
