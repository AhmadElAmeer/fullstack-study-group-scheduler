import pytest

from scheduler import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(str(tmp_path / "test.db"))


@pytest.fixture
def client(app):
    return app.test_client()


class Api:
    """Helpers that keep the tests readable."""

    def __init__(self, client):
        self.c = client

    def group(self, name="Algorithms"):
        r = self.c.post("/api/groups", json={"name": name})
        assert r.status_code == 201, r.json
        return r.json["slug"]

    def join(self, slug, name):
        r = self.c.post(f"/api/groups/{slug}/members", json={"name": name})
        assert r.status_code == 201, r.json
        return r.json

    def put(self, slug, member, slots, key=None):
        return self.c.put(f"/api/groups/{slug}/members/{member['id']}/availability",
                          json={"slots": slots},
                          headers={"X-Member-Key": member["key"] if key is None else key})

    def suggest(self, slug, query=""):
        return self.c.get(f"/api/groups/{slug}/suggestions{query}")


@pytest.fixture
def api(client):
    return Api(client)
