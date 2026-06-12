# -*- coding: utf-8 -*-

import unittest

from quasarr.downloads.packages import get_links_status, is_not_downloadable

PACKAGE = {"uuid": 1, "name": "Synthetic.Release.Example"}


def make_link(uuid, url, availability="ONLINE", status="", finished=False):
    return {
        "uuid": uuid,
        "packageUUID": 1,
        "name": f"file-{uuid}.mkv",
        "url": url,
        "availability": availability,
        "status": status,
        "finished": finished,
    }


class IsNotDownloadableTests(unittest.TestCase):
    def test_matches_status_case_insensitively(self):
        self.assertTrue(is_not_downloadable("Not downloadable!"))
        self.assertTrue(is_not_downloadable("NOT DOWNLOADABLE! (Premium needed)"))

    def test_ignores_other_or_missing_status(self):
        self.assertFalse(is_not_downloadable("Extraction OK"))
        self.assertFalse(is_not_downloadable(""))
        self.assertFalse(is_not_downloadable(None))


class GetLinksStatusNotDownloadableTests(unittest.TestCase):
    def test_all_mirrors_not_downloadable_sets_error(self):
        links = [
            make_link(11, "http://mirror-a.invalid/f1", status="Not downloadable!"),
            make_link(12, "http://mirror-a.invalid/f2", status="Not downloadable!"),
        ]

        result = get_links_status(PACKAGE, links)

        self.assertEqual(result["error"], "Links not downloadable for all mirrors")
        self.assertFalse(result["all_finished"])

    def test_not_downloadable_mirror_does_not_count_as_online(self):
        links = [
            make_link(11, "http://mirror-a.invalid/f1", availability="OFFLINE"),
            make_link(21, "http://mirror-b.invalid/f1", status="Not downloadable!"),
        ]

        result = get_links_status(PACKAGE, links)

        self.assertIn("for all mirrors", result["error"])
        self.assertEqual(result["offline_mirror_linkids"], [])

    def test_online_mirror_suppresses_not_downloadable_error(self):
        links = [
            make_link(11, "http://mirror-a.invalid/f1", finished=True),
            make_link(21, "http://mirror-b.invalid/f1", status="Not downloadable!"),
        ]

        result = get_links_status(PACKAGE, links)

        self.assertIsNone(result["error"])
        self.assertFalse(result["all_finished"])

    def test_offline_links_collected_for_cleanup_with_online_mirror(self):
        links = [
            make_link(11, "http://mirror-a.invalid/f1", finished=True),
            make_link(21, "http://mirror-b.invalid/f1", availability="OFFLINE"),
        ]

        result = get_links_status(PACKAGE, links)

        self.assertIsNone(result["error"])
        self.assertEqual(result["offline_mirror_linkids"], [21])


if __name__ == "__main__":
    unittest.main()
