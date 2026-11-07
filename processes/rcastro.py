"""RC-Astro parameters verified against installed CLI 2.6.10 help."""
from .options import values_for

def command(operation,source,options=None,output=None):
    p=values_for('rcastro:'+operation,options)
    if operation=='nxt':
        strength=p['strength']/100
        p.update(device='auto',overlap=.2,ml_version=0.,frequency_scale=5.,iterations=2.,intensity_high=strength,intensity_low=strength,color_high=strength,color_low=strength)
    if operation=='sxt':p.update(device='auto',overlap=.2,ml_version=0.,unscreen=False)
    from core.compatibility import enabled
    if enabled():p['device']='cpu'
    args=[operation,str(source),'--device',p['device'],'--overlap',str(p['overlap']),'--ml-version',str(p['ml_version']),'--depth','32F']
    if output is not None:args+=['--output',str(output)]
    if operation=='bxt':
        args+=['--sharpen-stars',str(p['sharpen_stars']),'--adjust-star-halos',str(p['halos']),'--nonstellar-diameter',str(p['psf']),'--sharpen-nonstellar',str(p['sharpen_nonstellar'])]
        args+=['--auto-nonstellar-psf' if p['auto_psf'] else '--no-auto-nonstellar-psf']
        if p['correct_only']:args+=['--correct-only']
        if p['lunar']:args+=['--lunar-planetary']
    elif operation=='nxt':
        for key,flag in [('intensity_high','--denoise-intensity-high-freq'),('intensity_low','--denoise-intensity-low-freq'),('color_high','--denoise-color-high-freq'),('color_low','--denoise-color-low-freq'),('frequency_scale','--frequency-scale'),('iterations','--iterations')]:args+=[flag,str(p[key])]
    elif operation=='sxt':
        if p['stars']:args+=['--stars']
        if p['unscreen']:args+=['--unscreen']
    return args
