"""Compare the OCR responses of a clean-machine run (run_sandbox_qa.ps1) with a development reference run.

  python compare_sandbox.py <results folder> <reference folder of check_packaged_ocr.py --dev-python>

Every <results>/ocr_*/<file>__<mode>.json (and vn_out/ocr_*) must equal the reference response of the same name,
timing fields aside and numbers compared by value. Prints a JSON summary; exit code 1 on any difference.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_packaged_ocr import differences, strip_timing  # noqa: E402


def compare(results: Path, reference: Path) -> dict:
    summary = {"compared": 0, "identical": 0, "missing_reference": [], "different": {}}
    for response in sorted(list(results.glob("ocr_*/*.json")) + list(results.glob("vn_out/ocr_*/*.json"))):
        ref = reference / response.name
        if not ref.is_file():
            summary["missing_reference"].append(str(response.relative_to(results)))
            continue
        found = differences(strip_timing(json.loads(response.read_text(encoding="utf-8-sig"))),
                            strip_timing(json.loads(ref.read_text(encoding="utf-8"))))
        summary["compared"] += 1
        if found:
            summary["different"][str(response.relative_to(results))] = found[:5]
        else:
            summary["identical"] += 1
    summary["result"] = "PASS" if summary["compared"] and not summary["different"] and not summary["missing_reference"] else "FAIL"
    return summary


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    summary = compare(Path(sys.argv[1]), Path(sys.argv[2]))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if summary["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
