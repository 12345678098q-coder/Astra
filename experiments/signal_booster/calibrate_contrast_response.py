"""Fit two bounded response coefficients using TRAINING exposures only."""
import hashlib,json,sys
from pathlib import Path
import numpy as np
from scipy.ndimage import gaussian_filter,maximum_filter
from scipy.optimize import minimize
from multiscale import load_checkpoint,write_checkpoint,enhance,statistics
from contrast_response import features,apply_response,protect_stars

ROOT=Path('G:/AstraTraining/prepared/ground_structure01')


def main():
    model,meta=load_checkpoint(ROOT/'raw_effect.npz','cuda');fields=[];H=np.zeros((2,2));b=np.zeros(2);constraints=[]
    rng=np.random.default_rng(6077)
    for record in json.loads((ROOT/'strong_train.json').read_text(encoding='utf-8')):
        first,last=record['levels'][0],record['levels'][-1]
        def pixels(level):
            path=Path(level['path'])
            if hashlib.sha256(path.read_bytes()).hexdigest()!=level['file_sha256']:raise ValueError('Stack changed')
            with np.load(path) as z:a=z['image']
            return np.repeat(a[...,None],3,axis=2) if a.ndim==2 else a
        a,deep=pixels(first),pixels(last);keys=('Red','Green','Blue') if 'Red' in first['actual_seconds'] else ('image',)*3
        ratio=np.array([last['actual_seconds'][k]/first['actual_seconds'][k] for k in keys],dtype='f4')
        ref=(deep-a/ratio)/(1-1/ratio);raw_base=enhance(a,model,precision='fp32')
        offset,scale=statistics(a);base=protect_stars(raw_base,a,scale);fs=features(base,a,scale)
        light=((a-offset)/scale).mean(2);mask=~(maximum_filter((light-gaussian_filter(light,4)>8).astype('u1'),size=21)>0)[64:-64,64:-64]
        residual=((base-ref)/scale)[64:-64,64:-64][mask].astype('f8')
        normalized=[(f/scale)[64:-64,64:-64][mask].astype('f8') for f in fs]
        for i in range(2):
            b[i]+=np.mean(residual*normalized[i])
            for j in range(2):H[i,j]+=np.mean(normalized[i]*normalized[j])
        field=dict(field=record['field'],measurements=[])
        for low,high in ((1,4),(4,16)):
            def band(x):return ((gaussian_filter(x,(low,low,0))-gaussian_filter(x,(high,high,0)))/scale)[64:-64,64:-64].astype('f8')
            ab,rb,bb,f1,f2=map(band,(a,ref,base,*fs))
            for v in (ab,rb,bb,f1,f2):v-=v[mask].mean(axis=0)
            signal=float((ab*rb)[mask].mean());null=[]
            for _ in range(16):
                dy,dx=rng.integers(64,200,size=2)
                shifted_mask=mask&np.roll(mask,(dy,dx),(0,1))
                null.append(float((ab*np.roll(rb,(dy,dx),(0,1)))[shifted_mask].mean()))
            floor=max(0.,float(np.mean(null)+3*np.std(null,ddof=1)))
            reliable=signal>floor and signal>1e-8
            transfer=float((bb*rb)[mask].mean()/signal) if signal>0 else None
            slopes=[float((v*rb)[mask].mean()/signal) for v in (f1,f2)] if signal>0 else [0.,0.]
            measurement=dict(band=[low,high],signal=signal,null_upper_3sigma=floor,reliable=reliable,raw_transfer=transfer,response_slopes=slopes)
            field['measurements'].append(measurement)
            if reliable:constraints.append((np.asarray(slopes),.998-transfer))
        fields.append(dict(field=field,a=a,base=base,raw_base=raw_base,ref=ref,scale=scale,mask=mask))
        print('CALIBRATION FIELD',field,flush=True)
    if not constraints:raise ValueError('No reliable training-only contrast response; cannot invent gains')
    A=np.stack([x for x,y in constraints]);target=np.array([y for x,y in constraints])
    objective=lambda x:float(x@H@x+2*b@x)
    solution=minimize(objective,[.1,0.],jac=lambda x:2*(H@x+b),bounds=((0.,.4),(-.2,.2)),
        constraints=[dict(type='ineq',fun=lambda x:A@x-target,jac=lambda x:A)],method='SLSQP',options=dict(maxiter=200,ftol=1e-10))
    if not solution.success:raise ValueError('Training contrast constraints infeasible: '+solution.message)
    gains=solution.x;model.structure_gains=tuple(float(x) for x in gains)
    model.structure_response_enabled=True
    audit=[]
    for item in fields:
        corrected=apply_response(item['raw_base'],item['a'],item['scale'],gains)
        transfers=[]
        for measurement in item['field']['measurements']:
            low,high=measurement['band']
            def local_band(x):return ((gaussian_filter(x,(low,low,0))-gaussian_filter(x,(high,high,0)))/item['scale'])[64:-64,64:-64].astype('f8')
            ab,rb,cb=map(local_band,(item['a'],item['ref'],corrected))
            for v in (ab,rb,cb):v-=v[item['mask']].mean(axis=0)
            signal=float((ab*rb)[item['mask']].mean());transfer=float((cb*rb)[item['mask']].mean()/signal) if signal>0 else None
            transfers.append(dict(band=[low,high],reliable=measurement['reliable'],transfer=transfer))
            if measurement['reliable'] and transfer<.995:raise ValueError('Exact clipped response fails training contrast retention')
        audit.append(dict(field=item['field'],correction_std_noise_units=((corrected-item['a']).std((0,1))/item['scale']).tolist(),exact_transfer=transfers))
    meta.update(parameters=sum(p.numel() for p in model.parameters()),widened_channels_finetuned=True,
        known_additional_unique_exposures=376,cumulative_unique_exposures=None,noise_matching_not_training_objective=True,
        structure_response_calibration='Two bounded zero-DC Gaussian-band coefficients, learned only from 376 training exposures and disjoint reference remainders',
        structure_response_training_constraints=len(constraints),fresh_test_exposures=45,calibration_not_fitted_to_controls=True,
        deployment_status='pending_independent_comparison')
    write_checkpoint(ROOT/'candidate_calibrated_safe.npz',model,meta)
    report=dict(gains=gains.tolist(),objective=float(solution.fun),success=True,training_fields=[i['field'] for i in fields],audit=audit,
        calibration_uses_only_training_manifest=str(ROOT/'strong_train.json'),heldout_iris_used=False)
    (ROOT/'contrast_calibration_safe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FITTED',gains.tolist(),flush=True)


if __name__=='__main__':main()
