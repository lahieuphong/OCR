"""Tests for collect_notices.py on a synthetic backend folder and checkout (no real build needed)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_notices  # noqa: E402


def write(root: Path, rel: str, text: str = "x") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class CollectNoticesTest(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp())
        self.backend, self.repo, self.out = base / "vietdoc-backend", base / "repo", base / "licenses"
        internal = self.backend / "_internal"
        write(internal, "tidy-1.0.dist-info/METADATA", "Name: tidy\nVersion: 1.0\nLicense-Expression: MIT\n")
        write(internal, "tidy-1.0.dist-info/licenses/LICENSE", "MIT text")
        write(internal, "pymupdf-1.28.2.dist-info/METADATA",
              "Name: PyMuPDF\nVersion: 1.28.2\nLicense: Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License\n")
        write(internal, "pymupdf-1.28.2.dist-info/top_level.txt", "fitz\npymupdf\n")
        write(internal, "pymupdf/COPYING", "AGPL text")
        write(internal, "mystery-2.0.dist-info/METADATA", "Name: mystery\nVersion: 2.0\n")
        write(internal, "classified-3.0.dist-info/METADATA",
              "Name: classified\nVersion: 3.0\nClassifier: License :: OSI Approved :: BSD License\n")
        write(internal, "classified-3.0.dist-info/LICENSE.txt", "BSD text")
        write(internal, "paddle/libs/msvcp140.dll", "dll")
        write(self.repo, "desktop/package.json", json.dumps({"version": "0.1.0", "devDependencies": {"electron": "44.6.0"}}))
        write(self.repo, "PaddleOCR/LICENSE", "Apache text")
        write(self.repo, "desktop/node_modules/electron/dist/ffmpeg.dll", "dll")
        write(self.repo, "desktop/node_modules/electron/dist/libEGL.dll", "dll")
        front = self.repo / "demo/local_pdf_ocr/frontend"
        write(front, "package-lock.json", json.dumps({"packages": {
            "": {"name": "app"},
            "node_modules/react": {"version": "19.1.1", "license": "MIT"},
            "node_modules/vite": {"version": "6.3.5", "license": "MIT", "dev": True},
            "node_modules/maybe": {"version": "1.0.0", "license": "ISC", "devOptional": True},
            "node_modules/@scope/lib": {"version": "2.0.0", "license": "MPL-2.0"},
            "node_modules/@scope/lib/node_modules/react": {"version": "19.1.1", "license": "MIT"},
            "node_modules/@scope/lib/node_modules/isarray": {"version": "1.0.0", "license": "MIT"},
        }}))
        write(front, "node_modules/react/LICENSE", "React MIT")
        write(front, "node_modules/@scope/lib/LICENSE.md", "MPL text")
        self.card = write(base, "card/README.md", "---\nlicense: apache-2.0\n---\nModel card")
        self.vietocr = write(base, "vietocr/LICENSE", "Apache text")

    def collect(self):
        return collect_notices.collect(self.backend, self.repo, self.out, self.card, self.vietocr)

    def test_every_component_is_listed_with_its_licence_files(self):
        summary = self.collect()
        items = {c["name"]: c for c in summary["items"]}
        self.assertEqual(items["tidy"]["licence"], "MIT")
        self.assertEqual(items["tidy"]["files"], ["python/tidy/LICENSE"])
        self.assertEqual(items["PyMuPDF"]["files"], ["python/PyMuPDF/COPYING"])
        self.assertEqual(items["classified"]["licence"], "BSD License")
        self.assertEqual(items["react"]["files"], ["npm/react/LICENSE"])
        self.assertEqual([c["name"] for c in summary["items"]].count("react"), 1)   # nested copy listed once
        self.assertEqual(items["isarray"]["review"], "no licence file in the package")
        self.assertNotIn("vite", items)        # development only: not in the frontend build
        self.assertNotIn("maybe", items)
        self.assertEqual((self.out / "npm/react/LICENSE").read_text(encoding="utf-8"), "React MIT")
        self.assertEqual(items["PP-OCRv6_medium_det (text detector weights)"]["licence"], "apache-2.0")
        self.assertTrue((self.out / "models/PP-OCRv6_medium_det/MODEL_CARD.md").is_file())
        self.assertTrue((self.out / "models/VietOCR/LICENSE").is_file())
        self.assertIn("msvcp140.dll", items["Microsoft Visual C++ runtime"]["detail"])

    def test_copyleft_unknown_models_runtime_and_the_app_need_review(self):
        summary = self.collect()
        review = {c["name"] for c in summary["items"] if c["review"]}
        self.assertEqual(summary["copyleft"], ["@scope/lib", "PyMuPDF"])
        self.assertNotIn("Microsoft D3DCompiler", {c["name"] for c in summary["items"]})   # not shipped in this fixture
        for name in ("PyMuPDF", "mystery", "@scope/lib", "Microsoft Visual C++ runtime", "VietDoc OCR (this application)",
                     "FFmpeg (Chromium's media library)", "NSIS installer and plug-ins (Setup only)",
                     "PP-OCRv6_medium_det (text detector weights)",
                     "VietOCR B1024 (recognizer weights, fine-tuned from vgg_transformer)"):
            self.assertIn(name, review)
        for name in ("tidy", "react", "classified"):
            self.assertNotIn(name, review)
        text = (self.out / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8")
        self.assertIn("not a licence grant or a legal clearance", text)
        self.assertIn("== NEEDS REVIEW", text)
        self.assertEqual(json.loads((self.out / "notices.json").read_text(encoding="utf-8"))["needs_review"], len(review))

    def test_refuses_a_non_empty_output_or_a_folder_that_is_not_a_backend(self):
        write(self.out, "old.txt")
        with self.assertRaises(SystemExit):
            self.collect()
        with self.assertRaises(SystemExit):
            collect_notices.collect(self.repo, self.repo, self.out.parent / "other")


if __name__ == "__main__":
    unittest.main()
