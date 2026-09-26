import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from typst_runner import compile_typst


class TypstRunnerTests(unittest.TestCase):
    def test_landlock_confines_typst_to_project_and_disables_tcp(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            typ = project / "main.typ"
            typ.write_text("sandbox-input")
            font_dir = root / "fonts"
            font_dir.mkdir()
            secret_dir = root / "outside"
            secret_dir.mkdir(mode=0o700)
            secret = secret_dir / "secret"
            secret.write_text("not-visible")
            output = root / "project.pdf"
            fake_typst = root / "typst"
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            fake_typst.write_text(
                f"#!{sys.executable}\n"
                "import os, socket, sys\n"
                "uid = os.geteuid()\n"
                "db = os.environ.get('DB_URL', 'unset')\n"
                f"try: open({str(secret)!r}, 'rb').read(); outside = 'readable'\n"
                "except PermissionError: outside = 'blocked'\n"
                f"try: socket.create_connection(('127.0.0.1', {port}), timeout=1); network = 'connected'\n"
                "except PermissionError: network = 'blocked'\n"
                "except OSError as error: network = f'error:{error.errno}'\n"
                "contents = open(sys.argv[-2], 'rb').read().decode()\n"
                "open(sys.argv[-1], 'wb').write(f'%PDF-{uid}|{db}|{outside}|{network}|{contents}'.encode())\n"
            )
            fake_typst.chmod(0o755)

            try:
                with mock.patch("typst_runner.shutil.which", return_value=str(fake_typst)), \
                     mock.patch.dict(os.environ, {"DB_URL": "postgres://secret"}):
                    result = compile_typst(project, typ, output, font_dir)
            finally:
                listener.close()

            self.assertEqual(result.returncode, 0)
            pdf = output.read_text()
            uid, db_url, outside, network, contents = pdf.removeprefix("%PDF-").split("|")
            self.assertEqual(uid, str(os.geteuid()))
            self.assertEqual(db_url, "unset")
            self.assertEqual(outside, "blocked")
            self.assertEqual(network, "blocked")
            self.assertEqual(contents, "sandbox-input")


if __name__ == "__main__":
    unittest.main()
