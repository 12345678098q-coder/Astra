"""Install only packaged GraXpert ONNX models; leave preferences untouched."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def install(root,target):
    root=Path(root).resolve();target=Path(target).resolve()
    models=root/'graxpert-models'
    manifest=json.loads((root/'TOOLS-MANIFEST.json').read_text(encoding='utf-8'))
    for entry in manifest['models']:
        family=entry['family'];version=entry['version']
        if family not in ('bge-ai-models','denoise-ai-models','deconvolution-object-ai-models','deconvolution-stars-ai-models') or not re.fullmatch(r'\d+\.\d+\.\d+',version):raise ValueError('Invalid model entry')
        source=(models/family/version/'model.onnx').resolve()
        if not source.is_relative_to(models.resolve()) or digest(source)!=entry['sha256']:raise ValueError('Model verification failed: '+family)
    for entry in manifest['models']:
        source=models/entry['family']/entry['version']/'model.onnx'
        destination=target/entry['family']/entry['version']/'model.onnx'
        if destination.exists() and digest(destination)==entry['sha256']:
            print('Already installed:',entry['family'],entry['version'],flush=True);continue
        destination.parent.mkdir(parents=True,exist_ok=True)
        if destination.exists():shutil.copy2(destination,destination.with_suffix('.onnx.before-Astra-Tools'))
        temporary=destination.with_suffix('.onnx.astra-installing')
        try:
            shutil.copyfile(source,temporary)
            if digest(temporary)!=entry['sha256']:raise OSError('Copied model verification failed')
            os.replace(temporary,destination)
        finally:temporary.unlink(missing_ok=True)
        print('Installed:',entry['family'],entry['version'],flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--target-root',type=Path);args=parser.parse_args()
    root=Path(__file__).resolve().parent
    target=args.target_root or Path(os.environ['LOCALAPPDATA'])/'GraXpert/GraXpert'
    install(root,target)
    print('GraXpert models ready. Restart Astra.')
