"""Evaluate learned detail recovery against the frozen installed model."""
import argparse,json
import subprocess
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=Path('G:/AstraTraining/prepared/ground_detail01')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--candidate',type=Path,default=ROOT/'candidate_detail.npz')
    parser.add_argument('--prefix',default='')
    options=parser.parse_args();candidate=options.candidate
    def output(name):return ROOT/(options.prefix+name)
    common=['--baseline',ROOT/'parent_installed.npz','--device','cuda','--detail-evidence']
    jobs=[
        ('iris_evaluation.log',[HERE/'training2500/evaluate.py',candidate,output('iris_evaluation.json'),
         *common,'--controls',ROOT/'detail_test.json','--blind-controls']),
        ('personal_evaluation.log',[HERE/'training2500/evaluate.py',candidate,output('personal_evaluation.json'),
         *common,'--controls',HERE/'detail_training/test.json']),
        ('tensor_check.log',['-m','experiments.signal_booster.check_tensor_backend','--checkpoint',candidate,
         '--report',output('tensor_check.json')]),
        ('actual_integrations.log',[HERE/'check_native_candidate.py',candidate,'--baseline',ROOT/'parent_installed.npz',
         '--output',output('actual_integrations'),'--precision','fp16','--inputs',
         Path.home()/'Desktop/golovast.FTS',Path.home()/'Desktop/result_31440s M45.fit']),
    ]
    for log,args in jobs:
        print('RUN',options.prefix+log,flush=True)
        with output(log).open('w',encoding='utf-8') as stream:
            subprocess.run([sys.executable,*map(str,args)],stdout=stream,stderr=subprocess.STDOUT,check=True)
    print('COMPLETE; active weights unchanged pending review',flush=True)


if __name__=='__main__':main()
