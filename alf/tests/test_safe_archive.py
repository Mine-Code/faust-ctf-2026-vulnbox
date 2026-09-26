import io
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from safe_archive import UnsafeArchiveError, extract_archive


def make_tar(entries):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, kind, data in entries:
            member = tarfile.TarInfo(name)
            if kind == "dir":
                member.type = tarfile.DIRTYPE
                archive.addfile(member)
            elif kind == "symlink":
                member.type = tarfile.SYMTYPE
                member.linkname = data
                archive.addfile(member)
            elif kind == "hardlink":
                member.type = tarfile.LNKTYPE
                member.linkname = data
                archive.addfile(member)
            else:
                content = data
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
    buffer.seek(0)
    return buffer


class SafeArchiveTests(unittest.TestCase):
    def test_extracts_regular_files_and_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "project"
            destination.mkdir()
            archive = make_tar([
                ("main.typ", "file", b"#raw(\"safe\")"),
                ("assets", "dir", None),
                ("assets/note.txt", "file", b"safe asset"),
            ])

            main = extract_archive(archive, destination)

            self.assertEqual(main.read_bytes(), b"#raw(\"safe\")")
            self.assertEqual((destination / "assets/note.txt").read_bytes(), b"safe asset")

    def test_accepts_leading_current_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "project"
            destination.mkdir()
            archive = make_tar([
                ("./", "dir", None),
                ("./main.typ", "file", b"safe"),
            ])

            self.assertEqual(extract_archive(archive, destination).read_bytes(), b"safe")

    def test_rejects_symlinks_without_writing_anything(self):
        for target in ("/app/data", "../../victim/flag.typ"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temp:
                destination = Path(temp) / "project"
                destination.mkdir()
                archive = make_tar([
                    ("main.typ", "file", b"safe"),
                    ("leak", "symlink", target),
                ])

                with self.assertRaises(UnsafeArchiveError):
                    extract_archive(archive, destination)
                self.assertEqual(list(destination.iterdir()), [])

    def test_rejects_hardlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "project"
            destination.mkdir()
            archive = make_tar([
                ("main.typ", "file", b"safe"),
                ("leak", "hardlink", "main.typ"),
            ])

            with self.assertRaises(UnsafeArchiveError):
                extract_archive(archive, destination)
            self.assertEqual(list(destination.iterdir()), [])

    def test_rejects_traversal_and_duplicate_paths(self):
        cases = [
            [("../escape", "file", b"bad"), ("main.typ", "file", b"safe")],
            [("main.typ", "file", b"one"), ("main.typ", "file", b"two")],
            [("node", "file", b"file"), ("node/child", "file", b"bad")],
        ]
        for entries in cases:
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as temp:
                destination = Path(temp) / "project"
                destination.mkdir()
                with self.assertRaises(UnsafeArchiveError):
                    extract_archive(make_tar(entries), destination)
                self.assertEqual(list(destination.iterdir()), [])

    def test_rejects_archives_without_root_main_typ(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "project"
            destination.mkdir()
            archive = make_tar([("nested/main.typ", "file", b"safe")])

            with self.assertRaises(UnsafeArchiveError):
                extract_archive(archive, destination)


if __name__ == "__main__":
    unittest.main()
