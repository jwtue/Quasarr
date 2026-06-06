import unittest
from unittest.mock import patch

from quasarr.downloads.sources.wx import Source


class SharedState:
    def __init__(self):
        self.values = {"user_agent": "UA/1.0", "config": self.config}

    def config(self, section):
        if section == "Hostnames":
            return {"wx": "source.invalid"}
        return {}


class FakeResponse:
    def __init__(self, json_data=None, status_code=200):
        self._json = json_data or {}
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


def _api_payload(releases):
    return {"item": {"releases": releases}}


def _release(fulltitle, links, crypted, check=None):
    return {
        "fulltitle": fulltitle,
        "links": links,
        "crypted_links": crypted,
        "options": {"check": check or {}},
    }


class WxDirectLinksTests(unittest.TestCase):
    URL = "https://www.source.invalid/detail/ABC123/Some-Movie"
    TITLE = "Some.Movie.2024.German.1080p.WEB.H264-GRP"

    def _run(self, releases, online_badge_urls=None, mirrors=None):
        """
        online_badge_urls: set of badge URLs that should be considered green/online.
        When None, no badge checking is performed (all hosters without a badge URL
        are treated as online — mirrors the check_links_online_status contract).
        """

        def fake_session_get(url, **kwargs):
            if "/start/d/" in url:
                return FakeResponse(_api_payload(releases))
            return FakeResponse({})  # initial page load

        def fake_check_links(links_with_status, shared_state=None):
            """
            Simulate check_links_online_status using badge URL presence as the
            online/offline signal.  Mirrors that have no badge URL (status_url
            is None) are always included — matching the real implementation's
            conservative contract.
            """
            if online_badge_urls is None:
                # No badge differentiation requested: return all as online.
                return [[lnk[0], lnk[1]] for lnk in links_with_status]

            result = []
            for lnk in links_with_status:
                url, hoster, badge_url = lnk
                if badge_url is None or badge_url in online_badge_urls:
                    result.append([url, hoster])
            return result

        with (
            patch("quasarr.downloads.sources.wx.requests.Session") as session_cls,
            patch(
                "quasarr.downloads.sources.wx.check_links_online_status",
                side_effect=fake_check_links,
            ),
        ):
            session = session_cls.return_value
            session.get.side_effect = fake_session_get
            return Source().get_download_links(
                SharedState(), self.URL, mirrors or [], self.TITLE, ""
            )

    def test_prefers_direct_links_over_filecrypt(self):
        releases = [
            _release(
                self.TITLE,
                {
                    "ddownload.com": [
                        "https://ddownload.com/a",
                        "https://ddownload.com/b",
                    ],
                    "rapidgator.net": ["https://rapidgator.net/file/c"],
                },
                {
                    "ddownload.com": "https://filecrypt.cc/Container/AAA.html",
                    "rapidgator.net": "https://filecrypt.cc/Container/BBB.html",
                },
            )
        ]
        result = self._run(releases)
        urls = [link[0] for link in result["links"]]
        # All direct hoster links returned; no filecrypt container leaks through.
        self.assertEqual(
            sorted(urls),
            sorted(
                [
                    "https://ddownload.com/a",
                    "https://ddownload.com/b",
                    "https://rapidgator.net/file/c",
                ]
            ),
        )
        self.assertFalse(any("filecrypt" in u for u in urls))

    def test_filecrypt_only_release_still_yields_direct_links(self):
        # No hide.cx mirror anywhere; crypted is filecrypt-only. Direct links
        # must still be used instead of failing into the CAPTCHA path.
        releases = [
            _release(
                self.TITLE,
                {"rapidgator.net": ["https://rapidgator.net/file/x"]},
                {"rapidgator.net": "https://filecrypt.cc/Container/ZZZ.html"},
            )
        ]
        result = self._run(releases)
        self.assertEqual(
            [link[0] for link in result["links"]],
            ["https://rapidgator.net/file/x"],
        )

    def test_offline_hoster_is_dropped_but_online_kept(self):
        """
        When options.check provides badge URLs, check_links_online_status
        determines per-hoster status via the badge image colour.  Only the
        hoster whose badge is green (in online_badge_urls) should survive.
        """
        releases = [
            _release(
                self.TITLE,
                {
                    "ddownload.com": ["https://ddownload.com/live"],
                    "nitroflare.com": ["https://nitroflare.com/dead"],
                },
                {},
                check={
                    "ddownload.com": "https://filecrypt.cc/Stat/GREEN.png",
                    "nitroflare.com": "https://filecrypt.cc/Stat/RED.png",
                },
            )
        ]
        # Only the ddownload badge is green.
        result = self._run(
            releases,
            online_badge_urls={"https://filecrypt.cc/Stat/GREEN.png"},
        )
        urls = [link[0] for link in result["links"]]
        self.assertIn("https://ddownload.com/live", urls)
        self.assertNotIn("https://nitroflare.com/dead", urls)

    def test_best_mirror_with_most_online_hosters_wins(self):
        """
        M1 has 1 hoster, M2 has 2 hosters — M2 should be selected.
        Without badge URLs (options.check empty), all hosters are treated as
        online; hoster count alone decides the winner.
        """
        releases = [
            _release(
                self.TITLE,
                {"ddownload.com": ["https://ddownload.com/m1"]},
                {},
            ),
            _release(
                self.TITLE,
                {
                    "ddownload.com": ["https://ddownload.com/m2"],
                    "rapidgator.net": ["https://rapidgator.net/file/m2"],
                },
                {},
            ),
        ]
        result = self._run(releases)
        urls = [link[0] for link in result["links"]]
        self.assertEqual(
            sorted(urls),
            ["https://ddownload.com/m2", "https://rapidgator.net/file/m2"],
        )

    def test_stale_mirror_loses_to_live_mirror_via_badge(self):
        """
        Regression test for the DeLo report: M1 has 3 hosters all returning
        HTTP 200 (stale/deleted files on premium hosters), M2 has 2 hosters
        that are genuinely online.  The old HEAD-probe approach counted M1 as
        3-online and chose it; the badge approach reads the filecrypt status
        image and correctly drops M1's offline hosters.
        """
        # M1: 3 hosters, all badges are red (stale).
        # M2: 2 hosters, all badges are green (live).
        m1 = _release(
            self.TITLE,
            {
                "rapidgator.net": [
                    "https://rapidgator.net/file/m1a",
                    "https://rapidgator.net/file/m1b",
                ],
                "ddownload.com": [
                    "https://ddownload.com/m1a",
                    "https://ddownload.com/m1b",
                ],
                "turbobit.net": [
                    "https://turbobit.net/m1a.html",
                    "https://turbobit.net/m1b.html",
                ],
            },
            {},
            check={
                "rapidgator.net": "https://filecrypt.cc/Stat/M1RG.png",
                "ddownload.com": "https://filecrypt.cc/Stat/M1DD.png",
                "turbobit.net": "https://filecrypt.cc/Stat/M1TB.png",
            },
        )
        m2 = _release(
            self.TITLE,
            {
                "ddownload.com": [
                    "https://ddownload.com/m2a",
                    "https://ddownload.com/m2b",
                    "https://ddownload.com/m2c",
                ],
                "rapidgator.net": [
                    "https://rapidgator.net/file/m2a",
                    "https://rapidgator.net/file/m2b",
                    "https://rapidgator.net/file/m2c",
                ],
            },
            {},
            check={
                "ddownload.com": "https://filecrypt.cc/Stat/M2DD.png",
                "rapidgator.net": "https://filecrypt.cc/Stat/M2RG.png",
            },
        )
        # Only M2's badges are online.
        result = self._run(
            [m1, m2],
            online_badge_urls={
                "https://filecrypt.cc/Stat/M2DD.png",
                "https://filecrypt.cc/Stat/M2RG.png",
            },
        )
        urls = [link[0] for link in result["links"]]
        # All M2 links present.
        self.assertIn("https://ddownload.com/m2a", urls)
        self.assertIn("https://rapidgator.net/file/m2a", urls)
        # No M1 links.
        self.assertFalse(any("/m1" in u for u in urls))

    def test_falls_back_to_crypted_when_no_direct_links(self):
        # Empty 'links' field → must fall back to the filecrypt container.
        releases = [
            _release(
                self.TITLE,
                {},
                {"ddownload.com": "https://filecrypt.cc/Container/CCC.html"},
            )
        ]
        result = self._run(releases)
        urls = [link[0] for link in result["links"]]
        self.assertEqual(urls, ["https://filecrypt.cc/Container/CCC.html"])


if __name__ == "__main__":
    unittest.main()
