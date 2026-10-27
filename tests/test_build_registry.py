"""build_registry.py: app discovery and its failure modes, with GitHub faked."""
import urllib.error

import pytest

import build_registry as br


def _repo(name, topics):
    return {
        "full_name": f"CrossPad/{name}",
        "clone_url": f"https://github.com/CrossPad/{name}.git",
        "default_branch": "main",
        "stargazers_count": 0,
        "topics": topics,
    }


def _fake_get(pages, errors=None):
    """_api_get stand-in: org repo pages by number, HTTP errors by URL substring."""
    errors = errors or {}

    def get(url, token, strict=False):
        for part, code in errors.items():
            if part in url:
                if strict and code != 404:
                    raise br.RegistryBuildError(f"{url} — HTTP {code}")
                return None
        if "/orgs/" in url:
            page = int(url.rsplit("page=", 1)[1])
            return pages[page - 1] if page <= len(pages) else []
        raise AssertionError(f"unexpected URL {url}")

    return get


def test_discovery_keeps_only_topic_repos_across_pages(monkeypatch):
    first = [_repo(f"crosspad-app{i}", ["crosspad-app"]) for i in range(60)]
    first += [_repo(f"tool{i}", ["crosspad-release"]) for i in range(40)]
    second = [_repo("crosspad-late", ["crosspad-app", "crosspad-release"]), _repo("fork", [])]
    monkeypatch.setattr(br, "_api_get", _fake_get([first, second]))

    names = [r["full_name"] for r in br.discover_app_repos("t")]

    assert len(names) == 61
    assert names[-1] == "CrossPad/crosspad-late"
    assert "CrossPad/tool0" not in names


def test_discovery_error_aborts_instead_of_returning_fewer_apps(monkeypatch):
    monkeypatch.setattr(br, "_api_get", _fake_get([[_repo("crosspad-a", ["crosspad-app"])]],
                                                  errors={"/orgs/": 502}))
    with pytest.raises(br.RegistryBuildError):
        br.discover_app_repos("t")


def test_metadata_server_error_aborts_but_missing_file_skips(monkeypatch):
    monkeypatch.setattr(br, "_api_get", _fake_get([], errors={"crosspad-gone": 404, "crosspad-flaky": 503}))
    assert br.fetch_app_metadata("CrossPad/crosspad-gone", "t") is None
    with pytest.raises(br.RegistryBuildError):
        br.fetch_app_metadata("CrossPad/crosspad-flaky", "t")


def test_api_get_strict_raises_on_http_error_but_not_on_404(monkeypatch):
    def fail(code):
        def urlopen(req, timeout):
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)
        return urlopen

    monkeypatch.setattr(br.urllib.request, "urlopen", fail(404))
    assert br._api_get("https://api.github.com/x", "t", strict=True) is None
    monkeypatch.setattr(br.urllib.request, "urlopen", fail(500))
    assert br._api_get("https://api.github.com/x", "t") is None
    with pytest.raises(br.RegistryBuildError):
        br._api_get("https://api.github.com/x", "t", strict=True)
