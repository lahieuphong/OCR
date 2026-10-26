"""Platform and lifecycle regressions for the packaged-backend probe (no models)."""
import io
import os
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

import probe_backend as probe


class ProbeBackendTest(unittest.TestCase):
    def test_packaged_binary_name_matches_each_platform(self):
        for platform, name in (("win32", "vietdoc-backend.exe"), ("darwin", "vietdoc-backend"),
                               ("linux", "vietdoc-backend")):
            self.assertEqual(os.path.basename(probe.backend_command("resources", platform=platform)), name)

    def test_macos_backend_environment_drops_shell_and_loader_overrides(self):
        source = {"HOME": "/Users/test", "TMPDIR": "/tmp/user", "LANG": "en_US.UTF-8",
                  "PATH": "/evil/bin", "PYTHONPATH": "/evil", "DYLD_LIBRARY_PATH": "/evil",
                  "DYLD_INSERT_LIBRARIES": "/evil.dylib", "LD_LIBRARY_PATH": "/evil",
                  "VIETDOC_MODEL_ROOT": "/unverified", "HTTPS_PROXY": "http://evil:1"}
        env = probe.probe_environment("/Applications/VietDoc OCR.app/Contents/Resources/backend/vietdoc-backend/vietdoc-backend",
                                      platform="darwin", source=source)
        self.assertEqual(set(env), {"HOME", "TMPDIR", "LANG", "PATH", "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"})
        self.assertEqual(env["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"], "True")
        self.assertTrue(env["PATH"].endswith(":/usr/local/bin:/usr/bin:/bin"))
        self.assertNotIn("/evil", env["PATH"])

    def test_windows_probe_keeps_system_paths_without_user_path(self):
        env = probe.probe_environment(r"D:\app\backend\vietdoc-backend.exe", platform="win32",
                                      source={"SystemRoot": r"C:\WINDOWS", "PATH": r"C:\evil", "HOME": "evil"})
        self.assertEqual(env["PATH"], r"D:\app\backend;D:\app\backend\_internal;C:\WINDOWS\System32;C:\WINDOWS;C:\WINDOWS\System32\Wbem")
        self.assertNotIn("HOME", env)

    def test_posix_launch_does_not_request_windows_creation_flags(self):
        with patch.object(probe.subprocess, "Popen") as popen:
            proc = probe.launch(["backend"], {"PATH": "/usr/bin"}, "/resources", "token", platform="darwin")
            self.assertEqual(popen.call_args.kwargs["creationflags"], 0)
            self.assertEqual(popen.call_args.kwargs["env"], {"PATH": "/usr/bin"})
            proc.stdin.write.assert_called_once_with(b"token\n")

    def test_readiness_decodes_utf8_and_enforces_timeout(self):
        class Ready:
            stdout = io.BytesIO("VIETDOC_ERROR Không khởi động được\n".encode())
        self.assertEqual(probe.read_line(Ready())[0], "VIETDOC_ERROR Không khởi động được")
        release = threading.Event()
        class Blocked:
            class stdout:
                @staticmethod
                def readline():
                    release.wait(2)
                    return b""
        try:
            with self.assertRaises(TimeoutError):
                probe.read_line(Blocked(), timeout=0.01)
        finally:
            release.set()

    def test_cleanup_terminates_a_live_backend_and_closes_its_pipes(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            probe.cleanup([proc])
            self.assertIsNotNone(proc.poll())
            self.assertTrue(all(stream.closed for stream in (proc.stdin, proc.stdout, proc.stderr)))
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
