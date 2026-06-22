import importlib.util
import pkgutil


def get_hostnames():
    spec = importlib.util.find_spec("quasarr.search.sources")
    if not spec or not spec.submodule_search_locations:
        return []

    hostnames = []
    for _, module_name, _ in pkgutil.iter_modules(spec.submodule_search_locations):
        if module_name == "helpers" or module_name.startswith("_"):
            continue
        hostnames.append(module_name)

    return sorted(hostnames)


def get_login_required_hostnames():
    from quasarr.search.sources import get_sources

    return [
        source.initials for source in get_sources().values() if source.requires_login
    ]


def get_radarr_required_hostnames():
    from quasarr.search.sources import get_sources

    return [
        source.initials
        for source in get_sources().values()
        if source.feed_requires_radarr
    ]


def get_sonarr_required_hostnames():
    from quasarr.search.sources import get_sources

    return [
        source.initials
        for source in get_sources().values()
        if source.feed_requires_sonarr
    ]
