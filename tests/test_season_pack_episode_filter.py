import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from quasarr.downloads import episode_filter
from quasarr.providers import sonarr_api


class FakeSonarrClient:
    def __init__(self, series=None, library=None, episodes=None):
        self._series = series
        self._library = library
        self._episodes = episodes
        self.episodes_kwargs = None

    def series_lookup_imdb(self, imdb_id):
        return self._series

    def series_by_tvdb(self, tvdb_id):
        return self._library

    def episodes(self, series_id, include_episode_file=False):
        self.episodes_kwargs = {"include_episode_file": include_episode_file}
        return self._episodes


def shared_state_with(client):
    return SimpleNamespace(values={"sonarr_client": client})


class WantedSeasonEpisodeNumbersTests(unittest.TestCase):
    def _client(self, episodes):
        return FakeSonarrClient(
            series={"tvdbId": 999}, library={"id": 42}, episodes=episodes
        )

    def test_returns_missing_of_season_regardless_of_monitored(self):
        episodes = [
            {"seasonNumber": 1, "episodeNumber": 1, "monitored": True, "hasFile": True},
            {
                "seasonNumber": 1,
                "episodeNumber": 2,
                "monitored": True,
                "hasFile": False,
            },
            # Unmonitored but missing still counts: season packs are grabbed
            # interactively for unmonitored series too, and including it can
            # never download more than the unfiltered full pack would.
            {
                "seasonNumber": 1,
                "episodeNumber": 3,
                "monitored": False,
                "hasFile": False,
            },
            {
                "seasonNumber": 2,
                "episodeNumber": 1,
                "monitored": True,
                "hasFile": False,
            },
        ]
        got = sonarr_api.wanted_season_episode_numbers(
            shared_state_with(self._client(episodes)), "tt1", "1"
        )
        # Present-on-disk (E1) and other seasons (S2) are excluded.
        self.assertEqual(got, {2, 3})

    def test_none_without_client_falls_back(self):
        self.assertIsNone(
            sonarr_api.wanted_season_episode_numbers(
                SimpleNamespace(values={}), "tt1", 1
            )
        )

    def test_none_when_series_not_in_library(self):
        client = FakeSonarrClient(series={"tvdbId": 999}, library=None, episodes=[])
        self.assertIsNone(
            sonarr_api.wanted_season_episode_numbers(
                shared_state_with(client), "tt1", 1
            )
        )

    def test_empty_set_when_all_present(self):
        episodes = [
            {"seasonNumber": 1, "episodeNumber": 1, "monitored": True, "hasFile": True},
        ]
        got = sonarr_api.wanted_season_episode_numbers(
            shared_state_with(self._client(episodes)), "tt1", 1
        )
        self.assertEqual(got, set())

    def test_cutoff_unmet_file_counts_as_wanted(self):
        # An on-disk episode below the quality cutoff is an upgrade target and
        # must be grabbed; one at/above cutoff must not. hasFile without an
        # embedded episodeFile (defensive) is not an upgrade target.
        episodes = [
            {
                "seasonNumber": 1,
                "episodeNumber": 1,
                "monitored": True,
                "hasFile": True,
                "episodeFile": {"qualityCutoffNotMet": True},
            },
            {
                "seasonNumber": 1,
                "episodeNumber": 2,
                "monitored": True,
                "hasFile": True,
                "episodeFile": {"qualityCutoffNotMet": False},
            },
            {"seasonNumber": 1, "episodeNumber": 3, "monitored": True, "hasFile": True},
        ]
        client = self._client(episodes)
        got = sonarr_api.wanted_season_episode_numbers(
            shared_state_with(client), "tt1", 1
        )
        self.assertEqual(got, {1})
        # The cutoff decision requires the embedded episodeFile record.
        self.assertEqual(client.episodes_kwargs, {"include_episode_file": True})


class ParseSeasonEpisodesTests(unittest.TestCase):
    def test_parses_titles_and_filenames(self):
        cases = [
            # Season pack titles: season token, no episode part.
            ("Synthetic.Show.S01.German.2160p.WEB.H265-GRP", (1, set())),
            # Single-episode release titles and archive filenames.
            ("Synthetic.Show.S01E05.German.1080p.WEB-GRP", (1, {5})),
            ("synthetic.show.s01e05.german.2160p.web.h265-grp.part03.rar", (1, {5})),
            # Repack markers after the token do not disturb parsing.
            ("synthetic.show.s01e06.german.web.repack-grp.part01.rar", (1, {6})),
            # Episode ranges expand to every contained episode.
            ("Synthetic.Show.S01E01-E03.German.1080p.WEB-GRP", (1, {1, 2, 3})),
            ("Synthetic.Show.S01E01-03.German.1080p.WEB-GRP", (1, {1, 2, 3})),
            # Multi-episode files without a range dash keep both numbers.
            ("Synthetic.Show.S01E01E02.German.1080p.WEB-GRP", (1, {1, 2})),
            # No season token at all.
            ("Synthetic.Movie.2024.German.1080p.BluRay-GRP", None),
            # "part01" must not be mistaken for an episode marker.
            ("synthetic.show.s02.german.web-grp.part11.rar", (2, set())),
        ]
        for name, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(episode_filter.parse_season_episodes(name), expected)


def _link(uuid, name):
    return {"uuid": uuid, "name": name, "packageUUID": 1000}


class PlanLinkRemovalsTests(unittest.TestCase):
    # Multipart archives, one group per episode — the real-world shape this
    # feature exists for. Synthetic names only (never real release titles).
    LINKS = [
        _link(1, "synthetic.show.s01e01.german.web-grp.part01.rar"),
        _link(2, "synthetic.show.s01e01.german.web-grp.part02.rar"),
        _link(3, "synthetic.show.s01e02.german.web-grp.part01.rar"),
        _link(4, "synthetic.show.s01e02.german.web-grp.part02.rar"),
        _link(5, "synthetic.show.s01e03.german.web-grp.part01.rar"),
    ]

    def test_keeps_only_wanted_episode_parts(self):
        plan = episode_filter.plan_link_removals(
            {"season": 1, "episodes": [3]}, self.LINKS
        )
        self.assertEqual(plan, ([5], [1, 2, 3, 4]))

    def test_multiple_wanted_episodes(self):
        plan = episode_filter.plan_link_removals(
            {"season": 1, "episodes": [1, 3]}, self.LINKS
        )
        self.assertEqual(plan, ([1, 2, 5], [3, 4]))

    def test_unparseable_link_keeps_full_pack(self):
        # One link without an episode marker poisons the mapping -> keep all,
        # never risk an incomplete download.
        links = self.LINKS + [_link(6, "synthetic.show.sample.mkv")]
        self.assertIsNone(
            episode_filter.plan_link_removals({"season": 1, "episodes": [3]}, links)
        )

    def test_season_mismatch_keeps_full_pack(self):
        links = self.LINKS + [_link(6, "synthetic.show.s02e01.german.web-grp.rar")]
        self.assertIsNone(
            episode_filter.plan_link_removals({"season": 1, "episodes": [3]}, links)
        )

    def test_nothing_to_remove_or_keep_is_a_noop(self):
        # All episodes wanted -> nothing to remove; none wanted -> nothing to
        # keep. Both mean "do not touch the package".
        self.assertIsNone(
            episode_filter.plan_link_removals(
                {"season": 1, "episodes": [1, 2, 3]}, self.LINKS
            )
        )
        self.assertIsNone(
            episode_filter.plan_link_removals(
                {"season": 1, "episodes": [9]}, self.LINKS
            )
        )

    def test_link_without_uuid_keeps_full_pack(self):
        links = [dict(self.LINKS[0]), dict(self.LINKS[4])]
        links[0].pop("uuid")
        self.assertIsNone(
            episode_filter.plan_link_removals({"season": 1, "episodes": [3]}, links)
        )


class _FakeDb:
    def __init__(self, rows=None):
        self.rows = dict(rows or {})

    def retrieve(self, key):
        return self.rows.get(key)

    def update_store(self, key, value):
        self.rows[key] = value

    def delete(self, key):
        self.rows.pop(key, None)


def _filter_shared_state(db, enabled=True, device=None):
    config_values = {"season_pack_episode_filter": "true" if enabled else "false"}
    return SimpleNamespace(
        values={"config": lambda section: config_values},
        get_db=lambda table: db,
        get_device=lambda: device,
    )


class MaybeStoreEpisodeFilterTests(unittest.TestCase):
    PACK_TITLE = "Synthetic.Show.S01.German.2160p.WEB.H265-GRP"

    def test_stores_wanted_subset_for_season_pack(self):
        db = _FakeDb()
        state = _filter_shared_state(db)
        with patch.object(
            episode_filter, "wanted_season_episode_numbers", return_value={8}
        ):
            episode_filter.maybe_store_episode_filter(
                state, "Quasarr_tv_abc", self.PACK_TITLE, "tt1"
            )
        self.assertEqual(
            json.loads(db.rows["Quasarr_tv_abc"]), {"season": 1, "episodes": [8]}
        )

    def test_no_store_when_disabled_or_not_a_pack_or_no_imdb(self):
        db = _FakeDb()
        with patch.object(
            episode_filter, "wanted_season_episode_numbers", return_value={8}
        ):
            episode_filter.maybe_store_episode_filter(
                _filter_shared_state(db, enabled=False),
                "Quasarr_tv_abc",
                self.PACK_TITLE,
                "tt1",
            )
            episode_filter.maybe_store_episode_filter(
                _filter_shared_state(db),
                "Quasarr_tv_abc",
                "Synthetic.Show.S01E05.German.1080p.WEB-GRP",
                "tt1",
            )
            episode_filter.maybe_store_episode_filter(
                _filter_shared_state(db), "Quasarr_tv_abc", self.PACK_TITLE, None
            )
        self.assertEqual(db.rows, {})

    def test_no_store_when_sonarr_undecidable_or_nothing_missing(self):
        # None -> Sonarr cannot decide; empty -> deliberate (forced/manual)
        # grab. Both must download the full pack, i.e. store nothing.
        for wanted in (None, set()):
            with self.subTest(wanted=wanted):
                db = _FakeDb()
                with patch.object(
                    episode_filter,
                    "wanted_season_episode_numbers",
                    return_value=wanted,
                ):
                    episode_filter.maybe_store_episode_filter(
                        _filter_shared_state(db),
                        "Quasarr_tv_abc",
                        self.PACK_TITLE,
                        "tt1",
                    )
                self.assertEqual(db.rows, {})


class ApplyEpisodeFilterTests(unittest.TestCase):
    LINKS = PlanLinkRemovalsTests.LINKS

    def _entry(self):
        return json.dumps({"season": 1, "episodes": [3]})

    def test_removes_unwanted_links_and_consumes_entry(self):
        db = _FakeDb({"Quasarr_tv_abc": self._entry()})
        device = MagicMock()
        state = _filter_shared_state(db, device=device)
        removed = episode_filter.apply_episode_filter(
            state, "Quasarr_tv_abc", "pack", self.LINKS
        )
        self.assertTrue(removed)
        # package_ids must stay empty; passing the package id would remove the
        # whole package.
        device.linkgrabber.remove_links.assert_called_once_with([1, 2, 3, 4], [])
        self.assertEqual(db.rows, {})

    def test_no_entry_is_a_fast_noop(self):
        device = MagicMock()
        state = _filter_shared_state(_FakeDb(), device=device)
        self.assertFalse(
            episode_filter.apply_episode_filter(
                state, "Quasarr_tv_abc", "pack", self.LINKS
            )
        )
        device.linkgrabber.remove_links.assert_not_called()

    def test_unmappable_links_keep_full_pack_and_consume_entry(self):
        db = _FakeDb({"Quasarr_tv_abc": self._entry()})
        device = MagicMock()
        state = _filter_shared_state(db, device=device)
        links = self.LINKS + [_link(6, "synthetic.show.sample.mkv")]
        self.assertFalse(
            episode_filter.apply_episode_filter(state, "Quasarr_tv_abc", "pack", links)
        )
        device.linkgrabber.remove_links.assert_not_called()
        # Entry is consumed either way so the filter runs at most once.
        self.assertEqual(db.rows, {})

    def test_device_error_keeps_full_pack(self):
        db = _FakeDb({"Quasarr_tv_abc": self._entry()})
        device = MagicMock()
        device.linkgrabber.remove_links.side_effect = RuntimeError("jd gone")
        state = _filter_shared_state(db, device=device)
        self.assertFalse(
            episode_filter.apply_episode_filter(
                state, "Quasarr_tv_abc", "pack", self.LINKS
            )
        )


if __name__ == "__main__":
    unittest.main()
