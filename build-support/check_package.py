"""Fail packaging when a base staging directory contains optional CUDA files."""
import argparse,fnmatch,json
from pathlib import Path

def check(root):
 policy=json.loads(Path(__file__).with_name('package-policy.json').read_text(encoding='utf-8'));errors=[]
 for relative in policy['required_bundle_paths']:
  if not (root/relative).exists():errors.append('Missing required bundle path: '+relative)
 packages=root/'runtime/Lib/site-packages'
 if packages.is_dir():
  for entry in packages.iterdir():
   if any(fnmatch.fnmatch(entry.name.lower(),pattern.lower()) for pattern in policy['exclude_site_packages_globs']):errors.append('Excluded from base bundle: '+str(entry.relative_to(root)))
 for entry in root.iterdir():
  if any(fnmatch.fnmatch(entry.name,pattern) for pattern in policy['exclude_project_paths']):errors.append('Development artifact in bundle: '+entry.name)
 return errors

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('staging',type=Path);args=parser.parse_args()
 if not args.staging.is_dir():parser.error('staging must be an existing directory')
 errors=check(args.staging)
 print('\n'.join(errors) if errors else 'Base bundle policy: OK')
 raise SystemExit(1 if errors else 0)
