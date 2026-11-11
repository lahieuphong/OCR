"""Publish a checked public Windows build as a GitHub Release (the owner runs this; the models never go through CI).

  python packaging/windows/publish_github_release.py --release-dir <build>/release --repo lahieuphong/OCR [--publish]

Stops before touching GitHub unless:
  - the build is the public channel and was made from a clean checkout at the commit HEAD points to (BUILD_INFO.txt),
  - SHA256SUMS.txt matches the Setup and the Portable ZIP, and latest.yml names the Setup and its SHA-512,
  - the tag v<version> does not exist yet (or already points at that commit) and no release uses it.
Then: annotated tag v<version> on that commit (pushed), a DRAFT release with the body below, every asset uploaded and its
SHA-256 (GitHub's digest) compared with the local file. Only with --publish is the draft published and marked Latest.
The GitHub token comes from the stored git credential and is never printed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
from build_release import BuildError, check_latest_yml, release_names, sha256  # noqa: E402

API = "https://api.github.com"


def build_info(release_dir: Path) -> dict:
    lines = (release_dir / "BUILD_INFO.txt").read_text(encoding="utf-8").splitlines()
    info = {"version": lines[0].split()[2]}
    for line in lines:
        if line.startswith("Channel: "):
            info["channel"] = line.split(": ", 1)[1]
        elif line.startswith("Source: "):
            info["source"] = line.split(": ", 1)[1]
    return info


def assets(release_dir: Path, version: str) -> list[Path]:
    names = release_names(version, "public")
    files = [names["setup"], names["setup"] + ".blockmap", names["portable"], "latest.yml", "SHA256SUMS.txt",
             "BUILD_INFO.txt", "THIRD_PARTY_NOTICES.txt"]
    missing = [n for n in files if not (release_dir / n).is_file()]
    if missing:
        raise BuildError(f"Release folder is missing {missing}")
    return [release_dir / n for n in files]


def check_folder(release_dir: Path, head: str) -> dict:
    info = build_info(release_dir)
    if info.get("channel") != "public":
        raise BuildError("Only a public-channel build can be published (build_release.py --channel public).")
    if info.get("source") != head:
        raise BuildError(f"The build's source ({info.get('source')}) is not the checked-out commit {head}.")
    names = release_names(info["version"], "public")
    sums = dict(reversed(line.split("  ", 1)) for line in
                (release_dir / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines() if line.strip())
    for name in (names["setup"], names["portable"]):
        if sums.get(name) != sha256(release_dir / name):
            raise BuildError(f"SHA256SUMS.txt does not match {name}")
    check_latest_yml(release_dir / "latest.yml", release_dir / names["setup"], info["version"])
    return info


def body(version: str, commit: str, repo: str) -> str:
    names = release_names(version, "public")
    tag = f"v{version}"
    return "\n".join([
        "## Tải về",
        "",
        f"- **Setup — khuyên dùng:** `{names['setup']}` — cài cho tài khoản hiện tại (không cần quyền quản trị), "
        "có lối tắt Start Menu, tự cập nhật từ GitHub Releases.",
        f"- **Portable — không cần cài:** `{names['portable']}` — giải nén rồi chạy `VietDoc OCR\\VietDoc OCR.exe`; "
        "không tự cập nhật.",
        "",
        "Nhận dạng chữ tiếng Việt trong PDF, PNG, JPG; đọc 22 trường thông tin văn bản hành chính; xuất TXT, JSON, Excel. "
        "Model OCR có sẵn trong gói và tài liệu được xử lý ngay trên máy. Windows 10 (1903 trở lên) hoặc Windows 11, 64-bit.",
        "",
        "Bản build chưa được ký số, nên Windows SmartScreen có thể cảnh báo (\"More info\" → \"Run anyway\" sau khi "
        "SHA-256 khớp). Kiểm tra file tải về bằng `SHA256SUMS.txt`.",
        "",
        f"Hướng dẫn: [HUONG_DAN_CAI_DAT.md](https://github.com/{repo}/blob/{tag}/release/windows/HUONG_DAN_CAI_DAT.md) · "
        "Thông báo giấy phép bên thứ ba: `THIRD_PARTY_NOTICES.txt` · Thông tin bản build: `BUILD_INFO.txt`",
        "",
        f"**Mã nguồn:** commit [`{commit[:7]}`](https://github.com/{repo}/commit/{commit}) · "
        f"**Full Changelog**: https://github.com/{repo}/commits/{tag}",
        "",
    ])


class GitHub:
    def __init__(self, repo: str):
        self.repo = repo
        filled = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                                capture_output=True, text=True, check=True).stdout
        self._token = dict(line.split("=", 1) for line in filled.splitlines() if "=" in line).get("password", "")
        if not self._token:
            raise BuildError("No stored GitHub credential for github.com")

    def call(self, method: str, url: str, payload=None, data=None, headers=None, timeout=120):
        request = urllib.request.Request(url, method=method, data=data if data is not None else
                                         (json.dumps(payload).encode() if payload is not None else None),
                                         headers={"Authorization": f"Bearer {self._token}",
                                                  "Accept": "application/vnd.github+json",
                                                  "X-GitHub-Api-Version": "2022-11-28",
                                                  "User-Agent": "vietdoc-release-publisher", **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"null")

    def upload(self, release: dict, path: Path) -> dict:
        url = release["upload_url"].split("{", 1)[0] + "?name=" + urllib.request.quote(path.name)
        with path.open("rb") as stream:
            status, asset = self.call("POST", url, data=stream, timeout=7200,
                                      headers={"Content-Type": "application/octet-stream",
                                               "Content-Length": str(path.stat().st_size)})
        if status != 201:
            raise BuildError(f"Upload of {path.name} failed: HTTP {status} {asset}")
        return asset


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], check=True, capture_output=True, text=True).stdout.strip()


def ensure_tag(tag: str, commit: str, version: str) -> str:
    remote = [line.split("\t") for line in git("ls-remote", "--tags", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}").splitlines()]
    pointed = {ref: sha for sha, ref in remote}
    target = pointed.get(f"refs/tags/{tag}^{{}}") or pointed.get(f"refs/tags/{tag}")
    if target and target != commit:
        raise BuildError(f"Tag {tag} already exists on GitHub at {target}, not at {commit}.")
    if not target:
        if subprocess.run(["git", "-C", str(REPO), "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
                          capture_output=True).returncode != 0:
            git("tag", "-a", tag, commit, "-m", f"VietDoc OCR {tag}")
        elif git("rev-parse", f"{tag}^{{commit}}") != commit:
            raise BuildError(f"Local tag {tag} points elsewhere.")
        git("push", "origin", f"refs/tags/{tag}")
    return git("rev-parse", tag)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--repo", default="lahieuphong/OCR")
    parser.add_argument("--publish", action="store_true", help="publish the checked draft and mark it Latest")
    args = parser.parse_args()
    try:
        head = git("rev-parse", "HEAD")
        info = check_folder(args.release_dir, head)
        version, tag = info["version"], f"v{info['version']}"
        files = assets(args.release_dir, version)
        hub = GitHub(args.repo)
        status, existing = hub.call("GET", f"{API}/repos/{args.repo}/releases/tags/{tag}")
        if status == 200:
            raise BuildError(f"A release for {tag} already exists: {existing.get('html_url')}")
        tag_object = ensure_tag(tag, head, version)
        status, release = hub.call("POST", f"{API}/repos/{args.repo}/releases",
                                   {"tag_name": tag, "name": f"VietDoc OCR {tag}", "body": body(version, head, args.repo),
                                    "draft": True, "prerelease": False})
        if status != 201:
            raise BuildError(f"Could not create the draft release: HTTP {status} {release}")
        uploaded = {}
        for path in files:
            asset = hub.upload(release, path)
            local = "sha256:" + sha256(path)
            if asset.get("digest") and asset["digest"] != local:
                raise BuildError(f"GitHub's digest of {path.name} differs from the local file")
            uploaded[path.name] = {"bytes": asset["size"], "digest": asset.get("digest") or local}
            print("uploaded", path.name, asset["size"], flush=True)
        result = {"tag": tag, "tag_object": tag_object, "commit": head, "release_id": release["id"],
                  "draft_url": release["html_url"], "assets": uploaded, "published": False}
        if args.publish:
            status, done = hub.call("PATCH", f"{API}/repos/{args.repo}/releases/{release['id']}",
                                    {"draft": False, "make_latest": "true"})
            if status != 200 or done.get("draft"):
                raise BuildError(f"Publishing failed: HTTP {status}")
            result.update(published=True, url=done["html_url"])
    except BuildError as error:
        print(f"PUBLISH STOPPED: {error}", file=sys.stderr)
        return 1
    (args.release_dir.parent / "reports").mkdir(exist_ok=True)
    (args.release_dir.parent / "reports" / "publish.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
