import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from processes.starnet.backend import model_weights,command

class StarNetPathTests(unittest.TestCase):
 def test_unicode_path(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);install=root/'астропрога';install.mkdir();exe=install/'starnet2.exe';exe.touch()
   model=install/'StarNet2_weights.onnx';model.write_bytes(b'model test');work=root/'work';work.mkdir()
   safe=model_weights(exe,work);self.assertTrue(safe.isascii());self.assertEqual(Path(safe).read_bytes(),b'model test')
   self.assertTrue(model.exists());args=command(work/'input.fits',work/'output.fits',weights=safe)
   self.assertEqual(args[args.index('--weights')+1],safe)
 def test_no_short_names_and_copy_fallback(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);install=root/'установка';install.mkdir();exe=install/'starnet2.exe';model=install/'StarNet2_weights.onnx';model.write_bytes(b'unchanged')
   work=root/'work';work.mkdir()
   def safe(p):return str(work) if Path(p)==work else None
   with patch('processes.starnet.backend.ascii_path',side_effect=safe),patch('os.link',side_effect=OSError('no hardlinks')):
    result=model_weights(exe,work)
   self.assertEqual(Path(result).read_bytes(),b'unchanged');Path(result).unlink();self.assertEqual(model.read_bytes(),b'unchanged')
 def test_missing_model(self):
  with tempfile.TemporaryDirectory() as folder:
   for language, message in [('ru','Не найдена модель StarNet'), ('en','StarNet model is missing')]:
    with self.subTest(language=language), patch('core.i18n._language', language):
     with self.assertRaisesRegex(ValueError,message):model_weights(Path(folder)/'starnet2.exe',folder)

if __name__=='__main__':unittest.main()
