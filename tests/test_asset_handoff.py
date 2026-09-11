"""Reject incomplete Git LFS downloads and changed handoff assets."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from check_v22_assets import verify


class AssetHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'artifacts').mkdir()
        self.path = self.root / 'artifacts/vision.pt'
        self.path.write_bytes(b'weights')
        self.manifest = {'files': [{'path': 'artifacts/vision.pt', 'bytes': 7,
                                   'sha256': hashlib.sha256(b'weights').hexdigest()}]}

    def test_verified_asset(self):
        self.assertEqual(verify(self.root, self.manifest), [])

    def test_lfs_pointer_is_not_a_weight(self):
        self.path.write_bytes(b'version https://git-lfs.github.com/spec/v1\n')
        self.assertIn('LFS pointer', verify(self.root, self.manifest)[0][1])

    def test_same_size_corruption(self):
        self.path.write_bytes(b'changed')
        self.assertIn('SHA256 mismatch', verify(self.root, self.manifest)[0][1])

    def test_missing_asset(self):
        self.path.unlink()
        self.assertIn('missing', verify(self.root, self.manifest)[0][1])

    def test_outside_asset_directory(self):
        self.manifest['files'][0]['path'] = '../outside'
        self.assertIn('outside artifacts', verify(self.root, self.manifest)[0][1])


if __name__ == '__main__':
    unittest.main()
