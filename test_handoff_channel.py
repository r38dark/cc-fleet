import tempfile, unittest
from cc_claude_profile import ClaudeProfile

class ChannelTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.snap=dict(thread_id='11111111-1111-1111-1111-111111111111',model='claude-sonnet-5-5',effort='xhigh')
    def command(self, cfg, **extra):
        return ClaudeProfile(dict(BASE=self.tmp.name,cfg=lambda:cfg)).command(dict(self.snap,**extra),dict(access='full'),'test')
    def test_preserve_explicit_channel_and_sandbox(self):
        a=self.command({},telegram_channel=True,sandbox_root=True)
        self.assertEqual(a[a.index('--channels')+1], 'plugin:telegram@claude-plugins-official')
        self.assertIn('IS_SANDBOX=1',a)
        self.assertEqual(a[a.index('--resume')+1],self.snap['thread_id'])
    def test_no_channel_or_sandbox_without_previous_settings(self):
        a=self.command({})
        self.assertNotIn('--channels',a); self.assertNotIn('IS_SANDBOX=1',a)
    def test_existing_channel_and_sandbox_not_duplicated(self):
        a=self.command(dict(claude_cmd='IS_SANDBOX=1 claude --channels plugin:telegram@claude-plugins-official'),telegram_channel=True,sandbox_root=True)
        self.assertEqual(a.count('--channels'),1);self.assertEqual(a.count('IS_SANDBOX=1'),1)
