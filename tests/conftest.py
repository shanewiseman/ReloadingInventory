from tempfile import TemporaryDirectory

import pytest

from storage_service.app import create_app
from storage_service.models import db


def pytest_addoption(parser):
    parser.addoption(
        "--run-selenium",
        action="store_true",
        default=False,
        help="run browser workflow tests that require Selenium and a running app",
    )
    parser.addoption(
        "--selenium-headful",
        action="store_true",
        default=False,
        help="run local Selenium Chrome with a visible browser window",
    )
    parser.addoption(
        "--selenium-remote-url",
        default=None,
        help="remote Selenium WebDriver URL, for example http://selenium:4444/wd/hub",
    )
    parser.addoption(
        "--selenium-slow-ms",
        type=int,
        default=None,
        help="pause this many milliseconds after visible Selenium actions",
    )
    parser.addoption(
        "--app-base-url",
        default=None,
        help="browser-facing application URL, for example http://localhost:8080 or http://web",
    )
    parser.addoption(
        "--e2e-email",
        default=None,
        help="email to use for Selenium workflow tests; defaults to a unique test account",
    )
    parser.addoption(
        "--e2e-cleanup-command",
        default=None,
        help="cleanup command template containing {email}; overrides automatic cleanup detection",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "selenium: browser-based Selenium workflow tests")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-selenium"):
        return
    skip_selenium = pytest.mark.skip(reason="need --run-selenium option to run browser workflow tests")
    for item in items:
        if "selenium" in item.keywords:
            item.add_marker(skip_selenium)


@pytest.fixture()
def app():
    with TemporaryDirectory() as file_storage_dir:
        app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SECRET_KEY": "test",
            "SESSION_HOURS": 1,
            "FILE_STORAGE_DIR": file_storage_dir,
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
