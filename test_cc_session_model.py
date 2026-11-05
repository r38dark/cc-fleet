import json, os, tempfile, unittest
from unittest import mock
import cc_limits as L


class SyntheticModel(unittest.TestCase):
    """Служебный ответ Claude Code («<synthetic>») — не модель: плитка Claude не должна его показывать."""
    def test_synthetic_reply_is_skipped(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, 's.jsonl'), 'w') as f:
            f.write(json.dumps({'type': 'assistant', 'message': {'model': 'claude-opus-5-5'}}) + '\n')
            f.write(json.dumps({'type': 'assistant', 'message': {'model': '<synthetic>'}}) + '\n')
        with mock.patch.object(L, 'screen_hardcopy', return_value=''), mock.patch.object(L, 'transcripts_dir', return_value=d), \
                mock.patch.object(L, 'all_models', return_value={'claude-opus-5-5': 'Opus 5.5'}):
            self.assertEqual(L.session_model(), 'claude-opus-5-5')


if __name__ == '__main__':
    unittest.main()
