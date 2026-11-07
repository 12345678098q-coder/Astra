import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parent
FOLDER=ROOT/'fixes/Astra-Win10-4GB-CPU'


class PackageTest(unittest.TestCase):
    def test_manifest_and_archive(self):
        manifest=json.loads((FOLDER/'manifest.json').read_text())
        with zipfile.ZipFile(FOLDER.with_suffix('.zip')) as archive:
            for entry in manifest['files']:
                name=entry['path']
                data=(FOLDER/'payload'/name).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(),entry['sha256'])
                self.assertEqual(archive.read(FOLDER.name+'/payload/'+name),data)
                self.assertNotIn(name.split('/')[0],('optional','runtime','.venv','tools'))

    @unittest.skipUnless(os.name=='nt','Windows installer')
    def test_install_preserves_runtime_and_backs_up(self):
        with tempfile.TemporaryDirectory(prefix='astra-install-check-') as folder:
            target=Path(folder)/'Astra test';target.mkdir()
            (target/'app.py').write_text('# old app',encoding='utf-8')
            (target/'runtime').mkdir();(target/'runtime/python.exe').write_bytes(b'runtime sentinel')
            cuda=target/'optional/cuda/site-packages';cuda.mkdir(parents=True)
            (cuda/'sentinel.txt').write_text('do not move')
            result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
                                   '-File',str(FOLDER/'Install.ps1'),'-Target',str(target)],capture_output=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual((target/'runtime/python.exe').read_bytes(),b'runtime sentinel')
            self.assertEqual((cuda/'sentinel.txt').read_text(),'do not move')
            self.assertEqual(next(target.glob('compatibility-backup-*/app.py')).read_text(),'# old app')
            self.assertTrue((target/'compatibility.flag').exists())
            self.assertEqual((target/'app.py').read_bytes(),(ROOT/'app.py').read_bytes())

if __name__=='__main__':unittest.main()
