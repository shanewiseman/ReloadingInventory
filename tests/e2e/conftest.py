from __future__ import annotations

import os
import shutil
import shlex
import subprocess
import uuid
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def app_base_url(pytestconfig):
    return (
        pytestconfig.getoption("--app-base-url")
        or os.getenv("APP_BASE_URL")
        or "http://localhost:8080"
    ).rstrip("/")


@pytest.fixture(scope="session")
def selenium_remote_url(pytestconfig):
    return pytestconfig.getoption("--selenium-remote-url") or os.getenv("SELENIUM_REMOTE_URL")


@pytest.fixture(scope="session")
def selenium_headless(pytestconfig):
    if pytestconfig.getoption("--selenium-headful"):
        return False
    value = os.getenv("SELENIUM_HEADLESS", "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


@pytest.fixture(scope="session")
def selenium_slow_seconds(pytestconfig):
    value = pytestconfig.getoption("--selenium-slow-ms")
    if value is None:
        value = os.getenv("SELENIUM_SLOW_MS", "0")
    return max(int(value), 0) / 1000


@pytest.fixture(scope="session")
def driver(pytestconfig, selenium_remote_url, selenium_headless):
    selenium = pytest.importorskip("selenium", reason="selenium package is not installed")
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    options.add_argument("--window-size=1440,1100")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    if selenium_headless:
        options.add_argument("--headless=new")

    if selenium_remote_url:
        from selenium.webdriver.remote.file_detector import LocalFileDetector

        browser = webdriver.Remote(command_executor=selenium_remote_url, options=options)
        browser.file_detector = LocalFileDetector()
    else:
        browser = webdriver.Chrome(options=options)

    browser.set_page_load_timeout(30)
    try:
        yield browser
    finally:
        browser.quit()


@pytest.fixture()
def e2e_user(pytestconfig):
    email = pytestconfig.getoption("--e2e-email") or os.getenv("E2E_EMAIL")
    if not email:
        email = f"e2e-357-{uuid.uuid4().hex[:10]}@example.test"
    password = os.getenv("E2E_PASSWORD", "correct-horse-battery")

    cleanup_user(pytestconfig, email)
    try:
        yield {"email": email, "password": password, "display_name": "Selenium 357 Workflow"}
    finally:
        cleanup_user(pytestconfig, email)


def cleanup_user(pytestconfig, email):
    command_template = (
        pytestconfig.getoption("--e2e-cleanup-command")
        or os.getenv("E2E_CLEANUP_COMMAND")
        or default_cleanup_command()
    )
    if not command_template:
        return

    command = shlex.split(command_template.format(email=email))
    subprocess.run(
        command,
        cwd=repository_root(),
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=45,
    )


def default_cleanup_command():
    if os.getenv("DATABASE_URL"):
        return "flask --app storage_service.app delete-user {email}"
    if shutil.which("docker") and (repository_root() / "compose.yaml").exists():
        return "docker compose exec -T storage flask --app storage_service.app delete-user {email}"
    return None


def repository_root():
    return Path(__file__).resolve().parents[2]
