"""Exercise native spec assembly without running a platform-specific freeze."""
from pathlib import Path
import os
import tempfile
import runpy
import sys
import types
import unittest
from unittest.mock import patch

SPEC = Path(__file__).with_name("vietdoc-backend.spec")


def assemble(platform):
    hooks = types.ModuleType("PyInstaller.utils.hooks")
    hooks.collect_data_files = lambda *a, **k: []
    hooks.collect_dynamic_libs = lambda *a, **k: []
    hooks.collect_submodules = lambda package: [package]
    hooks.copy_metadata = lambda package: []
    result = {}

    def analysis(*args, **kwargs):
        result["analysis"] = kwargs
        return types.SimpleNamespace(
            binaries=[("paddle/libs/libpaddle.dylib", "paddle.dylib", "BINARY"),
                      ("onnxruntime/capi/libonnxruntime.dylib", "ort.dylib", "BINARY")],
            datas=[], pure=[], scripts=[])

    def executable(*args, **kwargs):
        result["exe"] = kwargs
        return object()

    def collect(*args, **kwargs):
        result["binaries"] = args[1]

    with tempfile.TemporaryDirectory() as tmp, \
            patch.dict(os.environ, {"VIETDOC_GCC_LIBDIR": tmp}), \
            patch.dict(sys.modules, {"PyInstaller.utils.hooks": hooks}), \
            patch("sys.platform", platform), patch("importlib.metadata.distributions", return_value=[]):
        for name in ("libgomp.1.dylib", "libgcc_s.1.1.dylib", "libgcc_s.1.dylib"):
            Path(tmp, name).touch()
        runpy.run_path(str(SPEC), init_globals={
            "SPECPATH": str(SPEC.parent), "Analysis": analysis, "PYZ": lambda *a: object(),
            "EXE": executable, "COLLECT": collect})
    return result


class NativeSpecTests(unittest.TestCase):
    def test_windows_retains_the_existing_traced_runtime(self):
        build = assemble("win32")
        self.assertIn("_winapi", build["analysis"]["hiddenimports"])
        self.assertIn("asyncio.windows_events", build["analysis"]["hiddenimports"])
        self.assertIsNone(build["exe"]["target_arch"])

    def test_windows_backend_opens_models_from_any_folder_name(self):
        # Paddle opens model files through ANSI APIs: the UTF-8 code page keeps a Vietnamese folder name working.
        import xml.dom.minidom
        manifest = assemble("win32")["exe"]["manifest"]
        dom = xml.dom.minidom.parseString(manifest)
        settings = {node.localName: node.firstChild.data for node in dom.getElementsByTagName("*")
                    if node.namespaceURI and "WindowsSettings" in node.namespaceURI}
        self.assertEqual(settings, {"longPathAware": "true", "activeCodePage": "UTF-8"})
        self.assertNotIn("requireAdministrator", manifest)
        self.assertIsNone(assemble("darwin")["exe"]["manifest"])

    def test_mac_assembles_a_native_backend_without_windows_extensions(self):
        build = assemble("darwin")
        imports = build["analysis"]["hiddenimports"]
        self.assertEqual(build["exe"]["target_arch"], "arm64")
        for module in ("_winapi", "_wmi", "winreg", "asyncio.windows_events"):
            self.assertNotIn(module, imports)
        for module in ("_scproxy", "_posixsubprocess", "asyncio.unix_events", "paddle.base.libpaddle"):
            self.assertIn(module, imports)
        # Shared trimming rules must not remove the native inference libraries.
        self.assertEqual(len(build["binaries"]), 2)
        collected = {Path(source).name: destination for source, destination in build["analysis"]["binaries"]}
        self.assertEqual(collected["libgomp.1.dylib"], ".")
        self.assertEqual(collected["libgcc_s.1.1.dylib"], ".")


if __name__ == "__main__":
    unittest.main()
