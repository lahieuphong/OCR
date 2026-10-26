#!/usr/bin/env bash
# Native build only; invoked by CI after installing requirements-macos.txt and npm lockfiles.
set -euo pipefail
test "$(uname -s)" = Darwin
test "$(uname -m)" = arm64
: "${OUT:?Set OUT to an absolute build folder outside the checkout}"
: "${VPY:?Set VPY to the packaging venv Python}"
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
"$VPY" - "$ROOT" "$OUT" <<'PY'
from pathlib import Path
import sys
root, out = (Path(p).resolve() for p in sys.argv[1:])
if not Path(sys.argv[2]).is_absolute() or out == root or root in out.parents:
    raise SystemExit('OUT must be an absolute folder outside the checkout')
PY
mkdir -p "$OUT/report" "$OUT/download" "$OUT/empty-paddlex"
"$VPY" -m pip freeze --all > "$OUT/report/python-versions.txt"
"$VPY" -W error -m compileall -q demo/local_pdf_ocr desktop/python desktop/scripts packaging .github/scripts
"$VPY" .github/scripts/run_backend_tests.py
for dir in desktop/python/tests packaging/backend packaging/ci packaging/macos; do
  "$VPY" -m unittest discover -v -s "$dir" -p 'test_*.py' 2>&1 | tee "$OUT/report/tests-${dir//\//-}.txt"
  if grep -q 'skipped=' "$OUT/report/tests-${dir//\//-}.txt"; then exit 1; fi
done
npm --prefix desktop test
npm --prefix demo/local_pdf_ocr/frontend test
npm --prefix demo/local_pdf_ocr/frontend run build

# Check native inference libraries before freezing; importing must not download models.
PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True "$VPY" -c 'import paddle,paddlex,paddleocr,onnxruntime,cv2; print("Paddle",paddle.__version__,"ONNX Runtime",onnxruntime.__version__,"OpenCV",cv2.__version__)' > "$OUT/report/native-runtime.txt"

# Include the native libraries in the executable, never weights or documents.
"$VPY" -m PyInstaller --noconfirm --clean --distpath "$OUT/backend-dist" --workpath "$OUT/backend-build" packaging/backend/vietdoc-backend.spec 2>&1 | tee "$OUT/report/pyinstaller.txt"
"$VPY" packaging/macos/check_native_dependencies.py "$OUT/backend-dist/vietdoc-backend" "$OUT/report/native-dependencies.json" --minimum-macos 15.0
LINK="$ROOT/desktop/out/backend/vietdoc-backend"
if [ -e "$LINK" ] || [ -L "$LINK" ]; then
  echo 'Backend staging path already exists; refusing to replace it.' >&2
  exit 1
fi
mkdir -p "$(dirname "$LINK")"
ln -s "$OUT/backend-dist/vietdoc-backend" "$LINK"
cleanup() { if [ -L "$LINK" ]; then rm "$LINK"; fi; }
trap cleanup EXIT
cd "$ROOT/desktop"
for kind in release smoke; do
  config=electron-builder.macos.yml
  if [ "$kind" = smoke ]; then config=electron-builder.macos-smoke.yml; fi
  npx --no-install electron-builder --mac dir --arm64 --config "$config" "--config.directories.output=$OUT/$kind"
done
cd "$ROOT"
APP="$OUT/release/mac-arm64/VietDoc OCR.app"
SMOKE_APP="$OUT/smoke/mac-arm64/VietDoc OCR.app"
for kind in release smoke; do
  app="$OUT/$kind/mac-arm64/VietDoc OCR.app"
  codesign --verify --deep --strict "$app"
done
node desktop/node_modules/@electron/fuses/dist/bin.js read --app "$APP" | tee "$OUT/report/fuses.txt"
for expected in 'RunAsNode is Disabled' 'EnableNodeOptionsEnvironmentVariable is Disabled' \
  'EnableNodeCliInspectArguments is Disabled' 'EnableEmbeddedAsarIntegrityValidation is Enabled' \
  'OnlyLoadAppFromAsar is Enabled' 'GrantFileProtocolExtraPrivileges is Disabled'; do
  grep -q "$expected" "$OUT/report/fuses.txt"
done
"$VPY" desktop/scripts/make_synthetic_pdf.py "$OUT/synthetic.pdf"
node demo/local_pdf_ocr/frontend/scripts/export_metadata_fixtures.mjs "$OUT/fixtures"
"$VPY" desktop/scripts/make_metadata_fixtures.py "$OUT/fixtures"
# Exercise the frozen inference libraries too, with no weights and no listener.
"$VPY" - "$APP/Contents/Resources" "$OUT/report/runtime-probe.json" <<'PY'
import json, secrets, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path('packaging/ci').resolve()))
from probe_backend import backend_command, probe_environment
resources, output = map(Path, sys.argv[1:])
exe = backend_command(str(resources))
qa_home = output.parent / 'runtime-check-paddlex'
qa_home.mkdir()
args = [exe, '--repo-root', str(resources), '--frontend-dist', str(resources / 'frontend'),
        '--model-lock', str(resources / 'model_lock.json'), '--paddlex-home', str(qa_home), '--check-runtime']
result = subprocess.run(args, input=secrets.token_hex(32) + '\n', text=True, capture_output=True,
                        cwd=resources, env=probe_environment(exe), timeout=180)
if result.returncode:
    raise SystemExit(result.stdout + result.stderr)
line = next((line for line in result.stdout.splitlines() if line.startswith('VIETDOC_RUNTIME ')), None)
if line is None:
    raise SystemExit('Frozen runtime did not return its diagnostic: ' + result.stdout + result.stderr)
report = json.loads(line.removeprefix('VIETDOC_RUNTIME '))
assert report['frozen'] is True and report['model_downloads'] == 'disabled', report
assert report['versions']['paddlepaddle'] == '3.2.0', report
assert report['versions']['onnxruntime'] == '1.31.0', report
output.write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report))
PY
"$VPY" packaging/ci/probe_backend.py "$APP/Contents/Resources" "$OUT/report/backend-probe.json" "$OUT/synthetic.pdf"

# A user can install into a folder containing spaces and Unicode; exercise that native path too.
mkdir -p "$OUT/Ứng dụng thử"
ditto "$SMOKE_APP" "$OUT/Ứng dụng thử/VietDoc OCR.app"
"$VPY" packaging/ci/watch_run.py --strict --system-path \
  --exe "$OUT/Ứng dụng thử/VietDoc OCR.app/Contents/MacOS/VietDoc OCR" --out "$OUT/report/smoke-watch" \
  --unset VIETDOC_MODEL_ROOT --set "VIETDOC_PADDLEX_HOME=$OUT/empty-paddlex" --timeout 600 -- \
  "--smoke-test=$OUT/report/smoke" "--smoke-pdf=$OUT/synthetic.pdf" "--smoke-batch-dir=$OUT/fixtures" --smoke-timeout=540
node desktop/scripts/check-smoke-report.js "$OUT/report/smoke/smoke_report.json" --expect=no-models --with-pdf
"$VPY" desktop/scripts/check_excel_export.py "$OUT/report/smoke/downloads/Danh_sach_van_ban.xlsx" --rows=3 --expected-json="$OUT/report/smoke/batch_expected.json"
test -z "$(ls -A "$OUT/empty-paddlex")"
"$VPY" packaging/ci/watch_run.py --strict --system-path --expect-exit 2 \
  --exe "$APP/Contents/MacOS/VietDoc OCR" --out "$OUT/report/release-gate" --timeout 60 -- \
  "--user-data-dir=$OUT/report/release-gate/userData" "--smoke-test=$OUT/report/release-gate/smoke"
test ! -e "$OUT/report/release-gate/smoke/smoke_report.json"

# Both app bundles must pass the private-material scan before any download is created.
for kind in release smoke; do
  "$VPY" packaging/ci/scan_bundle.py "$OUT/$kind/mac-arm64/VietDoc OCR.app" "$OUT/report/scan-$kind" --allow-internal-symlinks --forbid-string "$ROOT"
done

# DMG is made from the exact app that passed the checks, without rebuilding it.
cd "$ROOT/desktop"
npx --no-install electron-builder --mac dmg --arm64 --prepackaged "$APP" --config electron-builder.macos.yml "--config.directories.output=$OUT/download"
cd "$ROOT"
DMG="$(find "$OUT/download" -maxdepth 1 -name '*.dmg' -print)"
test -n "$DMG"
hdiutil verify "$DMG"
mkdir -p "$OUT/mount"
hdiutil attach "$DMG" -readonly -nobrowse -mountpoint "$OUT/mount"
trap 'hdiutil detach "$OUT/mount" || true; cleanup' EXIT
codesign --verify --deep --strict "$OUT/mount/VietDoc OCR.app"
cmp "$APP/Contents/Resources/app.asar" "$OUT/mount/VietDoc OCR.app/Contents/Resources/app.asar"
hdiutil detach "$OUT/mount"
trap cleanup EXIT
cp packaging/macos/README.md "$OUT/download/README.md"
(cd "$OUT/download" && shasum -a 256 ./*.dmg > SHA256SUMS.txt)
# electron-builder emits debug/config files beside targets; only deliver the allowlisted files.
"$VPY" - "$OUT/download" <<'PY'
from pathlib import Path
import sys
for p in Path(sys.argv[1]).iterdir():
    if p.is_file() and p.suffix != '.dmg' and p.name not in {'README.md', 'SHA256SUMS.txt'}:
        p.unlink()
PY
