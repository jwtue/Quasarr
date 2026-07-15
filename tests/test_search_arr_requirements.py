import unittest
from types import SimpleNamespace
from unittest.mock import patch

from quasarr.constants import SEARCH_CAT_BOOKS, SEARCH_CAT_MOVIES, SEARCH_CAT_SHOWS
from quasarr.search import get_search_results
from quasarr.storage.setup.radarr import _radarr_setup_form_html, is_radarr_skipped
from quasarr.storage.setup.sonarr import _sonarr_setup_form_html, is_sonarr_skipped


class SearchArrRequirementTests(unittest.TestCase):
    @staticmethod
    def _state(**clients):
        return SimpleNamespace(
            values={
                "config": lambda _section: {},
                **clients,
            }
        )

    def test_movie_search_stops_without_radarr(self):
        with patch("quasarr.search.error") as log_error:
            results = get_search_results(
                self._state(),
                "radarr",
                SEARCH_CAT_MOVIES,
                imdb_id="tt0000010",
            )

        self.assertEqual([], results)
        log_error.assert_called_once_with(
            "Movie search unavailable: Radarr is not configured"
        )

    def test_tv_feed_stops_without_sonarr(self):
        with patch("quasarr.search.error") as log_error:
            results = get_search_results(self._state(), "sonarr", SEARCH_CAT_SHOWS)

        self.assertEqual([], results)
        log_error.assert_called_once_with(
            "TV search unavailable: Sonarr is not configured"
        )

    def test_book_phrase_search_does_not_require_arr_client(self):
        with (
            patch("quasarr.search.get_sources", return_value={}),
            patch("quasarr.search.get_search_category_sources", return_value=[]),
            patch("quasarr.search.error") as log_error,
        ):
            results = get_search_results(
                self._state(),
                "magazarr",
                SEARCH_CAT_BOOKS,
                search_phrase="Synthetic Author",
            )

        self.assertEqual([], results)
        log_error.assert_not_called()

    def test_movie_search_warms_metadata_from_radarr(self):
        state = self._state(radarr_client=object())
        with (
            patch("quasarr.search.get_sources", return_value={}),
            patch("quasarr.search.get_search_category_sources", return_value=[]),
            patch("quasarr.search.get_imdb_metadata") as metadata_lookup,
        ):
            get_search_results(
                state,
                "radarr",
                SEARCH_CAT_MOVIES,
                imdb_id="tt0000011",
            )

        metadata_lookup.assert_called_once_with(state, "tt0000011", SEARCH_CAT_MOVIES)

    def test_setup_forms_do_not_offer_arr_skip_loopholes(self):
        with (
            patch("quasarr.storage.setup.radarr.Config", return_value={}),
            patch("quasarr.storage.setup.sonarr.Config", return_value={}),
        ):
            radarr_html = _radarr_setup_form_html(["aa"])
            sonarr_html = _sonarr_setup_form_html(["bb"])

        self.assertNotIn("skip", radarr_html.lower())
        self.assertNotIn("skip", sonarr_html.lower())
        self.assertEqual(2, radarr_html.count(" required"))
        self.assertEqual(2, sonarr_html.count(" required"))
        self.assertFalse(is_radarr_skipped())
        self.assertFalse(is_sonarr_skipped())


if __name__ == "__main__":
    unittest.main()
