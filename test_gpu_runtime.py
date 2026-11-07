import importlib.util,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from core.gpu_runtime import runtime_path

class GpuRuntimeTests(unittest.TestCase):
 def test_install_command(self):
  from core.gpu_setup import installation_details
  with patch('core.gpu_setup.sys.executable','C:/Astra/runtime/pythonw.exe'):
   exe,requirements,command=installation_details()
  self.assertEqual(exe.name,'python.exe');self.assertIn('--no-deps --target',command);self.assertIn(str(runtime_path()),command);self.assertTrue(requirements.is_file())
 def test_base_cpu_without_optional_packages(self):
  code='import sys; from modules.stacking.engine import compute_backend; import numpy; assert compute_backend("cpu") is numpy; assert "cupy" not in sys.modules'
  subprocess.run([sys.executable,'-B','-c',code],check=True,capture_output=True,timeout=20)
 def test_policy_excludes_optional(self):
  policy=json.loads(Path('build-support/package-policy.json').read_text())
  self.assertFalse(policy['base_bundle_include_cuda']);self.assertIn('optional',policy['exclude_project_paths'])
  spec=importlib.util.spec_from_file_location('check_package','build-support/check_package.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder)
   for relative in policy['required_bundle_paths']:
    path=root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.touch()
   self.assertEqual(module.check(root),[]);(root/'optional').mkdir();self.assertTrue(any('optional' in s for s in module.check(root)))
 def test_dependency_list_is_complete(self):
  # Validate the isolated target against the base environment's dependencies.
  from importlib.metadata import distributions
  from packaging.requirements import Requirement
  optional=runtime_path()
  if not optional.is_dir():self.skipTest('Optional runtime is not installed')
  base={d.metadata['Name'].lower().replace('_','-'):d.version for d in distributions()}
  gpu={d.metadata['Name'].lower().replace('_','-'):d for d in distributions(path=[str(optional)])}
  versions={**base,**{name:d.version for name,d in gpu.items()}}
  pinned={Requirement(line).name.lower().replace('_','-') for line in Path('requirements-cuda.txt').read_text().splitlines() if line.strip() and not line.startswith('#')}
  self.assertEqual(set(gpu),pinned)
  for d in gpu.values():
   for text in d.requires or []:
    r=Requirement(text)
    if r.marker is not None and not r.marker.evaluate({'extra':''}):continue
    name=r.name.lower().replace('_','-');self.assertIn(name,versions);self.assertIn(versions[name],r.specifier)

if __name__=='__main__':unittest.main()
