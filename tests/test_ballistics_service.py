from ballistics_service.app import create_app


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.content = b"{}"

    def json(self):
        return self._payload

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError("request failed")


def auth_response(url, **_kwargs):
    if url.endswith("/api/auth/me"):
        return FakeResponse({"user": {"id": 1, "email": "owner@example.com"}})
    raise AssertionError(url)


def test_health_is_public():
    app = create_app({"TESTING": True, "STORAGE_URL": "http://storage.test"})

    response = app.test_client().get("/health")

    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_calculator_requires_bearer_token():
    app = create_app({"TESTING": True, "STORAGE_URL": "http://storage.test"})

    response = app.test_client().post("/api/ballistics/calculate", json={})

    assert response.status_code == 401
    assert response.json["error"]["code"] == "authentication_required"


def test_calculator_validates_token_and_returns_angular_corrections(monkeypatch):
    monkeypatch.setattr("ballistics_service.app.requests.get", auth_response)
    app = create_app({"TESTING": True, "STORAGE_URL": "http://storage.test"})

    response = app.test_client().post(
        "/api/ballistics/calculate",
        headers={"Authorization": "Bearer token"},
        json={
            "target_distance": "300",
            "zero_distance": "100",
            "muzzle_velocity": "2600",
            "ballistic_coefficient": "0.243",
            "drag_model": "G7",
            "sight_height": "1.5",
            "wind_speed": "10",
            "wind_angle": "90",
            "bullet_weight": "168",
            "environment": {
                "temperature_f": "59",
                "pressure_inhg": "29.92",
                "humidity_percent": "40",
                "altitude_ft": "0",
                "source": "test",
            },
        },
    )

    assert response.status_code == 200, response.json
    result = response.json["result"]
    assert result["vertical"]["correction_moa"] > 0
    assert result["vertical"]["correction_mil"] > 0
    assert result["wind"]["correction_moa"] > 0
    assert result["trajectory"]["time_of_flight_seconds"] > 0
    assert result["trajectory"]["remaining_energy_ft_lbf"] > 0


def test_open_meteo_weather_proxy_normalizes_environment(monkeypatch):
    def fake_get(url, **_kwargs):
        if url.endswith("/api/auth/me"):
            return FakeResponse({"user": {"id": 1}})
        return FakeResponse({
            "elevation": 1609.3,
            "current": {
                "time": "2026-07-11T12:00",
                "temperature_2m": 72.5,
                "relative_humidity_2m": 33,
                "surface_pressure": 836.5,
                "pressure_msl": 1013.2,
                "wind_speed_10m": 8.4,
                "wind_direction_10m": 270,
            },
        })

    monkeypatch.setattr("ballistics_service.core.requests.get", fake_get)
    app = create_app({
        "TESTING": True,
        "STORAGE_URL": "http://storage.test",
        "OPEN_METEO_FORECAST_URL": "http://weather.test/forecast",
    })

    response = app.test_client().get(
        "/api/weather/current",
        headers={"Authorization": "Bearer token"},
        query_string={"lat": "39.739", "lon": "-104.990"},
    )

    assert response.status_code == 200, response.json
    environment = response.json["environment"]
    assert environment["provider"] == "open-meteo"
    assert environment["temperature_f"] == 72.5
    assert round(environment["pressure_inhg"], 3) == 24.702
    assert round(environment["elevation_ft"]) == 5280


def test_geocode_uses_open_meteo(monkeypatch):
    def fake_get(url, **_kwargs):
        if url.endswith("/api/auth/me"):
            return FakeResponse({"user": {"id": 1}})
        return FakeResponse({
            "results": [{
                "id": 5419384,
                "name": "Denver",
                "admin1": "Colorado",
                "country": "United States",
                "country_code": "US",
                "latitude": 39.7392,
                "longitude": -104.9847,
                "elevation": 1609,
                "timezone": "America/Denver",
            }]
        })

    monkeypatch.setattr("ballistics_service.core.requests.get", fake_get)
    app = create_app({
        "TESTING": True,
        "STORAGE_URL": "http://storage.test",
        "OPEN_METEO_GEOCODE_URL": "http://weather.test/geocode",
    })

    response = app.test_client().get(
        "/api/weather/geocode",
        headers={"Authorization": "Bearer token"},
        query_string={"q": "Denver"},
    )

    assert response.status_code == 200, response.json
    location = response.json["locations"][0]
    assert location["name"] == "Denver"
    assert round(location["elevation_ft"]) == 5279
