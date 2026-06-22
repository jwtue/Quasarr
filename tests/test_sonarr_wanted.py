import unittest
from types import SimpleNamespace

from quasarr.providers import sonarr_api

PAST = "2000-01-01T00:00:00Z"
FUTURE = "2999-01-01T00:00:00Z"


def ep(imdb, season, episode, air):
    return {
        "series": {"imdbId": imdb},
        "seasonNumber": season,
        "episodeNumber": episode,
        "airDateUtc": air,
    }


class FakeClient:
    """Single-page client: records on page 1, empty thereafter."""

    def __init__(self, missing, cutoff):
        self._records = {"missing": missing, "cutoff": cutoff}

    def wanted(self, kind, page=1, page_size=50):
        return {"records": self._records.get(kind, []) if page == 1 else []}


class PagedClient:
    def __init__(self, pages):
        self._pages = pages

    def wanted(self, kind, page=1, page_size=50):
        return {"records": self._pages.get((kind, page), [])}


def shared_state_with(client):
    return SimpleNamespace(values={"sonarr_client": client})


class SonarrWantedTests(unittest.TestCase):
    def test_skips_unaired_and_undated(self):
        missing = [
            ep("tt1", 1, 1, PAST),
            ep("tt2", 1, 2, FUTURE),  # not aired yet -> skip
            ep("tt3", 1, 3, None),  # no air date -> skip
            ep("tt4", 2, 1, PAST),
        ]
        got = sonarr_api.get_wanted_episodes(shared_state_with(FakeClient(missing, [])))
        self.assertEqual(
            got,
            [
                {"imdb_id": "tt1", "season": 1, "episode": 1},
                {"imdb_id": "tt4", "season": 2, "episode": 1},
            ],
        )

    def test_pages_past_unaired(self):
        pages = {
            ("missing", 1): [ep("tt1", 1, 1, FUTURE), ep("tt2", 1, 2, None)],
            ("missing", 2): [ep("tt9", 3, 3, PAST)],
        }
        got = sonarr_api.get_wanted_episodes(
            shared_state_with(PagedClient(pages)), limit=5
        )
        self.assertEqual(got, [{"imdb_id": "tt9", "season": 3, "episode": 3}])

    def test_empty_without_client(self):
        self.assertEqual(sonarr_api.get_wanted_episodes(SimpleNamespace(values={})), [])


if __name__ == "__main__":
    unittest.main()
