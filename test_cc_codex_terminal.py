import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import cc_codex_terminal as T
import cc_codex_console as C


class Terminal(unittest.TestCase):
    def test_legacy_metadata_ignores_newly_installed_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(T.private_binary(d)); p.parent.mkdir(parents=True); p.write_text(''); p.chmod(0o755)
            self.assertTrue(T.target(d, d)['screen_rgb'])
            self.assertFalse(T.runtime({'pid':'123'}, d, d)['screen_rgb'])
            self.assertEqual(T.runtime({},d,d)['screen_bin'], '/usr/bin/screen')

    def test_untrusted_executable_or_namespace_is_never_used(self):
        for meta in ({'screen_bin':'/tmp/evil','screen_dir':'/tmp/socket'},
                     {'screen_bin':T.private_binary('/opt/cc-limits'),'screen_dir':'/tmp/socket'}):
            self.assertEqual(T.runtime(meta,'/opt/cc-limits','/home/user/codex_console'), T.legacy())

    def test_runtime_ctl_uses_saved_namespace_not_current_target(self):
        meta={'screen_bin':T.private_binary('/opt/cc-limits'),'screen_dir':'/home/user/codex_console/screen5'}
        with mock.patch.object(C,'BASE','/opt/cc-limits'), mock.patch.object(C,'_dir',return_value='/home/user/codex_console'), mock.patch.object(C,'_meta',return_value=meta), mock.patch.object(C.cc_codex,'wrap',return_value=(['safe-command'],{})) as wrap, mock.patch.object(C.subprocess,'run'):
            C._ctl(['-ls'])
        self.assertEqual(wrap.call_args.args[0], [meta['screen_bin'],'-ls'])
        self.assertEqual(wrap.call_args.args[2], {'SCREENDIR':meta['screen_dir']})

    def test_start_lookup_can_select_new_namespace_with_legacy_metadata(self):
        transport={'screen_bin':'approved','screen_dir':'private','screen_rgb':True}
        with mock.patch.object(C,'_known_pid') as known, mock.patch.object(C,'_ctl',return_value=mock.Mock(stdout=' 123.cc-codex (Detached)')) as ctl:
            self.assertEqual(C._pid(terminal=transport),'123')
        known.assert_not_called(); self.assertEqual(ctl.call_args.kwargs['terminal'],transport)

    def test_client_reads_metadata_and_returns_only_approved_paths(self):
        import subprocess,sys
        with tempfile.TemporaryDirectory() as d:
            meta=T.target(d,d)
            meta={'screen_bin':T.private_binary(d),'screen_dir':T.private_directory(d)}
            Path(d,'console.json').write_text(json.dumps(meta))
            result=subprocess.check_output([sys.executable,T.__file__,d,d],text=True).splitlines()
            self.assertEqual(result,[meta['screen_bin'],meta['screen_dir']])


if __name__ == '__main__': unittest.main()
