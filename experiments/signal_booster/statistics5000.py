"""Summarize the installed 5000-exposure checkpoint against the 2500 baseline."""
import hashlib
import json
from pathlib import Path

import numpy as np

HERE=Path(__file__).resolve().parent
OUT=HERE/'desktop_training'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


if __name__=='__main__':
    baseline=HERE/'training2500/multiscale2500.npz'
    candidate=HERE/'models/signal_booster_multiscale.npz'
    groups={}
    with np.load(baseline,allow_pickle=False) as first, np.load(candidate,allow_pickle=False) as last:
        before_meta=json.loads(str(first['metadata']))
        after_meta=json.loads(str(last['metadata']))
        count=changed=0
        squared_difference=squared_before=absolute_difference=0.
        for key in first.files:
            if key=='metadata':
                continue
            a,b=first[key].astype('f8'),last[key].astype('f8')
            delta=b-a
            size=a.size
            count+=size
            changed+=int(np.count_nonzero(delta))
            squared_difference+=float(np.sum(delta**2))
            squared_before+=float(np.sum(a**2))
            absolute_difference+=float(np.sum(abs(delta)))
            family=key.split('.')[0]
            row=groups.setdefault(family,dict(parameters=0,changed=0,squared_delta=0.,squared_before=0.))
            row['parameters']+=size
            row['changed']+=int(np.count_nonzero(delta))
            row['squared_delta']+=float(np.sum(delta**2))
            row['squared_before']+=float(np.sum(a**2))
    for row in groups.values():
        row['relative_l2_change_percent']=100*np.sqrt(row.pop('squared_delta')/row.pop('squared_before'))
    old_records=read(HERE/'training2500/records.json')
    new_records=read(OUT/'train5000_records.json')
    datasets=[]
    for records in (old_records,new_records):
        datasets.append(dict(frames=len({frame['sha256'] for record in records for rows in record['levels'][-1]['frames'].values() for frame in rows}),
            fields=len({record['field'] for record in records}),records=len(records),
            stacks=sum(len(record['levels']) for record in records),pairs=sum(len(record['levels'])-1 for record in records)))
    labels={'desktop:pointing_01':'Слон', 'desktop:pointing_16':'Боде / M81–M82',
        'NGC 6995':'NGC 6995','ngc2359':'NGC 2359','NGC 6960':'NGC 6960','holdout_M104':'M104'}
    results=[]
    for name,protocol in (('blind_test5000.json','personal_heldout'),('diagnostic_test5000.json','previous_diagnostic')):
        report=read(OUT/name)
        for row in report['objects']:
            identifier=row['object'].split('|')[0]
            entry=dict(object=labels[identifier],protocol='validation' if row['split']=='validation' else protocol,
                results={})
            for version,result in row['results'].items():
                bands=result['spatial_bands']
                stars=result['star_aperture_flux']['channels']
                entry['results'][version]=dict(
                    whole_image_error_reduction_percent=100*(1-result['structure_error_ratio']),
                    fine_nonstellar_error_reduction_percent=100*(1-bands['fine_1_4px']['star_core_excluded_error_ratio']),
                    diffuse_nonstellar_error_reduction_percent=100*(1-bands['diffuse_4_16px']['star_core_excluded_error_ratio']),
                    nonstellar_pixel_fraction=bands['fine_1_4px']['star_core_excluded_pixel_fraction'],
                    stellar_median_flux_change_percent=[100*channel['median_fractional_change'] for channel in stars],
                    stellar_p95_absolute_flux_change_percent=[100*channel['p95_absolute_fractional_change'] for channel in stars])
            entry['fine_improvement_percentage_points']=(entry['results']['candidate']['fine_nonstellar_error_reduction_percent']
                -entry['results']['baseline']['fine_nonstellar_error_reduction_percent'])
            results.append(entry)
    report=dict(date='2026-11-06',baseline=dict(bytes=baseline.stat().st_size,parameters=count,**datasets[0]),
        candidate=dict(bytes=candidate.stat().st_size,parameters=count,**datasets[1]),
        update=dict(changed_parameter_values=changed,changed_parameter_values_percent=100*changed/count,
            relative_l2_parameter_change_percent=100*np.sqrt(squared_difference/squared_before),
            mean_absolute_parameter_change=absolute_difference/count,by_module=groups,
            steps_completed=12000,selected_step=after_meta['step'],sampled_pairs=after_meta['sampled_pairs']),
        source_counts=dict(public=4825,personal_training=175,personal_validation=12,personal_test=20,personal_deferred=138),
        checkpoint_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),quality=results,
        conditions=dict(boost_percent=100,width_pixels=900,
            quality_formula='100*(1 - prediction_error/input_error) against an independent exposure remainder',
            fine_band_pixels=[1,4],diffuse_band_pixels=[4,16],
            nonstellar_mask='Input-only high-contrast core threshold 8 noise units; square dilation 21 pixels',
            independent_personal_test_series=2,previous_diagnostics=3,validation_series=1),
        limitations=['Percentages describe error reduction, not added detail or equivalent exposure.',
            'All six series were processed with identical baseline/candidate metrics; only two personal series were newly held out.',
            'Full native resolution quality has not been validated by these 900px tests.',
            '10% improvement for every image and spatial scale remains unmet.',
            'Changes in weight values are not a measure of image quality.'])
    (OUT/'statistics5000.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:report[key] for key in ('baseline','candidate','update')},ensure_ascii=False,indent=2))
