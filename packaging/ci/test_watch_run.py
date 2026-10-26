"""Portable watcher regressions; no Electron, backend build or model is required."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import watch_run


class WatchRunTest(unittest.TestCase):
    def test_backend_name_covers_native_macos_and_windows(self):
        for name in ("vietdoc-backend", "vietdoc-backend.exe", "VietDoc-Backend.EXE"):
            self.assertTrue(watch_run.is_backend(name))
        for name in (None, "", "python", "not-vietdoc-backend"):
            self.assertFalse(watch_run.is_backend(name))

    def test_system_path_never_carries_user_tools(self):
        source = {"SystemRoot": r"C:\WINDOWS", "PATH": "/evil/bin"}
        self.assertEqual(watch_run.system_path(source, "darwin"), "/usr/bin:/bin:/usr/sbin:/sbin")
        self.assertEqual(watch_run.system_path(source, "linux"), "/usr/bin:/bin:/usr/sbin:/sbin")
        self.assertEqual(watch_run.system_path(source, "win32"),
                         r"C:\WINDOWS\System32;C:\WINDOWS;C:\WINDOWS\System32\Wbem")

    def test_large_stdout_and_stderr_do_not_block_the_app(self):
        with tempfile.TemporaryDirectory() as directory:
            # Do not use --strict here: the test runner itself shares the Python installation
            # directory with the watched executable and is intentionally still running.
            command = [sys.executable, str(Path(watch_run.__file__)), "--exe", sys.executable,
                       "--out", directory, "--system-path", "--timeout", "10", "--", "-c",
                       "import sys; sys.stdout.write('a'*200000 + 'OUT-END'); sys.stderr.write('b'*200000 + 'ERR-END')"]
            result = subprocess.run(command, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(Path(directory, "run_watch.json").read_text(encoding="utf-8"))
            self.assertFalse(report["timed_out"], report)
            self.assertEqual(report["exit_code"], 0, report)
            self.assertEqual(len(report["stdout"]), 2000)
            self.assertTrue(report["stdout"].endswith("OUT-END"))
            self.assertTrue(report["stderr"].endswith("ERR-END"))
            self.assertEqual(report["launcher_env_path"], watch_run.system_path(os.environ))


if __name__ == "__main__":
    unittest.main()
