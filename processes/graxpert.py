"""GraXpert CLI parameters verified against the official main.py parser."""
from core.i18n import localize
import re
from .options import values_for

def command(operation,source,output,options=None,preferences_file=None):
    key='graxpert:'+operation
    p=values_for(key,options)
    from core.compatibility import enabled
    if enabled():p.update(gpu=False,batch=1)
    args=['-cmd',operation,str(source),'-cli','-output',str(output),'-gpu','true' if p['gpu'] else 'false']
    rbf=operation=='background-extraction' and p['method']=='RBF'
    if rbf:
        if preferences_file is None:raise ValueError(localize('Для RBF нужны точки фона. Откройте редактор точек.'))
        args+=['-preferences_file',str(preferences_file)]
        args[args.index('-gpu')+1]='false'
    if p['model'] and not rbf:
        if not re.fullmatch(r'\d+\.\d+\.\d+',p['model']):raise ValueError(localize('Версия модели GraXpert: используйте формат 1.0.0 либо оставьте поле пустым.'))
        args+=['-ai_version',p['model']]
    if operation=='background-extraction':
        args+=['-smoothing',str(p['smoothing']),'-correction',p['correction']]
        if p['background']:args+=['-bg']
    else:
        args+=['-strength',str(p['strength']),'-batch_size',str(p['batch'])]
        if operation.startswith('deconv-'):args+=['-psfsize',str(p['psf'])]
    return args

def rbf_preferences(options,points,shape):
    import numpy as np
    p=values_for('graxpert:background-extraction',options)
    a=np.asarray(points,dtype=float)
    if a.ndim!=2 or a.shape[1]!=2 or not 6<=len(a)<=500 or not np.isfinite(a).all():raise ValueError(localize('Для RBF нужно от 6 до 500 точек чистого фона.'))
    if len(np.unique(a.astype(int),axis=0))!=len(a) or np.linalg.matrix_rank(a-a.mean(axis=0))<2:raise ValueError(localize('Точки фона не должны совпадать или лежать на одной прямой.'))
    radius=p['sample_size']
    if min(shape[:2])<4 or np.any(a[:,0]<radius) or np.any(a[:,1]<radius) or np.any(a[:,0]>=shape[1]-radius) or np.any(a[:,1]>=shape[0]-radius):raise ValueError(localize('Образцы фона выходят за край. Уменьшите радиус или передвиньте точки.'))
    return {'interpol_type_option':'RBF','background_points':a.astype(int).tolist(),'RBF_kernel':p['kernel'],'smoothing_option':p['smoothing'],'sample_size':radius,'corr_type':p['correction'],'ai_gpu_acceleration':False}
