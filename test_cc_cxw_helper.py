import importlib.machinery,importlib.util,unittest
from pathlib import Path
from unittest import mock
path=Path(__file__).with_name('cc-codex-console-localize');loader=importlib.machinery.SourceFileLoader('cxw_helper',str(path));spec=importlib.util.spec_from_loader(loader.name,loader);H=importlib.util.module_from_spec(spec);loader.exec_module(H)
class CxwHelper(unittest.TestCase):
 def test_live_console_is_never_recreated_or_scanned(self):
  with mock.patch.object(H,'screen_pid',return_value=10),mock.patch.object(H,'processes') as processes,mock.patch.object(H,'run') as command,mock.patch.object(H,'start_console') as start:
   H.main();processes.assert_not_called();command.assert_not_called();start.assert_not_called()
 def test_missing_console_starts_without_restarting_panel(self):
  with mock.patch.object(H,'screen_pid',return_value=None),mock.patch.object(H,'processes',return_value=[]),mock.patch.object(H,'run') as command,mock.patch.object(H,'start_console',return_value=True) as start:
   H.main();command.assert_not_called();start.assert_called_once()
 def test_separate_live_cli_is_not_replaced(self):
  with mock.patch.object(H,'screen_pid',return_value=None),mock.patch.object(H,'processes',return_value=[(12,1,'pts/5','./node_modules/.bin/codex resume --last --all')]),mock.patch.object(H,'run') as command,mock.patch.object(H,'start_console') as start:
   with self.assertRaises(SystemExit):H.main()
   command.assert_not_called();start.assert_not_called()
 def test_start_failure_is_reported_without_another_attempt(self):
  with mock.patch.object(H,'screen_pid',return_value=None),mock.patch.object(H,'processes',return_value=[]),mock.patch.object(H,'start_console',return_value=False) as start:
   with self.assertRaises(SystemExit):H.main()
   start.assert_called_once()
 def test_live_entry_does_not_open_lock_in_readonly_environment(self):
  with mock.patch.object(H,'screen_pid',return_value=10),mock.patch('builtins.open',side_effect=OSError('read-only')) as opened,mock.patch.object(H,'start_console') as start:
   H.entry();opened.assert_not_called();start.assert_not_called()
 def test_check_mode_never_starts_missing_console(self):
  with mock.patch.object(H,'screen_pid',return_value=None),mock.patch.object(H,'start_console') as start,mock.patch('builtins.open') as opened:
   with self.assertRaises(SystemExit):H.check()
   start.assert_not_called();opened.assert_not_called()
if __name__=='__main__':unittest.main()
