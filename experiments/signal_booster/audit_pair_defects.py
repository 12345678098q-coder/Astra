"""Verify throughput independently and quantify fine-loss concentration in defects."""
import argparse,json
from pathlib import Path
import numpy as np
from scipy.ndimage import gaussian_filter,median_filter,maximum_filter
if __package__:
    from .audit_detail_pairs import independent_pair,bootstrap_median
    from .multiscale import statistics
    from .contrast_response import star_mask
else:
    from audit_detail_pairs import independent_pair,bootstrap_median
    from multiscale import statistics
    from contrast_response import star_mask


def aperture_flux(light,x,y):
    x0,y0=int(round(x)),int(round(y));radius=21
    patch=light[y0-radius:y0+radius+1,x0-radius:x0+radius+1]
    if patch.shape!=(43,43):return None
    yy,xx=np.mgrid[y0-radius:y0+radius+1,x0-radius:x0+radius+1]
    distance=(xx-x)**2+(yy-y)**2
    core=distance<=100;annulus=(distance>=14**2)&(distance<=20**2)
    return float(patch[core].sum()-np.median(patch[annulus])*core.sum())


def defect_energy(a,r,noise):
    # These are artifact candidates, not an automatic correction mask.
    # A median residual can also flag real compact dark features.
    na=(a-median_filter(a,size=(5,5,1)))/noise
    nr=(r-median_filter(r,size=(5,5,1)))/noise
    negatives=(na.min(2)<-20)|(nr.min(2)<-20)
    nearby=maximum_filter(negatives.astype('u1'),size=17)>0
    def fine(x):return (gaussian_filter(x,(1,1,0))-gaussian_filter(x,(4,4,0)))/noise
    errors=(fine(a)-fine(r))[32:-32,32:-32].astype('f8')**2
    combined=errors.sum(2);total=combined.sum();values=np.sort(combined.ravel())
    mask=nearby[32:-32,32:-32]
    selected=star_mask(a,noise)[32:-32,32:-32]<.5
    selected_values=np.sort(combined[selected]);selected_total=selected_values.sum()
    nonstellar=dict(pixel_fraction=float(selected.mean()))
    if selected.any() and selected_total>0:
        nonstellar.update(fine_loss_mean=float(errors[selected].mean()),
            fine_loss_fraction_top_0_1_percent=float(selected_values[-max(1,int(.001*len(selected_values))):].sum()/selected_total),
            fine_loss_fraction_top_1_percent=float(selected_values[-max(1,int(.01*len(selected_values))):].sum()/selected_total),
            fine_loss_fraction_near_negative_candidates=float(combined[selected&mask].sum()/selected_total),
            fraction_near_negative_candidates=float(mask[selected].mean()))
    return dict(negative_outlier_candidate_fraction=float(negatives.mean()),
        nonstellar_loss_with_training_star_mask=nonstellar,
        negative_residual_min_input_noise_units=float(na.min()),negative_residual_min_reference_noise_units=float(nr.min()),
        fine_loss_mean=float(errors.mean()),
        fine_loss_fraction_top_0_1_percent=float(values[-max(1,int(.001*len(values))):].sum()/total),
        fine_loss_fraction_top_1_percent=float(values[-max(1,int(.01*len(values))):].sum()/total),
        fraction_near_negative_candidates=float(mask.mean()),
        fine_loss_fraction_near_negative_candidates=float(combined[mask].sum()/total),
        fine_loss_mean_away_from_negative_candidates=float(errors[~mask].mean()) if (~mask).any() else None,
        note='Concentration diagnostic only; compact real dark structures must not be removed by this threshold alone.')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--audit',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();results=[]
    audit=json.loads(args.audit.read_text(encoding='utf-8'))
    for row in audit['pairs']:
        records=json.loads(Path(row['manifest']).read_text(encoding='utf-8'))
        record=next(r for r in records if r['field']==row['field'])
        a,r,_,_=independent_pair(record['levels'][row['first_index']],record['levels'][row['last_index']])
        x,y,w,h=row['native_crop'];a,r=a[y:y+h,x:x+w],r[y:y+h,x:x+w]
        flux=[];light_a=a.mean(2);light_r=r.mean(2)
        for star in row['stars'].get('measurements',[]):
            f=aperture_flux(light_a,star['input']['x'],star['input']['y'])
            g=aperture_flux(light_r,star['reference']['x'],star['reference']['y'])
            if f and g and f>0 and g>0:flux.append(g/f)
        result=dict(field=row['field'],first_index=row['first_index'],last_index=row['last_index'],
                    aperture_stars=len(flux),aperture_flux_ratio=bootstrap_median(flux) if flux else None,
                    defects=defect_energy(a,r,statistics(a)[1]))
        results.append(result);print(result,flush=True)
        args.output.write_text(json.dumps(dict(status='running',pairs=results),indent=2),encoding='utf-8')
    args.output.write_text(json.dumps(dict(status='complete',pairs=results),indent=2),encoding='utf-8')


if __name__=='__main__':main()
