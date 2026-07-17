from __future__ import annotations

import os
from functools import wraps

import requests
from flask import Flask, g, jsonify, request

from .core import (
    BallisticsError,
    calculate_ballistics,
    fetch_open_meteo_current,
    fetch_open_meteo_geocode,
    parse_required_number,
)


OPEN_METEO_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        STORAGE_URL=os.getenv("STORAGE_URL", "http://localhost:5001").rstrip("/"),
        AUTH_HTTP_TIMEOUT_SECONDS=float(os.getenv("AUTH_HTTP_TIMEOUT_SECONDS", "5")),
        WEATHER_HTTP_TIMEOUT_SECONDS=float(os.getenv("WEATHER_HTTP_TIMEOUT_SECONDS", "6")),
        OPEN_METEO_GEOCODE_URL=os.getenv("OPEN_METEO_GEOCODE_URL", OPEN_METEO_GEOCODE_URL),
        OPEN_METEO_FORECAST_URL=os.getenv("OPEN_METEO_FORECAST_URL", OPEN_METEO_FORECAST_URL),
    )
    if test_config:
        app.config.update(test_config)

    register_error_handlers(app)
    register_routes(app)
    return app


def register_error_handlers(app):
    @app.errorhandler(BallisticsError)
    def handle_ballistics_error(error):
        return jsonify(error={
            "code": error.code,
            "message": error.message,
            "details": error.details,
        }), error.status

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify(error={"code": "not_found", "message": "Not found", "details": {}}), 404

    @app.errorhandler(405)
    def method_not_allowed(_error):
        return jsonify(error={
            "code": "method_not_allowed",
            "message": "Method not allowed",
            "details": {},
        }), 405


def auth_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        token = header[7:] if header.startswith("Bearer ") else ""
        if not token:
            raise BallisticsError("authentication_required", "Authentication is required", status=401)
        try:
            response = requests.get(
                f"{current_app_config()['STORAGE_URL']}/api/auth/me",
                headers={"Authorization": f"Bearer {token}"},
                timeout=current_app_config()["AUTH_HTTP_TIMEOUT_SECONDS"],
            )
        except requests.RequestException as exc:
            raise BallisticsError(
                "authentication_unavailable",
                f"Authentication service is unavailable: {exc}",
                status=502,
            )
        if response.status_code == 401:
            raise BallisticsError("authentication_required", "Authentication is required", status=401)
        if not response.ok:
            raise BallisticsError(
                "authentication_unavailable",
                "Authentication service rejected the token validation request",
                status=502,
            )
        try:
            g.user = response.json().get("user") or {}
        except ValueError as exc:
            raise BallisticsError("authentication_unavailable", "Authentication service returned invalid JSON", status=502) from exc
        return view(*args, **kwargs)
    return wrapper


def current_app_config():
    from flask import current_app

    return current_app.config


def register_routes(app):
    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/api/weather/geocode")
    @auth_required
    def geocode_weather_location():
        query = request.args.get("q", "").strip()
        if len(query) < 2:
            raise BallisticsError("validation_error", "Location search needs at least two characters", {"q": "too short"})
        locations = fetch_open_meteo_geocode(app.config, query)
        return jsonify(locations=locations)

    @app.get("/api/weather/current")
    @auth_required
    def current_weather():
        latitude = parse_required_number(request.args, "lat")
        longitude = parse_required_number(request.args, "lon")
        if latitude < -90 or latitude > 90:
            raise BallisticsError("validation_error", "Latitude must be between -90 and 90", {"lat": "invalid"})
        if longitude < -180 or longitude > 180:
            raise BallisticsError("validation_error", "Longitude must be between -180 and 180", {"lon": "invalid"})
        environment = fetch_open_meteo_current(app.config, float(latitude), float(longitude))
        return jsonify(environment=environment)

    @app.post("/api/ballistics/calculate")
    @auth_required
    def calculate_ballistics_route():
        result = calculate_ballistics(request.get_json(silent=True) or {})
        return jsonify(result=result)


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5002)

