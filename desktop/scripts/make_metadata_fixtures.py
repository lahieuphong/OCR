"""Render synthetic fixture JSON to PDFs outside Git; never reads research documents or labels.

First run frontend/scripts/export_metadata_fixtures.mjs <outside-repo-folder>.
Then: python desktop/scripts/make_metadata_fixtures.py <folder> [--font <local-ttf>]
The local font is used only in synthetic QA PDFs, never copied into the app.
"""
import argparse
import json
from pathlib import Path

import pymupdf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--font", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    folder = args.folder.resolve()
    if folder.is_relative_to(root):
        parser.error("Synthetic PDFs must be written outside the repository")
    fonts = [args.font] if args.font else [Path("C:/Windows/Fonts/segoeui.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    font = next((p for p in fonts if p and p.is_file()), None)
    if not font:
        parser.error("Specify an installed Unicode TTF with --font; no font is downloaded")
    for source in sorted(folder.glob("*.source.json")):
        data = json.loads(source.read_text(encoding="utf-8"))
        document = pymupdf.open()
        for item in data["pages"]:
            page = document.new_page(width=595, height=842)
            page.insert_font(fontname="synthetic", fontfile=str(font))
            for line in item["lines"]:
                if "bbox" in line:
                    x, y = line["bbox"][:2]
                else:
                    x, y = line["polygon"][0]
                    x, y = x * 595 / item["width"], y * 842 / item["height"]
                page.insert_text((x, y + 10), line["text"], fontsize=9, fontname="synthetic")
        output = folder / (source.name.removesuffix(".source.json") + ".pdf")
        document.save(output)
        document.close()
        print(output.name)


if __name__ == "__main__":
    main()
