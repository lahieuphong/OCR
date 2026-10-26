"""Dependency closure checks work without macOS; native CI supplies real otool output."""
from pathlib import Path
import tempfile
import unittest

from check_native_dependencies import audit, parse_load_commands, parse_minimum_macos


class NativeDependenciesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "backend"
        self.root.mkdir()
        self.commands = {}
        self.binary("vietdoc-backend")

    def binary(self, name, deps=(), rpaths=(), minimum_versions=("14.0",)):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes.fromhex("cffaedfe") + b"test binary")
        self.commands[path.resolve()] = (list(deps), list(rpaths), list(minimum_versions))
        return path

    def report(self):
        return audit(self.root, reader=lambda path: self.commands[path])

    def test_parser_reads_imports_and_rpaths_but_not_a_dylibs_own_identity(self):
        output = """Load command 0
          cmd LC_ID_DYLIB
         name /old/build/libfoo.dylib (offset 24)
        Load command 1
          cmd LC_LOAD_DYLIB
         name @rpath/libbar.dylib (offset 24)
        Load command 2
          cmd LC_RPATH
         path @loader_path/../libraries (offset 12)
        """
        self.assertEqual(parse_load_commands(output),
                         (["@rpath/libbar.dylib"], ["@loader_path/../libraries"]))

    def test_dependencies_resolve_inside_bundle_and_system_shared_cache(self):
        self.binary("vietdoc-backend", ["@rpath/libfoo.dylib"], ["@executable_path/_internal"])
        self.binary("_internal/libfoo.dylib", ["/usr/lib/libSystem.B.dylib", "@loader_path/libgcc_s.1.1.dylib"])
        self.binary("_internal/libgcc_s.1.1.dylib")
        self.assertEqual(self.report()["result"], "PASS")
        self.assertEqual(self.report()["binaries"], 3)

    def test_missing_gcc_runtime_fails_even_with_a_valid_rpath(self):
        self.binary("vietdoc-backend", ["@rpath/libgomp.1.dylib"], ["@loader_path/_internal"])
        report = self.report()
        self.assertEqual(report["result"], "FAIL")
        self.assertEqual(report["findings"][0]["dependency"], "@rpath/libgomp.1.dylib")

    def test_homebrew_absolute_dependency_and_search_path_fail(self):
        self.binary("vietdoc-backend", ["/opt/homebrew/opt/gcc/lib/libgomp.1.dylib"],
                    ["/opt/homebrew/opt/gcc/lib"])
        report = self.report()
        self.assertEqual(report["result"], "FAIL")
        self.assertEqual(len(report["findings"]), 2)

    def test_loader_path_cannot_escape_to_an_existing_library_outside_bundle(self):
        (self.root.parent / "outside.dylib").write_bytes(bytes.fromhex("cffaedfe"))
        self.binary("vietdoc-backend", ["@loader_path/../outside.dylib"])
        self.assertEqual(self.report()["result"], "FAIL")

    def test_build_version_and_legacy_deployment_targets_are_read(self):
        output = """Load command 0
          cmd LC_BUILD_VERSION
        minos 15.0
          sdk 15.4
        Load command 1
          cmd LC_VERSION_MIN_MACOSX
      version 13.3
          sdk 14.0
        """
        self.assertEqual(parse_minimum_macos(output), ["15.0", "13.3"])

    def test_newer_os_requirement_fails_the_advertised_target(self):
        self.binary("_internal/libgomp.1.dylib", minimum_versions=("16.0",))
        report = self.report()
        self.assertEqual(report["result"], "FAIL")
        self.assertEqual(report["highest_minimum_macos"], "16.0")
        self.assertTrue(any(item["reason"] == "requires a newer macOS" for item in report["findings"]))

    def test_matching_and_older_os_requirements_pass(self):
        self.binary("_internal/libgomp.1.dylib", minimum_versions=("15.0",))
        report = self.report()
        self.assertEqual(report["result"], "PASS")
        self.assertEqual(report["highest_minimum_macos"], "15.0")

    def test_no_native_binaries_cannot_pass(self):
        (self.root / "vietdoc-backend").write_text("placeholder", encoding="utf-8")
        self.assertEqual(self.report()["result"], "FAIL")


if __name__ == "__main__":
    unittest.main()
