"""python -m unittest discover -s packaging/backend -p "test_*.py" """
import unittest

from importtime_modules import modules


class ImporttimeModules(unittest.TestCase):
    def test_names_are_taken_from_importtime_lines_only(self):
        lines = [
            "import time: self [us] | cumulative | imported package\n",
            "import time:       120 |        120 |   _io\n",
            "import time:      2533 |      40211 | paddlex.inference.models.text_detection\n",
            "import time:        15 |         15 |     encodings.utf_8\n",
            "VIETDOC_READY {\"port\": 1}\n",
            "WARNING something | with | pipes\n",
        ]
        self.assertEqual(modules(lines), {"_io", "paddlex.inference.models.text_detection", "encodings.utf_8"})


if __name__ == "__main__":
    unittest.main()
