"""Delete only generated source crops proven covered by a saved training checkpoint."""
import argparse,hashlib,json
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent
ALLOWED={(HERE/'long_exposure_training/calibrated_crops').resolve(),
         (HERE/'extension10000/raw_crops').resolve(),
         (HERE/'train4m_5000/source_crops').resolve(),
         (HERE/'train4m_5000/hst_clean').resolve()}
ALLOWED.add(Path('G:/AstraTraining/prepared/ground_finetune01/calibrated_crops').resolve())
ALLOWED.add(Path('G:/AstraTraining/prepared/ground_structure01/calibrated_crops').resolve())
ALLOWED.add(Path('G:/AstraTraining/prepared/ground_detail01/calibrated_crops').resolve())


def cleanup(checkpoint,manifest):
    with np.load(checkpoint,allow_pickle=False) as data:metadata=json.loads(str(data['metadata']))
    if Path(metadata['training_manifest']).resolve()!=manifest.resolve():
        raise ValueError('Checkpoint does not belong to this training manifest')
    if metadata.get('training_manifest_sha256') and hashlib.sha256(manifest.read_bytes()).hexdigest()!=metadata['training_manifest_sha256']:
        raise ValueError('Training manifest changed after checkpoint creation')
    if metadata['training_frames']!=metadata['available_training_frames']:
        raise ValueError('Not every frame in this phase was covered; refusing bulk cleanup')
    records=json.loads(manifest.read_text(encoding='utf-8'))
    rows={f['sha256']:f for r in records if r['split']=='train_candidate' for group in r['levels'][-1]['frames'].values() for f in group}
    if len(rows)!=metadata['training_frames']:raise ValueError('Training manifest coverage differs from checkpoint')
    removed=[]
    for row in rows.values():
        paths=[(row['path'],row['sha256'],False)]
        if row.get('cosmic_cleaning_version') and row.get('generated_raw_crop_path'):
            paths.append((row['generated_raw_crop_path'],row['original_cached_pixel_sha256'],True))
        for filename,digest,verify in paths:
            path=Path(filename).resolve()
            if path.parent not in ALLOWED or path.suffix!='.npy':continue
            if path.is_file():
                if verify and hashlib.sha256(np.ascontiguousarray(np.load(path,allow_pickle=False)).tobytes()).hexdigest()!=digest:
                    raise ValueError('Generated raw source crop changed; refusing deletion')
                size=path.stat().st_size
                path.unlink()
                removed.append({'path':str(path),'bytes':size,'source_pixel_sha256':digest})
    result={'checkpoint':str(checkpoint.resolve()),'checkpoint_sha256':hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            'manifest':str(manifest.resolve()),'removed_files':len(removed),'freed_bytes':sum(r['bytes'] for r in removed),'files':removed}
    receipt=checkpoint.with_suffix('.cleanup.json')
    receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('CLEANED',len(removed),'generated trained crops;',result['freed_bytes'],'bytes',flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkpoint',type=Path);parser.add_argument('manifest',type=Path)
    args=parser.parse_args();cleanup(args.checkpoint,args.manifest)
