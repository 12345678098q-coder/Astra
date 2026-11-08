import base64,unittest
from types import SimpleNamespace
from unittest.mock import patch
from core import pagefile
from core.resources import GIB,MIB,require_memory

class PagefileTest(unittest.TestCase):
 def test_bounded_growth_and_disk_reserve(self):
  with patch.object(pagefile,'managed_drives',return_value=['C:\\']),patch.object(pagefile.psutil,'virtual_memory',return_value=SimpleNamespace(total=4*GIB)),patch.object(pagefile.psutil,'swap_memory',return_value=SimpleNamespace(total=GIB)),patch.object(pagefile.shutil,'disk_usage',return_value=SimpleNamespace(total=128*GIB,free=20*GIB)):
   self.assertEqual(pagefile.growth_allowance(),8*GIB)
   with patch.object(pagefile.shutil,'disk_usage',return_value=SimpleNamespace(total=128*GIB,free=4*GIB)):
    self.assertEqual(pagefile.growth_allowance(),2*GIB)
   with patch.object(pagefile.shutil,'disk_usage',return_value=SimpleNamespace(total=128*GIB,free=GIB)):
    self.assertEqual(pagefile.growth_allowance(),0)
  with patch.object(pagefile,'managed_drives',return_value=[]):self.assertEqual(pagefile.growth_allowance(),0)
 def test_admission_accounts_for_growth_but_does_not_expand_blocks(self):
  plan=SimpleNamespace(budget=64*MIB)
  with patch('core.resources.plan_resources',return_value=plan),patch('core.resources.virtual_memory_available',return_value=GIB):
   with patch('core.pagefile.growth_allowance',return_value=2*GIB):self.assertIs(require_memory(int(1.17*GIB)),plan)
   with patch('core.pagefile.growth_allowance',return_value=0):
    with self.assertRaises(MemoryError):require_memory(int(1.17*GIB))
 def test_admin_command_is_enable_only(self):
  command=pagefile.enable_command();outer=base64.b64decode(command[-1]).decode('utf-16-le')
  self.assertIn('-Verb RunAs',outer);self.assertIn('-WindowStyle Hidden',outer)
  encoded=outer.split("'-EncodedCommand','",1)[1].split("'",1)[0]
  inner=base64.b64decode(encoded).decode('utf-16-le')
  self.assertIn('AutomaticManagedPagefile=$true',inner)
  self.assertNotIn('Remove-',inner);self.assertNotIn('Restart-',inner)
 def test_cancellation_and_failure_do_not_report_success(self):
  with patch.object(pagefile.os,'name','nt'),patch.object(pagefile.subprocess,'run',return_value=SimpleNamespace(returncode=1223)):
   with self.assertRaisesRegex(RuntimeError,'отменён'):pagefile.enable_system_management()
