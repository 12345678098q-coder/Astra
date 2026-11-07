import unittest
import numpy as np
from processes.reference_background.engine import analyze,apply
from processes.reference_background.review import candidates,decide,pending

class BackgroundReviewTest(unittest.TestCase):
    def test_uncertain_region_decisions_and_protection(self):
        yy,xx=np.mgrid[:256,:256];nebula=.09*np.exp(-((xx-125)**2+(yy-125)**2)/700)
        data=.2+xx*.0004+nebula;reference={'step':1,'data':np.ones((256,256))}
        model=analyze(data,reference);items=candidates(model);self.assertGreater(len(items),0)
        self.assertTrue(pending(model))
        with self.assertRaises(ValueError):apply(data,model)
        x,y,w,h=items[0]['rect']
        decide(model,0,True)
        for i in range(1,len(items)):decide(model,i,False)
        self.assertFalse(pending(model));result=apply(data,model)
        np.testing.assert_array_equal(result[y:y+h,x:x+w],data[y:y+h,x:x+w])
        decide(model,0,False);self.assertTrue((model['weight']==model['base_weight']).all())

if __name__=='__main__':unittest.main()
