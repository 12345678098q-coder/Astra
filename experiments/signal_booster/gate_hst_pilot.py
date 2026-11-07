"""Apply the pre-registered HST pilot continuation gate to held-out diagnostics."""
import json
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent
OUT=HERE/'train4m_5000/hst_pilot1000'


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    policy=read(OUT/'gate_policy.json');evaluation=read(OUT/'evaluation.json')
    noise=read(HERE/'noise_compatibility/hst_pilot1000/report.json')
    fields=[];reasons=[]
    def check_finite(value):
        if isinstance(value,dict):return all(check_finite(v) for v in value.values())
        if isinstance(value,list):return all(check_finite(v) for v in value)
        return not isinstance(value,float) or bool(np.isfinite(value))
    if not check_finite(evaluation) or not check_finite(noise):reasons.append('Nonfinite diagnostic values; continuation cannot be approved')
    for field in evaluation['objects']:
        first,last=(field['results'][name] for name in ('baseline','candidate'))
        gains={};transfer_losses=[]
        for band in ('fine_1_4px','diffuse_4_16px'):
            a,b=(row['spatial_bands'][band] for row in (first,last))
            gains[band]=100*(1-b['error_ratio']/a['error_ratio'])
            if a['independent_structure_transfer'] is None or b['independent_structure_transfer'] is None:
                reasons.append('Insufficient independent-reference structure support in '+band+': '+field['object'])
            else:
                transfer_losses.append(a['independent_structure_transfer']-b['independent_structure_transfer'])
        gain=float(np.mean(list(gains.values())))
        if gain < -policy['maximum_per_field_relative_detail_error_regression_percent']:
            reasons.append('Held-out field detail error worsened: '+field['object'])
        if transfer_losses and max(transfer_losses)>policy['maximum_independent_structure_transfer_loss']:
            reasons.append('Independent-reference-supported structure weakened: '+field['object'])
        fields.append(dict(field=field['object'],relative_error_reduction_percent=gain,spatial_bands=gains,
            maximum_supported_structure_transfer_loss=float(max(transfer_losses)) if transfer_losses else None))
    mean_gain=float(np.mean([f['relative_error_reduction_percent'] for f in fields]))
    if mean_gain<policy['minimum_mean_relative_detail_error_reduction_percent']:
        reasons.append('Mean held-out detail gain is below the pre-registered practical threshold')
    for band in ('fine_1_4px','diffuse_4_16px'):
        if np.mean([f['spatial_bands'][band] for f in fields])<=0:
            reasons.append('No consistent mean improvement in '+band)
    checks=[]
    for photo in noise['photos']:
        metrics=photo['metrics'];record=dict(source=photo['source'])
        colour=metrics['candidate']['pixel_chroma_fraction_change_p95']
        if colour is None:reasons.append('No valid positive RGB pixels for colour check: '+photo['source'])
        elif max(colour)>policy['maximum_rgb_chromaticity_fraction_error_p95']:
            reasons.append('RGB chromaticity changed beyond rounding tolerance: '+photo['source'])
        record['rgb_chromaticity_fraction_error_p95']=colour
        record['smoothed_chromaticity_fraction_change_p95']=metrics['candidate']['chroma_fraction_change_p95']
        for suffix,reference in (('','original'),('_nxt','original_nxt')):
            original=metrics[reference];a,b=(metrics[label+suffix] for label in ('current','candidate'))
            acf=[]
            for lag in original['acf']:
                for direction in ('vertical','horizontal'):
                    ref=np.asarray(original['acf'][lag][direction])
                    acf.extend(abs(np.asarray(b['acf'][lag][direction])-ref)-abs(np.asarray(a['acf'][lag][direction])-ref))
            ref=np.asarray(original['rgb_noise_correlation'])
            corr=float(np.max(abs(np.asarray(b['rgb_noise_correlation'])-ref)-abs(np.asarray(a['rgb_noise_correlation'])-ref)))
            added_acf=float(max(acf));record['added_acf_distortion'+suffix]=added_acf
            record['added_cross_channel_correlation_distortion'+suffix]=corr
            if added_acf>policy['maximum_added_noise_acf_absolute_difference']:
                reasons.append('Noise autocorrelation worsened'+suffix+': '+photo['source'])
            if corr>policy['maximum_added_cross_channel_noise_correlation_difference']:
                reasons.append('Cross-channel noise correlation worsened'+suffix+': '+photo['source'])
        checks.append(record)
    with np.load(OUT/'candidate_hst1000.npz',allow_pickle=False) as z:metadata=json.loads(str(z['metadata']))
    if metadata['new_training_frames']!=1000 or not metadata.get('widened_channels_finetuned'):
        reasons.append('Missing proof of 1000-frame optimizer coverage or widened-channel learning')
    result=dict(pass_all_checks=not reasons,decision='continue_hst' if not reasons else 'do_not_expand_hst',
        reasons=reasons,relative_detail_error_reduction_percent=mean_gain,fields=fields,noise_colour_checks=checks,
        training_frames=metadata['new_training_frames'],parameters=metadata['parameters'],
        caveats=['Three previously inspected held-out personal fields are a regression set, not a new blind benchmark.',
                 'NoiseX numerical checks do not prove absence of every visible artifact.',
                 'Improved error alone is insufficient; independent structure transfer is checked separately.'])
    (OUT/'gate_result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
