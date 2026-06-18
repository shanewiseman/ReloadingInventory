import pytest

from storage_service.app import create_app
from storage_service.models import db


@pytest.fixture()
def app():
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "SECRET_KEY": "test",
        "SESSION_HOURS": 1,
    })
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def register_and_login(client, email="owner@example.com"):
    password = "correct-horse-battery"
    response = client.post("/api/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json['token']}"}


@pytest.fixture()
def auth(client):
    return register_and_login(client)

