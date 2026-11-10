"""Build the Windows release of VietDoc OCR: Setup (NSIS) and Portable (ZIP), both with the verified models.

Run on the owner's Windows build machine with the packaging virtual environment (packaging/README.md, sections 1
and 8), from any folder:

  <packaging venv>\\Scripts\\python.exe packaging\\windows\\build_release.py --out <empty folder outside the checkout>
      --model-root <folder holding vietocr\\onnx\\exp_b_width1024 and vietocr\\finetuned\\exp_b_width1024\\weights.pth>
      --paddlex-home <folder holding official_models\\PP-OCRv6_medium_det>
      [--channel internal|public] [--allow-dirty] [--reuse-backend <earlier work\\backend-dist>]
      [--vietocr-license <VietOCR LICENSE>]

Every step stops the build when it fails:
  1. checks: Windows, this interpreter is a packaging venv, npm, the checksum-verified Electron binary, node_modules
     matching the lockfiles, the installed paddleocr equal to the vendored PaddleOCR/, the output folder outside the
     checkout and empty, the Git tree (public: always clean; internal: clean or --allow-dirty, recorded);
  2. stages the model files into <out>/work/staging as copies with their locked SHA-256 (never links to the source);
  3. builds the frontend and the PyInstaller backend (or reuses one with --reuse-backend);
  4. collects the licence notices (collect_notices.py) into resources/licenses;
  5. builds the folder app with electron-builder.release.yml (public: release-public.yml) and the internal smoke
     variant electron-builder.release-smoke.yml (QA only, never in the release folder), from junctions in
     desktop\\out\\ that are always removed again;
  6. checks the folder app: Electron fuses, the bundle scan (no documents, keys, secrets or machine paths; model
     weights only the locked files), path lengths for a typical profile, signature status;
  7. makes the Setup from that exact folder (--prepackaged) and the Portable ZIP from the same folder, and reads the
     whole ZIP back against the folder; with full 7-Zip installed it also compares the Setup's payload;
  8. writes <out>/release/ (the two files, SHA256SUMS.txt, BUILD_INFO.txt, guide, release notes, notices) and
     <out>/reports/build_report.json.

Nothing is uploaded, tagged or published, and nothing is installed. A public build also needs
desktop/build-resources/PUBLIC_LICENSE.txt, the licence text approved by the owner (release/LICENSING_AUDIT.md),
and the evidence gate release/check_release_candidate.py before anything is uploaded.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.metadata as md
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DESKTOP = REPO / "desktop"
FRONTEND = REPO / "demo" / "local_pdf_ocr" / "frontend"
sys.path.insert(0, str(HERE))
import collect_notices  # noqa: E402
import portable_zip  # noqa: E402

CONFIGS = {"internal": "electron-builder.release.yml", "public": "electron-builder.release-public.yml"}
SMOKE_CONFIG = "electron-builder.release-smoke.yml"
PUBLIC_LICENSE = DESKTOP / "build-resources" / "PUBLIC_LICENSE.txt"
INTERNAL_NOTICE = DESKTOP / "build-resources" / "INTERNAL_NOTICE.txt"
GUIDES = REPO / "release" / "windows"
EXE = "VietDoc OCR.exe"
FUSES = ("RunAsNode is Disabled", "EnableNodeOptionsEnvironmentVariable is Disabled",
         "EnableNodeCliInspectArguments is Disabled", "EnableEmbeddedAsarIntegrityValidation is Enabled",
         "OnlyLoadAppFromAsar is Enabled", "GrantFileProtocolExtraPrivileges is Disabled")
# The longest file path must fit Windows' 260-character limit (LongPathsEnabled is off by default) under a
# typical install and extract location of a user whose profile folder name has 20 characters.
PROFILE = "C:\\Users\\" + "u" * 20
MAX_PATH_FILE = 259


class BuildError(RuntimeError):
    pass


def release_names(version: str, channel: str) -> dict[str, str]:
    if channel not in CONFIGS:
        raise BuildError(f"Unknown channel: {channel}")
    if not re.fullmatch(r"\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?", version):
        raise BuildError(f"Not a release version: {version}")
    stem = f"VietDoc-OCR-v{version}" + ("-INTERNAL" if channel == "internal" else "") + "-Windows-x64"
    return {"setup": f"{stem}-Setup.exe", "portable": f"{stem}-Portable.zip"}


def channel_gate(channel: str, dirty: bool, allow_dirty: bool, public_license: Path = PUBLIC_LICENSE, *,
                 reuse_backend: bool = False, licence_inputs: tuple = ()) -> None:
    """A public build needs a commit, the owner-approved licence text, its licence inputs and a backend built from that
    commit; an internal one may record its changes."""
    if channel == "public" and reuse_backend:
        raise BuildError("A public build builds its own backend: --reuse-backend is for internal builds only.")
    if channel == "public" and not all(path and Path(path).is_file() for path in licence_inputs):
        raise BuildError("A public build needs --vietocr-license and the detector's model card (README.md).")
    if dirty and (channel == "public" or not allow_dirty):
        raise BuildError("The Git tree has uncommitted changes" + (" (a public build needs a commit)" if channel == "public"
                         else "; commit them or pass --allow-dirty (internal only)."))
    if channel == "public" and not public_license.is_file():
        raise BuildError("BLOCKED: a public build needs desktop/build-resources/PUBLIC_LICENSE.txt, the licence "
                         "text approved by the owner (release/LICENSING_AUDIT.md).")


def has_utf8_code_page(exe: Path) -> bool:
    """The backend's embedded manifest asks for the UTF-8 code page (Paddle's ANSI file APIs, see the spec)."""
    data = exe.read_bytes()
    return re.search(rb"<activeCodePage[^>]*>\s*UTF-8\s*</activeCodePage>", data) is not None


def short_path(value: str) -> str:
    """The 8.3 short form of an existing path (PROGRA~1 style), which some tools write into files instead."""
    if sys.platform != "win32" or not value or not os.path.exists(value):
        return ""
    import ctypes
    buffer = ctypes.create_unicode_buffer(1024)
    size = ctypes.windll.kernel32.GetShortPathNameW(value, buffer, 1024)
    return buffer.value if 0 < size < 1024 and buffer.value != value else ""


def inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def check_out_dir(out: Path, repo: Path = REPO) -> None:
    if not out.is_absolute():
        raise BuildError(f"--out must be an absolute path: {out}")
    if inside(out, repo) or inside(repo, out):
        raise BuildError(f"--out must be outside the checkout ({repo}): {out}")
    if out.exists() and any(out.iterdir()):
        raise BuildError(f"--out must be a new or empty folder: {out}")


def path_budget(app_dir: Path, portable_stem: str) -> dict:
    longest = max((str(p.relative_to(app_dir)) for p in app_dir.rglob("*")), key=len)
    prefixes = {"setup": PROFILE + "\\AppData\\Local\\Programs\\VietDoc OCR\\",
                "portable": PROFILE + "\\Downloads\\" + portable_stem + "\\" + portable_zip.APP_FOLDER + "\\"}
    budget = {name: {"prefix_chars": len(prefix), "total_chars": len(prefix) + len(longest),
                     "margin": MAX_PATH_FILE - len(prefix) - len(longest)} for name, prefix in prefixes.items()}
    return {"longest_relative": longest, "longest_chars": len(longest), "limit": MAX_PATH_FILE, **budget,
            "result": "PASS" if all(b["margin"] >= 0 for b in budget.values()) else "FAIL"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def locked_model_files(lock_file: Path) -> dict[str, str]:
    """Staging path (relative to the staging folder) -> SHA-256, from desktop/model_lock.json."""
    lock = json.loads(lock_file.read_text(encoding="utf-8"))
    rec, det = lock["recognizer"], lock["detector"]
    files = {"models/vietocr/onnx/exp_b_width1024/encoder.onnx": rec["encoder_sha256"],
             "models/vietocr/onnx/exp_b_width1024/decoder_step.onnx": rec["decoder_sha256"],
             "models/vietocr/finetuned/exp_b_width1024/weights.pth": rec["checkpoint_sha256"]}
    files.update({f"paddlex/official_models/{det['model_name']}/{name}": digest for name, digest in det["files"].items()})
    return files


def stage_models(model_root: Path, paddlex_home: Path, lock_file: Path, staging: Path) -> dict:
    """Copy exactly the files OCR needs, verifying each locked SHA-256 before and after the copy."""
    sources = {"models": model_root, "paddlex": paddlex_home}
    # contract.py also reads these two records of the frozen export (it checks their content at run time).
    extra = ["models/vietocr/onnx/exp_b_width1024/metadata.json", "models/vietocr/onnx/exp_b_width1024/parity_full.json"]
    staged = {}
    for rel, expected in list(locked_model_files(lock_file).items()) + [(rel, None) for rel in extra]:
        top, rest = rel.split("/", 1)
        source = sources[top].joinpath(*rest.split("/"))
        if not source.is_file():
            raise BuildError(f"Model file missing: {source}")
        if expected and sha256(source) != expected:
            raise BuildError(f"Model file differs from model_lock.json: {source}")
        target = staging.joinpath(*rel.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        digest = sha256(target)
        if expected and digest != expected:
            raise BuildError(f"Copy differs from the source: {target}")
        staged[rel] = {"sha256": digest, "bytes": target.stat().st_size, "locked": bool(expected)}
    return staged


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], check=True, capture_output=True).stdout.decode("utf-8", "replace")


def git_state() -> dict:
    head = git("rev-parse", "HEAD").strip()
    status = [line for line in git("status", "--porcelain=v1", "--untracked-files=all").splitlines() if line]
    digest = hashlib.sha256(subprocess.run(["git", "-C", str(REPO), "diff", "HEAD", "--binary"], check=True,
                                           capture_output=True).stdout)
    for line in sorted(status):
        if line.startswith("?? "):
            path = REPO / line[3:].strip('"')
            digest.update(line[3:].encode("utf-8"))
            if path.is_file():
                digest.update(path.read_bytes())
    return {"head": head, "dirty": bool(status), "changes": status,
            "working_tree_sha256": digest.hexdigest() if status else None}


def check_node_modules(folder: Path) -> int:
    """Every package of package-lock.json is installed at its locked version (else: run npm ci)."""
    lock = json.loads((folder / "package-lock.json").read_text(encoding="utf-8"))
    wrong = []
    for key, entry in lock.get("packages", {}).items():
        if not key.startswith("node_modules/") or entry.get("optional") or "version" not in entry:
            continue
        manifest = folder / key / "package.json"
        if not manifest.is_file() or json.loads(manifest.read_text(encoding="utf-8")).get("version") != entry["version"]:
            wrong.append(key)
    if wrong:
        raise BuildError(f"{folder}: {len(wrong)} package(s) differ from package-lock.json (run npm ci): {wrong[:5]}")
    return len(lock.get("packages", {})) - 1


def check_vendored_paddleocr() -> int:
    """The packaging venv's paddleocr must be the vendored PaddleOCR/ of this checkout (packaging/README.md, 1)."""
    import importlib.util
    spec = importlib.util.find_spec("paddleocr")   # locates the package without importing it
    if spec is None or not spec.origin:
        raise BuildError("paddleocr is not installed in this environment (packaging/README.md, section 1).")
    installed = Path(spec.origin).resolve().parent
    vendored = REPO / "PaddleOCR" / "paddleocr"
    names = sorted(p.relative_to(vendored) for p in vendored.rglob("*.py"))
    different = [str(n) for n in names if not (installed / n).is_file()
                 or (installed / n).read_bytes().replace(b"\r\n", b"\n") != (vendored / n).read_bytes().replace(b"\r\n", b"\n")]
    if different or not names:
        raise BuildError(f"Installed paddleocr differs from PaddleOCR/ (reinstall it, packaging/README.md 1): {different[:5]}")
    return len(names)


class Builder:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.out = args.out
        self.work, self.reports, self.release = self.out / "work", self.out / "reports", self.out / "release"
        self.logs = self.reports / "logs"
        self.report: dict = {"schema": "vietdoc-windows-release-build-v1", "channel": args.channel, "steps": []}
        self.npm = shutil.which("npm.cmd") or shutil.which("npm")
        self.npx = shutil.which("npx.cmd") or shutil.which("npx")

    # -- helpers ------------------------------------------------------------------------------------------------
    def run(self, name: str, command: list[str], cwd: Path, env: dict | None = None) -> str:
        self.logs.mkdir(parents=True, exist_ok=True)
        log = self.logs / f"{name}.log"
        started = time.monotonic()
        with log.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write("$ " + subprocess.list2cmdline(command) + "\n")
            stream.flush()
            proc = subprocess.run(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            text = proc.stdout.decode("utf-8", "replace")
            stream.write(text)
        if proc.returncode:
            raise BuildError(f"{name} failed (exit {proc.returncode}); log: {log}")
        self.report.setdefault("commands", {})[name] = {"seconds": round(time.monotonic() - started, 1), "log": log.name}
        return text

    def step(self, name: str, function, *args):
        print(f"== {name}", flush=True)
        started = time.monotonic()
        result = function(*args)
        self.report["steps"].append({"name": name, "seconds": round(time.monotonic() - started, 1)})
        return result

    def signature(self, path: Path) -> str:
        env = {**os.environ, "VIETDOC_SIGNATURE_PATH": str(path)}
        proc = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                               "(Get-AuthenticodeSignature -LiteralPath $env:VIETDOC_SIGNATURE_PATH).Status.ToString()"],
                              capture_output=True, env=env)
        return proc.stdout.decode("utf-8", "replace").strip() or "unknown"

    # -- steps --------------------------------------------------------------------------------------------------
    def preflight(self) -> None:
        args = self.args
        if sys.platform != "win32":
            raise BuildError("The Windows release is built on Windows.")
        if sys.prefix == sys.base_prefix or "packaging" not in Path(sys.prefix).name.lower():
            raise BuildError(f"Run this with the packaging venv's python.exe (now: {sys.executable}).")
        if not (self.npm and self.npx):
            raise BuildError("npm and npx are required (Node.js 22).")
        if not (DESKTOP / "node_modules" / "electron" / "dist" / "electron.exe").is_file():
            raise BuildError("Electron binary missing: run npm ci and node node_modules/electron/install.js in desktop/.")
        check_out_dir(self.out)
        for name in ("model_root", "paddlex_home"):
            if not getattr(args, name).is_dir():
                raise BuildError(f"--{name.replace('_', '-')} is not a folder: {getattr(args, name)}")
        state = git_state()
        card = args.paddlex_home / "official_models" / "PP-OCRv6_medium_det" / "README.md"
        channel_gate(args.channel, state["dirty"], args.allow_dirty, reuse_backend=bool(args.reuse_backend),
                     licence_inputs=(args.vietocr_license, card))
        version = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))["version"]
        self.names = release_names(version, args.channel)
        notes = GUIDES / f"RELEASE_NOTES_v{version}.md"
        if args.channel == "public" and not notes.is_file():
            raise BuildError(f"Release notes missing: {notes}")
        self.report.update({"version": version, "names": self.names, "source": state,
                            "node_modules": {"desktop": check_node_modules(DESKTOP), "frontend": check_node_modules(FRONTEND)},
                            "paddleocr_vendored_files": check_vendored_paddleocr(),
                            "build_machine": {"os": platform.platform(), "python": sys.version.split()[0]}})
        self.out.mkdir(parents=True, exist_ok=True)

    def stage(self) -> None:
        staging = self.work / "staging"
        self.report["models"] = stage_models(self.args.model_root, self.args.paddlex_home, DESKTOP / "model_lock.json", staging)

    def frontend(self) -> None:
        self.run("frontend-build", [self.npm, "run", "build"], FRONTEND)
        if not (FRONTEND / "dist" / "index.html").is_file():
            raise BuildError("Frontend build produced no dist/index.html")

    def backend(self) -> None:
        if self.args.reuse_backend:
            source = self.args.reuse_backend
            if not (source / "vietdoc-backend" / "vietdoc-backend.exe").is_file():
                raise BuildError(f"--reuse-backend has no vietdoc-backend\\vietdoc-backend.exe: {source}")
            self.backend_dist = source
            self.report["backend"] = {"reused": str(source),
                                      "exe_sha256": sha256(source / "vietdoc-backend" / "vietdoc-backend.exe")}
            return
        self.backend_dist = self.work / "backend-dist"
        self.run("backend-pyinstaller", [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                                         "--distpath", str(self.backend_dist), "--workpath", str(self.work / "backend-build"),
                                         str(REPO / "packaging" / "backend" / "vietdoc-backend.spec")], REPO)
        self.report["backend"] = {"reused": None, "pyinstaller": md.version("pyinstaller")}

    def notices(self) -> None:
        card = self.args.paddlex_home / "official_models" / "PP-OCRv6_medium_det" / "README.md"
        summary = collect_notices.collect(self.backend_dist / "vietdoc-backend", REPO, self.work / "licenses",
                                          card if card.is_file() else None, self.args.vietocr_license)
        self.report["notices"] = {k: summary[k] for k in ("components", "needs_review", "copyleft")}

    def apps(self) -> None:
        links = {DESKTOP / "out" / "backend" / "vietdoc-backend": self.backend_dist / "vietdoc-backend",
                 DESKTOP / "out" / "models": self.work / "staging" / "models",
                 DESKTOP / "out" / "paddlex": self.work / "staging" / "paddlex",
                 DESKTOP / "out" / "licenses": self.work / "licenses"}
        import _winapi
        for link in links:
            if os.path.lexists(link):
                raise BuildError(f"Staging link already exists (remove the link, never its target): {link}")
        created = []
        try:
            for link, target in links.items():
                link.parent.mkdir(parents=True, exist_ok=True)
                _winapi.CreateJunction(str(target), str(link))
                created.append(link)
            config = CONFIGS[self.args.channel]
            for name, cfg in (("app-release", config), ("app-smoke", SMOKE_CONFIG)):
                self.run(f"electron-{name}", [self.npx, "electron-builder", "--win", "dir", "--x64", "--config", cfg,
                                              f"--config.directories.output={self.work / name}"], DESKTOP)
        finally:
            for link in reversed(created):
                if os.path.isjunction(link):
                    os.rmdir(link)   # removes the junction only, never its target
        self.app = self.work / "app-release" / "win-unpacked"
        self.smoke_app = self.work / "app-smoke" / "win-unpacked"
        if not (self.app / EXE).is_file():
            raise BuildError(f"Folder app missing: {self.app / EXE}")

    def checks(self) -> None:
        fuses = self.run("fuses", ["node", str(DESKTOP / "node_modules/@electron/fuses/dist/bin.js"), "read", "--app",
                                   str(self.app / EXE)], DESKTOP)
        missing = [f for f in FUSES if f not in fuses]
        if missing:
            raise BuildError(f"Electron fuses not as expected: {missing}")
        backend_exe = self.app / "resources/backend/vietdoc-backend/vietdoc-backend.exe"
        if not has_utf8_code_page(backend_exe):
            raise BuildError("The backend has no activeCodePage UTF-8 manifest (packaging/backend/vietdoc-backend.spec): "
                             "OCR would fail under non-ASCII folders.")
        forbid = [str(REPO), os.environ.get("USERPROFILE", ""), str(self.out), sys.prefix,
                  str(self.args.model_root), str(self.args.paddlex_home), str(self.backend_dist)]
        forbid += [short_path(value) for value in list(forbid)]
        command = [sys.executable, "-B", str(REPO / "packaging" / "ci" / "scan_bundle.py"), str(self.app),
                   str(self.reports / "scan-release"), "--allow-locked-models", str(DESKTOP / "model_lock.json")]
        for value in filter(None, forbid):
            command += ["--forbid-string", value]
        self.run("scan-release", command, REPO)
        scan = json.loads((self.reports / "scan-release" / "scan.json").read_text(encoding="utf-8"))
        with (self.reports / "scan-release" / "manifest.tsv").open(encoding="utf-8") as stream:
            next(stream)
            rows = (line.rstrip("\n").split("\t") for line in stream)
            self.scanned = {path: digest for path, _, digest in rows}
        budget = path_budget(self.app, Path(self.names["portable"]).stem)
        self.report["checks"] = {"fuses": "PASS", "scan": {"result": scan["result"], "files": scan["files"],
                                                           "bytes": scan["bytes"], "locked_models": len(scan["locked_models"])},
                                 "paths": budget}
        if budget["result"] != "PASS":
            raise BuildError(f"Paths too long for a typical profile: {budget}")
        smoke_manifest = portable_zip.file_manifest(self.smoke_app)
        release_manifest = portable_zip.file_manifest(self.app)
        differ = sorted(n for n in release_manifest.keys() | smoke_manifest.keys()
                        if release_manifest.get(n) != smoke_manifest.get(n))
        self.report["checks"]["smoke_variant_differs_only_in"] = differ
        if differ != sorted([EXE, "resources/app.asar"]):
            raise BuildError(f"The smoke variant differs from the release in more than the app and its executable: {differ}")

    def setup(self) -> None:
        output = self.work / "setup"
        self.run("electron-setup", [self.npx, "electron-builder", "--win", "nsis", "--x64", "--prepackaged", str(self.app),
                                    "--config", CONFIGS[self.args.channel], f"--config.directories.output={output}"], DESKTOP)
        built = output / self.names["setup"]
        if not built.is_file():
            raise BuildError(f"Setup not found under its release name: {built}")
        self.release.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(built, self.release / self.names["setup"])
        seven_zip = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "7-Zip" / "7z.exe"
        if not seven_zip.is_file() and self.args.channel == "public":
            raise BuildError("A public build compares the Setup's payload with the checked app: install full 7-Zip.")
        if not seven_zip.is_file():
            self.report["setup_payload"] = {"result": "NOT RUN", "reason": "full 7-Zip is not installed; compare an install instead"}
            return
        outer, inner = self.work / "setup-unpacked", self.work / "setup-app"
        self.run("setup-extract", [str(seven_zip), "x", str(built), f"-o{outer}", "-y"], self.work)
        payload = list(outer.rglob("app-64.7z"))
        if len(payload) != 1:
            raise BuildError("Expected exactly one app-64.7z in the Setup")
        self.run("setup-extract-app", [str(seven_zip), "x", str(payload[0]), f"-o{inner}", "-y"], self.work)
        sys.path.insert(0, str(HERE))
        from check_installer_payload import verify
        result = verify(self.app, inner, EXE)
        self.report["setup_payload"] = result
        if result["result"] != "PASS":
            raise BuildError(f"Setup payload differs from the checked app: {result}")

    def portable(self) -> None:
        notice = INTERNAL_NOTICE if self.args.channel == "internal" else PUBLIC_LICENSE
        extras = {"DOC_TRUOC_KHI_CHAY.txt": GUIDES / "DOC_TRUOC_KHI_CHAY_PORTABLE.txt", notice.name: notice}
        missing = [str(p) for p in extras.values() if not p.is_file()]
        if missing:
            raise BuildError(f"Portable guide files missing: {missing}")
        target = self.release / self.names["portable"]
        portable_zip.make(self.app, target, extras)
        result = portable_zip.verify(target, self.app, extras, expected=self.scanned)
        self.report["portable_zip"] = {k: v for k, v in result.items() if k in ("result", "files", "app_files")} | (
            {} if result["result"] == "PASS" else result)
        if result["result"] != "PASS":
            raise BuildError(f"Portable ZIP differs from the checked app: {result}")

    def finish(self) -> None:
        version = self.report["version"]
        docs = {"HUONG_DAN_CAI_DAT.md": GUIDES / "HUONG_DAN_CAI_DAT.md",
                f"RELEASE_NOTES_v{version}.md": GUIDES / f"RELEASE_NOTES_v{version}.md",
                "THIRD_PARTY_NOTICES.txt": self.work / "licenses" / "THIRD_PARTY_NOTICES.txt"}
        notice = INTERNAL_NOTICE if self.args.channel == "internal" else PUBLIC_LICENSE
        docs[notice.name] = notice
        for name, source in docs.items():
            if source.is_file():
                shutil.copyfile(source, self.release / name)
        files = [self.names["setup"], self.names["portable"]]
        sums = {name: sha256(self.release / name) for name in files}
        (self.release / "SHA256SUMS.txt").write_text("".join(f"{sums[n]}  {n}\n" for n in files), encoding="utf-8", newline="\n")
        signatures = {name: self.signature(path) for name, path in
                      ((EXE, self.app / EXE), ("vietdoc-backend.exe", self.app / "resources/backend/vietdoc-backend/vietdoc-backend.exe"),
                       (self.names["setup"], self.release / self.names["setup"]))}
        models = self.report["models"]
        source = self.report["source"]
        commit = source["head"] + (f" + uncommitted changes (working tree sha256 {source['working_tree_sha256']})"
                                   if source["dirty"] else "")
        versions = {name: md.version(name) for name in ("paddlepaddle", "paddlex", "onnxruntime", "pymupdf", "pyinstaller")}
        electron = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))["devDependencies"]["electron"]
        lines = [f"VietDoc OCR {version} - Windows x64",
                 "Channel: " + ("INTERNAL TEST BUILD - not for distribution" if self.args.channel == "internal" else "public"),
                 f"Source: {commit}",
                 f"Built: {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} on {platform.platform()}",
                 f"Electron {electron}; Python {sys.version.split()[0]}; " + "; ".join(f"{k} {v}" for k, v in versions.items()),
                 "Models (offline, checked by SHA-256 before OCR):"]
        lines += [f"  {rel} {info['sha256']}" for rel, info in models.items() if info["locked"]]
        lines += ["Code signing: " + ("UNSIGNED" if all(s == "NotSigned" for s in signatures.values()) else json.dumps(signatures)),
                  "Automatic updates: none. Model downloads: none.",
                  *[f"SHA-256 {sums[n]}  {n}" for n in files]]
        (self.release / "BUILD_INFO.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        self.report.update({"release_files": {n: {"bytes": (self.release / n).stat().st_size, "sha256": sums[n]} for n in files},
                            "signatures": signatures, "versions": versions | {"electron": electron},
                            "folder_app": {"bytes": sum(p.stat().st_size for p in self.app.rglob("*") if p.is_file()),
                                           "files": sum(1 for p in self.app.rglob("*") if p.is_file())}})

    def build(self) -> dict:
        self.step("preflight", self.preflight)
        try:
            self.step("stage models", self.stage)
            self.step("frontend", self.frontend)
            self.step("backend", self.backend)
            self.step("licence notices", self.notices)
            self.step("folder apps", self.apps)
            self.step("checks", self.checks)
            self.step("setup", self.setup)
            self.step("portable", self.portable)
            self.step("release folder", self.finish)
            self.report["result"] = "PASS"
        except Exception as error:   # any failure still leaves a report saying where the build stopped
            self.report["result"] = "FAIL"
            self.report["error"] = f"{type(error).__name__}: {error}"
            raise BuildError(str(error)) from error
        finally:
            self.reports.mkdir(parents=True, exist_ok=True)
            (self.reports / "build_report.json").write_text(json.dumps(self.report, ensure_ascii=False, indent=1) + "\n",
                                                            encoding="utf-8", newline="\n")
        return self.report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--paddlex-home", type=Path, required=True)
    parser.add_argument("--channel", choices=sorted(CONFIGS), default="internal")
    parser.add_argument("--allow-dirty", action="store_true", help="internal builds only: build uncommitted changes (recorded)")
    parser.add_argument("--reuse-backend", type=Path, help="an earlier work\\backend-dist folder")
    parser.add_argument("--vietocr-license", type=Path, help="the VietOCR library's LICENSE file, for the notices")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        report = Builder(parse_args(argv)).build()
    except BuildError as error:
        print(f"BUILD FAILED: {error}", file=sys.stderr)
        return 1
    print(json.dumps({k: report[k] for k in ("result", "names", "release_files")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
