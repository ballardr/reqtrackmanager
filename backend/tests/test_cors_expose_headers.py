"""Tests for the response headers the CORS middleware exposes to a cross-origin page (see `app.main`)."""


def test_a_cross_origin_page_may_read_the_name_the_server_gave_a_download(client):
    """A browser hides `Content-Disposition` from a cross-origin fetch unless the CORS middleware exposes it; without
    it a download falls back to a client-side guess instead of the file-name template's result."""
    resp = client.get("/health", headers={"Origin": "http://localhost:3000"})

    exposed = {name.strip().lower() for name in resp.headers["access-control-expose-headers"].split(",")}
    assert "content-disposition" in exposed
