"""Tests for static frontend serving (including traversal safety)."""

from __future__ import annotations


def test_index_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Math Checker V6" in response.text
    assert "/js/main.js" in response.text


def test_javascript_and_css_content_types(client):
    js = client.get("/js/main.js")
    assert js.status_code == 200
    assert js.headers["content-type"].startswith(("text/javascript", "application/javascript"))

    css = client.get("/css/tokens.css")
    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")


def test_lazy_page_modules_are_served(client):
    for path in (
        "/js/pages/dashboard.js",
        "/js/pages/correction.js",
        "/js/pages/settings.js",
        "/js/pages/storage.js",
        "/js/pages/tasks.js",
        "/js/pages/notfound.js",
    ):
        assert client.get(path).status_code == 200


def test_unknown_paths_are_404(client):
    assert client.get("/nope.html").status_code == 404
    assert client.get("/js/nope.js").status_code == 404


def test_path_traversal_is_blocked(client):
    for path in (
        "/%2e%2e/requirements.txt",
        "/..%2frequirements.txt",
        "/css/%2e%2e/%2e%2e/requirements.txt",
        "/js/%2e%2e/%2e%2e/.env",
    ):
        response = client.get(path)
        assert response.status_code in (301, 302, 307, 400, 404), path
        assert b"fastapi" not in response.content.lower() or response.status_code != 200
