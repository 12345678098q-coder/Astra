"""Synthetic CPU benchmark; --baseline is a saved pre-change engine.py."""
import argparse,importlib.util,json,sys,tempfile,time,threading
from collections import Counter
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import psutil
from astropy.io import fits
from unittest.mock import patch
from modules.stacking import engine

parser=argparse.ArgumentParser();parser.add_argument('--baseline',required=True);args=parser.parse_args()
spec=importlib.util.spec_from_file_location('modules.stacking._baseline',args.baseline)
baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
with tempfile.TemporaryDirectory(prefix='astra-bench-data-') as folder:
    root=Path(folder);groups={k:[] for k in ('Lights','Darks','Flats','Dark flats')}
    rng=np.random.default_rng(94);shape=(768,1024);flat=np.linspace(.8,1.2,shape[1],dtype=np.float32)[None,:]
    for category,count in [('Lights',3),('Darks',6),('Flats',6),('Dark flats',6)]:
        for i in range(count):
            a=rng.normal(0,.1,shape).astype('float32')
            a+=100*flat+20 if category=='Lights' else 20 if category=='Darks' else 1000*flat+5 if category=='Flats' else 5
            path=root/f'{category}_{i}.fits';fits.writeto(path,a);groups[category].append(str(path))
    options=dict(auto_resources=False,device='cpu',align=False,normalize=False,hot=False,cold=False,save_masters=False,method='mean')
    results={};reference=None
    for name,module in [('before',baseline),('after',engine)]:
        counts=Counter();reader=module.read;notes=[];peak=[psutil.Process().memory_info().rss];stop=threading.Event()
        def monitor():
            while not stop.wait(.01):peak[0]=max(peak[0],psutil.Process().memory_info().rss)
        def counted(path):counts[str(path)]+=1;return reader(path)
        watcher=threading.Thread(target=monitor);watcher.start();start=time.perf_counter()
        try:
            with patch.object(module,'read',side_effect=counted):result,coverage=module.stack(groups,log=notes.append,options=options)
        finally:elapsed=time.perf_counter()-start;stop.set();watcher.join()
        if reference is None:reference=result
        else:np.testing.assert_allclose(result,reference,rtol=1e-6,atol=1e-5)
        results[name]={'seconds':round(elapsed,3),'calibration_decodes':sum(counts[p] for key in ('Darks','Flats','Dark flats') for p in groups[key]),'peak_process_rss_mb':round(peak[0]/1024**2,1),'log':notes}
    results['speedup']=round(results['before']['seconds']/results['after']['seconds'],2)
    print(json.dumps(results,ensure_ascii=False,indent=2))
