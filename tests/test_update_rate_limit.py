import io,json,tempfile,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch
from processes.update_cache import github_json
from processes.tool_updates import update_tool,rc_update_summary

class UpdateRateTest(unittest.TestCase):
    def test_installed_graxpert_skips_github_but_checks_models(self):
        with patch('processes.tool_updates.find_tool',return_value=Path('GraXpert.exe')),patch('processes.tool_updates.request_json',side_effect=AssertionError('unexpected GitHub call')),patch('processes.tool_updates.graxpert_models') as models:
            update_tool('graxpert',False,'',lambda text:None)
            models.assert_called_once()
    def test_rate_limit_persists_and_cache_is_reused(self):
        url='https://api.github.com/repos/Steffenhir/GraXpert/releases/tags/3.1.0rc2'
        with tempfile.TemporaryDirectory() as folder:
            error=urllib.error.HTTPError(url,403,'rate limit exceeded',{'Retry-After':'3600'},None)
            with patch('processes.update_cache.urllib.request.urlopen',side_effect=error) as request:
                with self.assertRaises(RuntimeError):github_json(url,folder)
                with self.assertRaises(RuntimeError):github_json(url,folder)
                self.assertEqual(request.call_count,1)
        with tempfile.TemporaryDirectory() as folder:
            with patch('processes.update_cache.urllib.request.urlopen',return_value=io.BytesIO(json.dumps({'assets':[]}).encode())) as request:
                self.assertEqual(github_json(url,folder),{'assets':[]})
                self.assertEqual(github_json(url,folder),{'assets':[]});self.assertEqual(request.call_count,1)
    def test_rcastro_summary(self):
        output='{"event":"info","topic":"version","cliVersion":"2.6.10"}\n{"event":"info","topic":"updateList","current":"2.6.10","latest":"2.6.10","updateAvailable":false}'
        self.assertEqual(rc_update_summary(output),'RC-Astro: установлена 2.6.10, доступна 2.6.10 - актуальная версия')

if __name__=='__main__':unittest.main()
