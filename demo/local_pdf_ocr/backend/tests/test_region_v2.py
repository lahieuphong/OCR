"""Synthetic unit tests. No user PDF, checkpoint, or blind-test files."""
import collections
import unittest

from demo.local_pdf_ocr.backend.ocr_layout_v2 import (
    analyze_detection_geometry,
    reorder_document_regions,
)


def row(i, box, text=None):
    x0, y0, x1, y1 = box
    return {
        "line_index": i,
        "polygon": [[x0,y0],[x1,y0],[x1,y1],[x0,y1]],
        "text": text or f"synthetic-token-{i}",
        "hit_decoder_limit": False,
    }


def make_split(kind):
    if kind == "upper":
        boxes = [(588,51,611,83),(218,115,1054,151),(149,149,1055,182),
                 (147,184,386,214),(746,260,981,292),(160,280,270,306),
                 (719,281,967,337)]
        boxes += [(161+i%3,308+28*i,640-(i%4)*30,333+28*i) for i in range(18)]
        boxes += [(741,467,1006,501)]
        return [row(i+1,box) for i,box in enumerate(boxes)],1194,1700
    boxes = [(212,127,1064,166),(157,158,1063,199),(157,192,1063,231),
             (155,356,747,391),(212,400,1059,440)]
    boxes += [(164,454,273,486),(663,459,1043,495),(166,484,451,512),
              (690,493,964,525)]
    boxes += [(166+i%2,510+27*i,550,539+27*i) for i in range(7)]
    boxes += [(749,674,949,710)]
    return [row(i+1,box) for i,box in enumerate(boxes)],1198,1690


class RegionLayoutV2Tests(unittest.TestCase):
    def test_upper_page_two_columns_no_footer_ratio(self):
        lines,w,h=make_split("upper")
        result,info=reorder_document_regions(lines,w,h)
        self.assertTrue(info["modified"],info)
        self.assertEqual(len(lines),len(result))
        self.assertGreaterEqual(info["left_line_count"],15)
        self.assertEqual(info["right_line_count"],3)
        self.assertEqual(
            collections.Counter((x["text"],str(x["polygon"])) for x in lines),
            collections.Counter((x["text"],str(x["polygon"])) for x in result),
        )

    def test_middle_page_two_columns(self):
        lines,w,h=make_split("middle")
        result,info=reorder_document_regions(lines,w,h)
        self.assertTrue(info["modified"],info)
        self.assertEqual(info["right_line_count"],3)
        self.assertEqual([x["line_index"] for x in result],list(range(1,len(result)+1)))
        self.assertFalse(any("layout_region" in x for x in lines))

    def test_no_false_split_when_right_column_missing(self):
        lines,w,h=make_split("upper")
        lines=[x for x in lines if min(p[0] for p in x["polygon"])<690]
        _,info=reorder_document_regions(lines,w,h)
        self.assertFalse(info["modified"])

    def test_potential_merged_header_only_on_first_page(self):
        line=row(1,(180,100,1070,136))
        self.assertEqual(
            analyze_detection_geometry([line],1200,1700,page_number=1)["flags"][0]["reasons"],
            ["possible_merged_two_column_header"],
        )
        self.assertEqual(
            analyze_detection_geometry([line],1200,1700,page_number=2)["flagged_count"],0
        )

    def test_short_region_remains_unchanged(self):
        rows=[row(1,(90,10,200,32)),row(2,(90,40,200,62))]
        result,info=reorder_document_regions(rows,1200,1700)
        self.assertFalse(info["modified"])
        self.assertEqual(rows,result)

    def test_invalid_page_dimensions(self):
        with self.assertRaises(ValueError):
            reorder_document_regions([],0,1700)


if __name__=="__main__":
    unittest.main()
