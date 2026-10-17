"""The H1 freeze on a synthetic repository: line endings, weights, missing files, the registration, v1 manifests."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from experiments.hybrid_h1 import freeze as frozen
from experiments.hybrid_h1.hybrid import gates_sha256

LF, CRLF = b"\n", b"\r\n"
MODEL = "models/vietocr/onnx/exp_b_width1024"
TEXT = {
    "experiments/hybrid_h1/gates.py": "GATES = 1\nTHRESHOLD = 0.5\n",
    "experiments/hybrid_h1/hybrid.py": "VERSION = 'h1_v1'\n",
    "experiments/hybrid_h1/blind_criteria_v1.json": '{\n "min_pdfs": 10\n}\n',
    "datasets/lexicon.txt": "# agency\nBo Tai chinh\nBo Noi vu\n",
}
FILES = {group: [] for group in frozen.FROZEN_FILES}
FILES.update({"candidate": ["experiments/hybrid_h1/gates.py", "experiments/hybrid_h1/hybrid.py"],
              "criteria": ["experiments/hybrid_h1/blind_criteria_v1.json"], "reference_data": ["datasets/lexicon.txt"],
              "models": [f"{MODEL}/metadata.json", f"{MODEL}/encoder.onnx", f"{MODEL}/decoder_step.onnx"]})
DETECTOR = "~/.paddlex/official_models/PP-OCRv6_medium_det"


def put(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


class Freeze(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.repo, self.detector = self.root / "repo", self.root / "detector"
        for path, text in TEXT.items():
            put(self.repo / path, text.encode("utf-8"))
        weights = {"encoder.onnx": b"onnx" + CRLF + b"encoder", "decoder_step.onnx": b"onnx" + CRLF + b"decoder"}
        for name, data in weights.items():
            put(self.repo / MODEL / name, data)
        metadata = {"selected": "phase4_exp_b_width1024", "checkpoint_sha256": "c" * 64, "config_sha256": "d" * 64,
                    "encoder_sha256": hashlib.sha256(weights["encoder.onnx"]).hexdigest(),
                    "decoder_sha256": hashlib.sha256(weights["decoder_step.onnx"]).hexdigest()}
        put(self.repo / MODEL / "metadata.json", json.dumps(metadata, indent=1).encode("utf-8"))
        for name, data in {"inference.json": b'{\n "x": 1\n}\n', "inference.pdiparams": b"params" + CRLF + b"end",
                           "inference.yml": b"a: 1\n"}.items():
            put(self.detector / name, data)
        for name, value in {"REPO": self.repo, "DETECTOR": self.detector, "FROZEN_FILES": FILES}.items():
            patcher = mock.patch.object(frozen, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.prereg = self.root / "h1_preregistration.json"
        code = {Path(p).name: hashlib.sha256(TEXT[p].encode("utf-8")).hexdigest() for p in FILES["candidate"]}
        self.prereg.write_text(json.dumps({"registered_at": "2026-10-16T00:00:00+00:00", "gates_sha256": gates_sha256(),
                                           "code_sha256": code}), encoding="utf-8")

    def to_crlf(self, relative: str) -> None:
        path = self.repo / relative
        path.write_bytes(path.read_bytes().replace(LF, CRLF))

    def freeze(self, name="freeze") -> Path:
        return Path(frozen.write(self.root / name, self.prereg)["manifest"])

    def test_lf_and_crlf_checkouts_of_the_same_content_verify_alike(self):
        manifest = self.freeze()
        self.to_crlf("experiments/hybrid_h1/gates.py")
        self.to_crlf("datasets/lexicon.txt")
        result = frozen.verify(manifest)
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(len(result["notes"]), 2)
        self.assertTrue(all("other line endings" in note for note in result["notes"]))
        path = self.repo / "datasets/lexicon.txt"
        path.write_bytes(path.read_bytes().replace(b"Bo Noi vu", b"Bo Noi vu."))
        self.assertEqual(frozen.verify(manifest)["problems"], ["reference_data: datasets/lexicon.txt differs"])

    def test_weights_are_hashed_byte_for_byte(self):
        manifest = self.freeze()
        path = self.detector / "inference.pdiparams"
        path.write_bytes(path.read_bytes().replace(CRLF, LF))
        self.assertEqual(frozen.verify(manifest)["problems"], [f"detector: {DETECTOR}/inference.pdiparams differs"])

    def test_missing_weights_are_reported_and_block_a_new_freeze(self):
        manifest = self.freeze()
        (self.repo / MODEL / "encoder.onnx").unlink()
        (self.repo / MODEL / "metadata.json").unlink()
        problems = frozen.verify(manifest)["problems"]
        self.assertIn(f"models: {MODEL}/encoder.onnx is missing", problems)
        self.assertIn(f"models: {MODEL}/metadata.json is missing", problems)
        self.assertTrue(any(p.startswith("b1024 differs") for p in problems))
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.freeze("freeze2")
        self.assertFalse((self.root / "freeze2").exists())

    def test_the_candidate_must_match_its_registration_and_the_manifest_is_lf(self):
        candidate = self.repo / "experiments/hybrid_h1/hybrid.py"
        candidate.write_bytes(b"VERSION = 'h1_v2'\n")
        with self.assertRaisesRegex(ValueError, "registration"):
            self.freeze("refused")
        self.assertFalse((self.root / "refused").exists())
        candidate.write_bytes(TEXT["experiments/hybrid_h1/hybrid.py"].encode("utf-8").replace(LF, CRLF))
        manifest = self.freeze()  # a CRLF checkout of the registered candidate is the registered candidate
        data = manifest.read_bytes()
        self.assertNotIn(CRLF, data)
        recorded = json.loads(data)
        self.assertEqual((recorded["schema"], recorded["hashing"]), ("h1_freeze_manifest_v2", frozen.HASHING))
        self.assertEqual(set(recorded["raw_sha256"]["models"]), {f"{MODEL}/metadata.json"})
        self.assertTrue((self.root / "freeze/source/experiments/hybrid_h1/hybrid.py").is_file())
        copy = self.root / "manifest_crlf.json"
        copy.write_bytes(data.replace(LF, CRLF))
        self.assertEqual(frozen.verify(copy)["manifest_sha256"], frozen.verify(manifest)["manifest_sha256"])

    def test_a_v1_manifest_is_compared_on_raw_bytes(self):
        recorded = json.loads(self.freeze().read_text(encoding="utf-8"))
        v1 = {k: v for k, v in recorded.items() if k not in ("hashing", "raw_sha256")}
        v1.update({"schema": "h1_freeze_manifest_v1", "files": frozen.raw_hashes(recorded)})
        path = self.root / "v1.json"
        path.write_text(json.dumps(v1), encoding="utf-8")
        self.assertTrue(frozen.verify(path)["ok"])
        self.to_crlf("datasets/lexicon.txt")
        self.assertEqual(frozen.verify(path)["problems"], ["reference_data: datasets/lexicon.txt differs"])


if __name__ == "__main__":
    unittest.main()
