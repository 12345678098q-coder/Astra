"""Verify exposure accounting, nested frames and finite image data before training."""
import json
import hashlib
from pathlib import Path
import numpy as np

from prepare_pc import OUT, NATIVE, write_json


def main():
    inventory = json.loads((OUT/'inventory.json').read_text(encoding='utf-8'))
    verified = []
    for group, rows in inventory['groups'].items():
        folder = OUT / hashlib.sha256(group.encode()).hexdigest()[:12]
        record = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        if NATIVE and not record.get('native_resolution'):
            raise ValueError('Native resolution is required')
        previous = {}
        shape = None
        for level in record['levels']:
            with np.load(level['path'], allow_pickle=False) as archive:
                image = archive['image']
            if not np.isfinite(image).all() or min(image.shape[:2]) < 64:
                raise ValueError('Invalid pixels or image area: ' + level['path'])
            if shape is not None and image.shape != shape:
                raise ValueError('Inconsistent field')
            shape = image.shape
            if list(shape[:2]) != [record['crop'][3], record['crop'][2]]:
                raise ValueError('Unexpected image scaling')
            for channel, frames in level['frames'].items():
                if NATIVE and any(f['source_shape'] != record['registration_shape'] for f in frames):
                    raise ValueError('Source and registration grids differ')
                hashes = [f['sha256'] for f in frames]
                if len(hashes) != len(set(hashes)):
                    raise ValueError('Repeated exposure inside a stack')
                if hashes[:len(previous.get(channel, []))] != previous.get(channel, []):
                    raise ValueError('Stacks are not cumulative')
                if previous.get(channel) == hashes:
                    raise ValueError('Identical exposure groups on adjacent levels')
                seconds = sum(f['seconds'] for f in frames)
                if abs(seconds-level['actual_seconds'][channel]) > 1e-6:
                    raise ValueError('Exposure accounting mismatch')
                previous[channel] = hashes
            level['file_sha256'] = hashlib.sha256(Path(level['path']).read_bytes()).hexdigest()
        name = group.split('|')[0]
        record['split'] = {'ngc2359':'validation', 'NGC 6960':'test', 'NGC 6995':'test',
                           'M 27':'reused_diagnostic'}.get(name, 'train_candidate')
        record['verified'] = True
        record['shape'] = shape
        write_json(folder/'manifest.json', record)
        verified.append(record)
        # Only disposable files with a full pixel-hash filename inside this output folder.
        for path in folder.iterdir():
            if path.suffix in ('.fit', '.npy') and len(path.stem) == 64 and all(c in '0123456789abcdef' for c in path.stem):
                if OUT.resolve() not in path.resolve().parents:
                    raise ValueError('Unexpected cache path')
                path.unlink()
    write_json(OUT/'summary.json', verified)
    print('VERIFIED', len(verified), 'objects', sum(len(r['levels']) for r in verified), 'stacks')
    for r in verified:
        print(r['group'].split('|')[0], r['accepted_frames'],
              [round(sum(x['actual_seconds'].values())/3600,4) for x in r['levels']],
              'calibrated', r['calibrated'], 'rejected', len(r['rejected']))


if __name__ == '__main__':
    main()
