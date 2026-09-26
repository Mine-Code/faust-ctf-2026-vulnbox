import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from user_storage import ensure_user_directory


class UserStorageTests(unittest.TestCase):
    def test_recreates_missing_user_directory_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / "data"
            user_path = ensure_user_directory(data, "user-123")

            self.assertTrue(user_path.is_dir())
            self.assertEqual(os.stat(user_path).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(data).st_mode & 0o777, 0o700)

            user_path.rmdir()
            self.assertEqual(ensure_user_directory(data, "user-123"), user_path)

    def test_rejects_symlinked_user_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "data"
            data.mkdir()
            outside = root / "outside"
            outside.mkdir()
            (data / "user-123").symlink_to(outside, target_is_directory=True)

            with self.assertRaises(ValueError):
                ensure_user_directory(data, "user-123")

    def test_rejects_path_components_in_user_id(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                ensure_user_directory(temp, "../outside")


if __name__ == "__main__":
    unittest.main()
