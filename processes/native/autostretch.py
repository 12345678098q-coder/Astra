from core.i18n import localize
import numpy as np

DEFAULT_TARGET=.12

def _midtone_for(value,target):
    x=float(np.clip(value,1e-6,1-1e-6))
    return x*(1-target)/(x+target-2*x*target)

def auto_settings(data,target=DEFAULT_TARGET):
    if not .05<=target<=.5:raise ValueError(localize('Целевой фон 0.05…0.5.'))
    step=max(1,int(np.ceil(max(data.shape[:2])/1200)));sample=data[::step,::step];finite=sample[np.isfinite(sample)]
    if not finite.size:raise ValueError(localize('Нет конечных пикселей.'))
    median=float(np.median(finite));mad=1.4826*float(np.median(np.abs(finite-median)))
    low=float(np.percentile(finite,.05));high=float(np.percentile(finite,99.95))
    if high<=low:low=float(finite.min());high=float(finite.max())
    if high<=low:high=low+max(1,abs(low))*1e-6
    black=max(low,median-2.8*mad);black=min(black,median)
    if high<=black:high=black+max(1.,abs(black))*1e-6
    # Keep bright cores in range and limit the lift of their upper tones.
    # Leave room below tight sky peaks so this does not crush the background.
    black=max(float(finite.min()),min(black,median-.008*(high-median)))
    upper=float(np.percentile(finite,99.5))
    white=max(float(finite.max()),black+1.1*(high-black))
    mid=max(_midtone_for((median-black)/(white-black),target),
            _midtone_for((upper-black)/(white-black),.85),
            _midtone_for((high-black)/(white-black),.95))
    mid=float(np.clip(mid,.001,.999))
    return {'channels':{'All':{'black':black,'white':white,'mid':mid,'curve':'0:0;1:1'}}}
