# WX

Per-source notes for the `WX` integration. For conventions, see `docs/sources/README.md`; for third-party payload rules, see the `Third-Party Source Work` section of `AGENTS.md`.

## Search

- Module: `quasarr/search/sources/wx.py`
- Categories: Movies, Shows, Anime Shows
- Style: RSS/Atom hybrid feed; JSON API for search
- Capabilities: `supports_imdb=True`, `supports_phrase=False`, `requires_login=False`
- Session: plain `requests`

## Download

- Module: `quasarr/downloads/sources/wx.py`
- Inherits: `AbstractDownloadSource`
- Link protection: none — direct links; detail and release endpoints are queried for full metadata

## Notable quirks

- The feed parser detects whether the payload is RSS or Atom and adapts; the default password is derived from the configured hostname in upper case.
- Search filters API results by an internal type token (movie / series / anime) to match the requested category.
- Releases are deduplicated by full title; mirrors come from the per-release block.
- IMDb mismatches between the query and the release are dropped; the release's own IMDb identifier is preferred when the query did not supply one.

## Mirror selection

Each mirror exposes direct hoster URLs (`links`), crypted containers
(`crypted_links`, filecrypt or hide) and per-hoster status badges
(`options.check`). The badge certifies the container, not the separately
uploaded direct links, so containers rank above direct links:

1. green hide.cx container (resolved downstream by `hide.py`, no CAPTCHA)
2. green filecrypt container (handed to JDownloader, may need a CAPTCHA)
3. green direct links (best effort; the badge does not measure them)
4. first offline-flagged mirror as a last resort

The `links` set and the container are separate uploads, so a green badge does not
prove the direct link is online; preferring the certified container avoids the
dead-direct-link case at the cost of a CAPTCHA on filecrypt mirrors. Quasarr never
probes direct-link liveness (JDownloader's job). See
[Mirror Selection](../Mirror-Selection.md) for the rationale.

### filecrypt to hide.cx twin (user_id)

For uploads from the WX user ids in `HIDE_CX_MIRROR_USER_IDS`, the same container
is also published on hide.cx under the same id. Their `filecrypt.cc` containers
are rewritten to the `hide.cx/fc` twin so they auto-resolve via `hide.py` without
a CAPTCHA (tier 1) instead of going to the filecrypt/SponsorsHelper path. This is
not a guess: it mirrors the WX frontend exactly, which gates the identical
`filecrypt.cc -> hide.cx/fc` rewrite on `[4].includes(mirror.user)` (the release
`user_id`). Uploads from other ids are left as filecrypt. If hide.cx happens not
to have a given container, `hide.py` returns nothing and the normal
auto-decrypt to SponsorsHelper fallback applies.
