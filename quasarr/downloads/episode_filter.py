# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""Opt-in season-pack episode filter (source-agnostic, JDownloader-level).

When Sonarr grabs a season pack although only some episodes are missing,
Quasarr remembers the missing episode numbers at grab time (keyed by package
id). Once the decrypted links sit fully collected in JDownloader's
linkgrabber — the earliest moment their filenames are known — links belonging
to episodes already on disk are removed, so only the still-missing episodes
are downloaded. Works for any source because it acts after decryption.

Safety first: whenever the links cannot be mapped to episodes unambiguously
(missing episode markers, season mismatch, nothing would remain), the full
pack is kept — the filter must never download less than Sonarr can import.
"""

import json
import re

from quasarr.providers.log import debug, info
from quasarr.providers.sonarr_api import wanted_season_episode_numbers

DB_TABLE = "episode_filter"

# Season/episode token in release titles and archive filenames, e.g.
# "Pack.S01.German..." (no episode part) or "pack.s01e05.german...part03.rar".
# Ranges like "S01E01-E03" are captured whole and expanded by the parser.
_SEASON_TOKEN = re.compile(
    r"(?<![a-z0-9])S(?P<season>\d{1,4})(?P<episodes>(?:E\d{1,4})+(?:-E?\d{1,4})?)?(?![a-z0-9])",
    re.IGNORECASE,
)


def parse_season_episodes(name):
    """Parse the first season/episode token from a title or filename.

    Returns ``(season, episode_numbers)`` where ``episode_numbers`` is a set
    (empty for a season pack without episode component), or ``None`` when the
    name carries no season token at all.
    """
    match = _SEASON_TOKEN.search(name or "")
    if not match:
        return None
    season = int(match.group("season"))
    episode_part = match.group("episodes") or ""
    numbers = [int(n) for n in re.findall(r"\d{1,4}", episode_part)]
    if not numbers:
        return season, set()
    if (
        "-" in episode_part
        and len(numbers) == 2
        and numbers[0] < numbers[1]
        and numbers[1] - numbers[0] <= 100
    ):
        return season, set(range(numbers[0], numbers[1] + 1))
    return season, set(numbers)


def episode_filter_enabled(shared_state):
    """True when the user opted into per-episode season-pack grabbing (Sonarr)."""
    value = shared_state.values["config"]("Sonarr").get("season_pack_episode_filter")
    return str(value).strip().lower() in ("true", "1", "yes", "on")


def maybe_store_episode_filter(shared_state, package_id, title, imdb_id):
    """Remember the missing episodes for a just-grabbed season pack.

    Called after a grab was accepted. Stores a ``{season, episodes}`` entry
    keyed by package id when the filter is enabled, the title is
    season-pack-shaped (season token without episode component), and Sonarr
    reports a non-empty set of missing episodes. In every other case nothing
    is stored and the pack downloads unfiltered — including the "nothing
    missing" case, which practically only occurs on deliberate forced/manual
    grabs.
    """
    try:
        if not episode_filter_enabled(shared_state):
            return
        parsed = parse_season_episodes(title)
        if not parsed or parsed[1]:
            return  # not a season pack (no season token or has episode part)
        season = parsed[0]
        if not imdb_id:
            debug(
                f"Season-pack episode filter: no IMDb id for '{title}', "
                "keeping the full pack"
            )
            return
        wanted = wanted_season_episode_numbers(shared_state, imdb_id, season)
        if wanted is None:
            info(
                "Season-pack episode filter: Sonarr could not determine missing "
                f"episodes for '{title}' (see debug log), keeping the full pack"
            )
            return
        if not wanted:
            info(
                f"Season-pack episode filter: no episode of '{title}' is "
                "missing — deliberate grab, keeping the full pack"
            )
            return
        shared_state.get_db(DB_TABLE).update_store(
            package_id,
            json.dumps({"season": season, "episodes": sorted(wanted)}),
        )
        info(
            f"Season-pack episode filter: will keep only episode(s) "
            f"{sorted(wanted)} of S{season:02d} for '{title}'"
        )
    except Exception as e:
        debug(f"Season-pack episode filter: store failed for '{title}': {e}")


def plan_link_removals(entry, links):
    """Split linkgrabber links into (keep_ids, remove_ids), or None to keep all.

    ``entry`` is the stored ``{season, episodes}`` dict; ``links`` are
    linkgrabber link dicts carrying ``uuid`` and ``name``. Returns ``None`` —
    keep the full pack — whenever any link cannot be mapped to an episode of
    the stored season (missing uuid, no/ambiguous episode marker, season
    mismatch), or when filtering would remove nothing or keep nothing.
    """
    try:
        season = int(entry["season"])
        wanted = {int(n) for n in entry["episodes"]}
    except (KeyError, TypeError, ValueError):
        return None
    if not wanted:
        return None

    keep, remove = [], []
    for link in links:
        uuid = link.get("uuid")
        if uuid is None:
            return None
        parsed = parse_season_episodes(link.get("name") or "")
        if not parsed or not parsed[1] or parsed[0] != season:
            return None  # unmapped link -> never risk an incomplete download
        if parsed[1] & wanted:
            keep.append(uuid)
        else:
            remove.append(uuid)

    if not keep or not remove:
        return None
    return keep, remove


def apply_episode_filter(shared_state, package_id, package_name, package_links):
    """Apply a stored episode filter to a fully collected linkgrabber package.

    Returns True when links were removed in this pass — the caller should
    postpone auto-starting the package until the next poll so JDownloader's
    state has settled. The DB entry is consumed either way, so the filter
    runs at most once per package.
    """
    db = shared_state.get_db(DB_TABLE)
    raw = db.retrieve(package_id)
    if not raw:
        return False
    db.delete(package_id)

    try:
        entry = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        debug(f"Season-pack episode filter: bad entry for {package_id}: {e}")
        return False

    plan = plan_link_removals(entry, package_links)
    if plan is None:
        info(
            f"Season-pack episode filter: links of '{package_name}' could not "
            "be safely mapped to episodes, keeping the full pack"
        )
        return False

    keep, remove = plan
    try:
        # package_ids must be empty: passing the package id would remove the
        # whole package, not just the filtered links.
        shared_state.get_device().linkgrabber.remove_links(remove, [])
    except Exception as e:
        info(
            f"Season-pack episode filter: failed to remove {len(remove)} links "
            f"from '{package_name}': {e} — keeping the full pack"
        )
        return False

    info(
        f"Season-pack episode filter: kept {len(keep)} of "
        f"{len(keep) + len(remove)} links of '{package_name}' "
        f"(episodes {entry.get('episodes')})"
    )
    return True


def clear_episode_filter(shared_state, package_id):
    """Drop a stored filter entry (package deleted or failed)."""
    try:
        shared_state.get_db(DB_TABLE).delete(package_id)
    except Exception:
        pass
