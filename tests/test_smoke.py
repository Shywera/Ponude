"""CI smoke — prijava i ključne stranice."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app


def _client():
    c = TestClient(app)
    r = c.post("/login", data={"username": "admin", "lozinka": "admin"},
               follow_redirects=False)
    assert r.status_code == 303
    return c


def test_login_stranica():
    c = TestClient(app)
    assert c.get("/login").status_code == 200


def test_kljucne_stranice():
    c = _client()
    for u in ["/", "/arhiva", "/statistika"]:
        r = c.get(u, follow_redirects=True)
        assert r.status_code == 200, u
