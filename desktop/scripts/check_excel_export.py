"""Read the actual app download independently of ExcelJS (stdlib OOXML reader).

No Office, Python or this QA script is needed by the application to export XLSX.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
HEADERS = ["STT", "Mã tài liệu", "Mã văn bản", "Thời hạn lưu trữ", "Loại tài liệu",
           "Số tài liệu", "Ký hiệu văn bản", "Ngày ban hành", "Cơ quan ban hành",
           "Trích yếu nội dung", "Ngôn ngữ", "Số trang", "Ký hiệu thông tin", "Từ khóa",
           "Chế độ sử dụng", "Mức độ tin cậy", "Bút tích", "Tình trạng vật lý",
           "Quy trình xử lý", "Chế độ dự phòng", "Tình trạng dự phòng", "Ghi chú", "Màu con dấu"]
KEYS = ["docId", "arcDocCode", "maintenance", "typeName", "codeNumber", "codeNotation",
        "issuedDate", "organName", "subject", "language", "numberOfPage", "inforSign", "keyword",
        "mode", "confidenceLevel", "autograph", "format", "process", "riskRecovery",
        "riskRecoveryStatus", "description", "isCan"]


def verify(file: Path, count: int, expected_file: Path | None = None) -> dict:
    with ZipFile(file) as archive:
        assert archive.testzip() is None, "Invalid ZIP CRC"
        assert not any("externalLinks" in name or "vbaProject" in name for name in archive.namelist())
        xml = lambda name: ET.fromstring(archive.read(name))
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(node.itertext()) for node in xml("xl/sharedStrings.xml")]
        styles = xml("xl/styles.xml")
        fonts = list(styles.find("s:fonts", NS))
        fills = list(styles.find("s:fills", NS))
        borders = list(styles.find("s:borders", NS))
        formats = list(styles.find("s:cellXfs", NS))
        rels = {node.get("Id"): node.get("Target") for node in xml("xl/_rels/workbook.xml.rels")}
        sheets = xml("xl/workbook.xml").find("s:sheets", NS)
        assert [sheet.get("name") for sheet in sheets] == ["Danh sách văn bản", "Nguồn tài liệu"]

        def read_sheet(sheet, columns):
            target = rels[sheet.get(REL)]
            root = xml(target.lstrip("/") if target.startswith("/") else "xl/" + target)
            assert root.find("s:mergeCells", NS) is None, "Merged data cells"
            assert root.find(".//s:f", NS) is None, "Executable formula found"
            assert root.find("s:hyperlinks", NS) is None, "Unexpected hyperlink"
            pane = root.find("s:sheetViews/s:sheetView/s:pane", NS)
            assert pane is not None and pane.get("state") == "frozen"
            assert pane.get("xSplit") == "1" and pane.get("ySplit") == "1" and pane.get("topLeftCell") == "B2"
            last = "W" if columns == 23 else "D"
            assert root.find("s:autoFilter", NS).get("ref") == f"A1:{last}{count+1}"
            col_specs = root.findall("s:cols/s:col", NS)
            assert col_specs and all(5 <= float(col.get("width")) <= 70 for col in col_specs)
            rows = root.findall("s:sheetData/s:row", NS)
            assert len(rows) == count + 1
            result = []
            for index, row in enumerate(rows, 1):
                assert int(row.get("r")) == index
                assert 26 <= float(row.get("ht")) <= 120
                cells = row.findall("s:c", NS)
                assert len(cells) == columns, "Blank cells must also be styled"
                values = []
                for col, cell in enumerate(cells, 1):
                    assert cell.get("r") == f"{chr(64+col)}{index}", "Unexpected cell order"
                    fmt = formats[int(cell.get("s", "0"))]
                    font = fonts[int(fmt.get("fontId"))]
                    assert font.find("s:name", NS).get("val") == "Times New Roman"
                    assert float(font.find("s:sz", NS).get("val")) == 13
                    assert (font.find("s:b", NS) is not None) == (index == 1)
                    fill = fills[int(fmt.get("fillId"))].find("s:patternFill/s:fgColor", NS)
                    assert fill.get("rgb") == ("FFDBEAFE" if index == 1 else "FFFFFFFF")
                    border = borders[int(fmt.get("borderId"))]
                    for side in ["left", "right", "top", "bottom"]:
                        edge = border.find("s:" + side, NS)
                        assert edge.get("style") == "thin"
                        assert edge.find("s:color", NS).get("rgb") == "FFCBD5E1"
                    align = fmt.find("s:alignment", NS)
                    assert align.get("wrapText") == "1"
                    assert align.get("horizontal") == ("center" if index == 1 or col == 1 else "left")
                    value_node = cell.find("s:v", NS)
                    value = "" if value_node is None else value_node.text or ""
                    if cell.get("t") == "s":
                        value = strings[int(value)]
                    elif cell.get("t") == "inlineStr":
                        value = "".join(cell.find("s:is", NS).itertext())
                    elif value:
                        assert col == 1 and index > 1 and int(value) == index-1, "Only STT may be numeric"
                        value = int(value)
                    assert fmt.get("numFmtId") == ("1" if col == 1 and index > 1 else "49")
                    values.append(value)
                result.append(values)
            return result

        main = read_sheet(sheets[0], 23)
        sources = read_sheet(sheets[1], 4)
        assert main[0] == HEADERS, "Wrong header order"
        for index, row in enumerate(main[1:], 1):
            assert row[0] == index and row[1] == "", "STT/docId mismatch"
            assert not row[7] or re.fullmatch(r"\d{2}-\d{2}-\d{4}", row[7]), "Date changed"
        for row in sources[1:]:
            assert "/" not in row[1] and "\\" not in row[1] and ":" not in row[1], "Absolute path leaked"
            # Processing provenance is separate from the metadata access-classification field "mode".
            assert row[2] in ("native_text", "vietocr_ocr", "hybrid_h1")
        if expected_file:
            expected = json.loads(expected_file.read_text(encoding="utf-8"))
            assert len(expected) == count
            for index, (actual, wanted) in enumerate(zip(main[1:], expected), 1):
                assert list(wanted) == KEYS
                assert actual == [index] + [wanted[key] for key in KEYS], f"UI/XLSX mismatch on row {index}"
    return {"status": "PASS", "reader": "Python stdlib ZIP/XML (independent of ExcelJS)",
            "rows": count, "columns": 23, "font": "Times New Roman", "size": 13,
            "ui_values_equal": expected_file is not None, "all_cells_styled": True,
            "freeze": "B2", "autofilter": f"A1:W{count+1}", "formulas": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--rows", type=int, default=3)
    parser.add_argument("--expected-json", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.workbook, args.rows, args.expected_json), ensure_ascii=False))
