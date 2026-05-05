# -*- coding: utf-8 -*-

import unittest

from quasarr.providers.utils import normalize_optional_int


class ReleaseMatchingUtilsTests(unittest.TestCase):
    def test_normalize_optional_int_returns_none_for_empty_string(self):
        self.assertIsNone(normalize_optional_int(""))

    def test_normalize_optional_int_parses_numbers(self):
        self.assertEqual(4, normalize_optional_int("4"))


if __name__ == "__main__":
    unittest.main()
