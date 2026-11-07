from core.i18n import localize
import numpy as np
from .processing import histogram

def auto_settings(data,target=.25):
    if not .05<=target<=.5:raise ValueError(localize('Целевой фон 0.05…0.5.'))
    step=max(1,int(np.ceil(max(data.shape[:2])/1200)));sample=data[::step,::step];finite=sample[np.isfinite(sample)]
    if not finite.size:raise ValueError(localize('Нет конечных пикселей.'))
    median=float(np.median(finite));mad=1.4826*float(np.median(np.abs(finite-median)))
    low=float(np.percentile(finite,.05));high=float(np.percentile(finite,99.95))
    if high<=low:low=float(finite.min());high=float(finite.max())
    if high<=low:high=low+max(1,abs(low))*1e-6
    black=max(low,median-2.8*mad);black=min(black,median)
    x=float(np.clip((median-black)/(high-black),1e-6,1-1e-6))
    mid=float(np.clip(x*(target-1)/(2*x*target-x-target),.001,.999))
    return {'channels':{'All':{'black':black,'white':high,'mid':mid,'curve':'0:0;1:1'}}}
