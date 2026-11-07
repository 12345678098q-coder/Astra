"""Evaluate the star-safe response without touching active plugin weights."""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = Path('G:/AstraTraining/prepared/ground_structure01')


def main():
    candidate = OUT / 'candidate_calibrated_safe.npz'
    common = ['--baseline', OUT / 'parent_4m.npz', '--extra-baseline',
              OUT / 'experimental_reference.npz', '--device', 'cuda']
    jobs = [
        ('safe_evaluation.log', [HERE / 'training2500/evaluate.py', candidate,
         OUT / 'safe_evaluation.json', *common, '--controls', HERE / 'detail_training/test.json']),
        ('safe_fresh_evaluation.log', [HERE / 'training2500/evaluate.py', candidate,
         OUT / 'safe_fresh_evaluation.json', *common, '--controls',
         OUT / 'strong_fresh_test.json', '--blind-controls']),
        ('safe_tensor_backend.log', ['-m', 'experiments.signal_booster.check_tensor_backend',
         '--checkpoint', candidate, '--report', OUT / 'safe_tensor_backend.json']),
        ('safe_actual_integrations.log', [HERE / 'check_native_candidate.py', candidate,
         '--baseline', OUT / 'parent_4m.npz', '--extra-baseline', OUT / 'experimental_reference.npz',
         '--output', OUT / 'safe_actual_integrations', '--precision', 'fp16', '--inputs',
         Path.home() / 'Desktop/golovast.FTS', Path.home() / 'Desktop/result_31440s M45.fit']),
    ]
    for log, args in jobs:
        print('RUN', log, flush=True)
        with (OUT / log).open('w', encoding='utf-8') as stream:
            subprocess.run([sys.executable, *map(str, args)], stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
    print('COMPLETE SAFE RESPONSE TESTS', flush=True)


if __name__ == '__main__':
    main()
