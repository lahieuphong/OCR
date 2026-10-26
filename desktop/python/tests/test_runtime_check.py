"""Native-library diagnostic: authentication, isolation and import-only behavior."""
import io
import json
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "desktop" / "python"))
import vietdoc_desktop_server as desktop

ARGS = ["--repo-root", str(REPO), "--frontend-dist", "unused-frontend",
        "--model-lock", "unused-model-lock", "--paddlex-home", "qa-cache", "--check-runtime"]


class RuntimeCheckTests(unittest.TestCase):
    def test_malformed_token_is_refused_before_imports_or_stdin_handover(self):
        for token in ("", "not-a-token", "f" * 31, "x" * 64):
            with self.subTest(token_length=len(token)), \
                    patch.object(sys, "stdin", io.StringIO(token + "\n")), \
                    patch.object(sys, "stdout", io.StringIO()) as output, \
                    patch.object(desktop, "check_native_runtime") as check, \
                    patch.object(desktop, "detach_stdin") as detach:
                self.assertEqual(desktop.main(ARGS), 2)
                self.assertTrue(output.getvalue().startswith("VIETDOC_ERROR"))
                check.assert_not_called()
                detach.assert_not_called()

    def test_success_returns_one_json_line_and_never_opens_a_server(self):
        report = {"frozen": True, "versions": {"paddlepaddle": "3.2.0"}}
        pipe = Mock()

        def imported(*args):
            pipe.close.assert_called_once_with()
            print("dependency import diagnostic")
            return report

        with patch.object(sys, "stdin", io.StringIO("a" * 64 + "\n")), \
                patch.object(sys, "stdout", io.StringIO()) as output, \
                patch.object(sys, "stderr", io.StringIO()) as errors, \
                patch.object(desktop, "detach_stdin", return_value=pipe), \
                patch.object(desktop, "check_native_runtime", side_effect=imported), \
                patch.object(desktop, "bind_loopback") as bind, \
                patch.object(desktop, "build") as build, \
                patch.object(desktop.socket, "socket") as socket:
            self.assertEqual(desktop.main(ARGS), 0)
            lines = output.getvalue().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertTrue(lines[0].startswith("VIETDOC_RUNTIME "))
            self.assertEqual(json.loads(lines[0].split(" ", 1)[1]), report)
            self.assertIn("dependency import diagnostic", errors.getvalue())
            bind.assert_not_called()
            build.assert_not_called()
            socket.assert_not_called()

    def test_import_failure_is_nonzero_without_opening_a_server(self):
        with patch.object(sys, "stdin", io.StringIO("a" * 64 + "\n")), \
                patch.object(sys, "stdout", io.StringIO()) as output, \
                patch.object(desktop, "detach_stdin", return_value=Mock()), \
                patch.object(desktop, "check_native_runtime", side_effect=ImportError("missing native library")), \
                patch.object(desktop, "bind_loopback") as bind:
            self.assertEqual(desktop.main(ARGS), 1)
            self.assertIn("VIETDOC_ERROR native runtime import failed", output.getvalue())
            self.assertNotIn("VIETDOC_RUNTIME", output.getvalue())
            bind.assert_not_called()

    def test_frozen_imports_disable_downloads_and_do_not_construct_inference(self):
        modules = {}
        for name in ("paddle", "onnxruntime", "cv2", "pypdfium2", "paddleocr", "paddlex",
                     "paddlex.inference", "paddlex.inference.pipelines", "paddlex.inference.pipelines.components"):
            modules[name] = types.ModuleType(name)
        modules["paddle"].__version__ = "3.2.0"
        modules["onnxruntime"].__version__ = "1.31.0"
        modules["cv2"].__version__ = "4.10.0"
        detector, cropper, session = Mock(), Mock(), Mock()
        modules["paddleocr"].TextDetection = detector
        modules["paddlex.inference.pipelines.components"].CropByPolys = cropper
        modules["onnxruntime"].InferenceSession = session
        cache = Path("qa-runtime-cache").resolve()
        original_path = sys.path[:]

        def disable():
            self.assertEqual(os.environ["PADDLE_PDX_CACHE_HOME"], str(cache))
            self.assertEqual(os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"], "True")

        with patch.dict(sys.modules, modules), patch.dict(os.environ), \
                patch.object(sys, "frozen", True, create=True), \
                patch.object(desktop, "disable_model_downloads", side_effect=disable) as offline:
            report = desktop.check_native_runtime(Path("untrusted-repository"), cache)
            self.assertEqual(sys.path, original_path)
            self.assertTrue(report["frozen"])
            self.assertEqual(report["versions"]["onnxruntime"], "1.31.0")
            self.assertEqual(report["model_downloads"], "disabled")
            offline.assert_called_once_with()
            detector.assert_not_called()
            cropper.assert_not_called()
            session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
