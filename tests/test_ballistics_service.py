import pytest
import requests

from ballistics_service.app import create_app
from ballistics_service.core import (
    BallisticsError,
    as_decimal,
    ballistic_input_warnings,
    calculate_ballistics,
    clean_drag_model,
    fetch_open_meteo_current,
    fetch_open_meteo_geocode,
    hpa_to_inhg,
    parse_optional_positive_decimal,
    parse_required_number,
    parse_required_positive_decimal,
)


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


class InvalidJsonResponse(FakeResponse):
    def json(self):
        raise ValueError("invalid json")


def auth_response(url, **_kwargs):
    if url.endswith("/api/auth/me"):
        return FakeResponse({"user": {"id": 1, "email": "owner@example.com"}})
    raise AssertionError(url)


def test_health_is_public():
    app = create_app({"TESTING": True, "STORAGE_URL": "http://storage.test"})

    response = app.test_client().get("/health")

    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_create_app_reads_environment_defaults(monkeypatch):
    monkeypatch.setenv("STORAGE_URL", "http://storage.test/")

    app = create_app()

    assert app.config["STORAGE_URL"] == "http://storage.test"


def test_error_handlers_return_json_for_not_found_and_method_not_allowed():
    app = create_app({"TESTING": True, "STORAGE_URL": "http://storage.test"})
    client = app.test_client()

    missing = client.get("/not-a-route")
    wrong_method = client.get("/api/ballistics/calculate")

    assert missing.status_code == 404
    assert missing.json["error"]["code"] == "not_found"
    assert wrong_method.status_code == 405
    assert wrong_method.json["error"]["code"] == "method_not_allowed"


def test_calculator_requires_bearer_token():
    app = create_app({"TESTING": True, "STORAGE_URL": "http://storage.test"})

    response = app.test_client().post("/api/ballistics/calculate", json={})

    assert response.status_code == 401
    assert response.json["error"]["code"] == "authentication_required"


@pytest.mark.parametrize((
    "mode",
    "expected_status",
    "expected_code",
), [
    ("request_exception", 502, "authentication_unavailable"),
    ("unauthorized", 401, "authentication_required"),
    ("rejected", 502, "authentication_unavailable"),
    ("invalid_json", 502, "authentication_unavailable"),
])
def test_authenticated_routes_report_auth_validation_failures(monkeypatch, mode, expected_status, expected_code):
    def fake_get(url, **_kwargs):
        if not url.endswith("/api/auth/me"):
            raise AssertionError(url)
        if mode == "request_exception":
            raise requests.RequestException("storage unavailable")
        if mode == "unauthorized":
            return FakeResponse({}, status_code=401)
        if mode == "rejected":
            return FakeResponse({}, status_code=503)
        return InvalidJsonResponse({})

    monkeypatch.setattr("ballistics_service.app.requests.get", fake_get)
    app = create_app({"TESTING": True, "STORAGE_URL": "http://storage.test"})

    response = app.test_client().get(
        "/api/weather/geocode",
        headers={"Authorization": "Bearer token"},
        query_string={"q": "Denver"},
    )

    assert response.status_code == expected_status
    assert response.json["error"]["code"] == expected_code


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
    assert result["solver"]["name"] == "py-ballisticcalc"
    assert result["solver"]["version"] == "2.2.10"
    assert result["solver"]["engine"] == "RK4IntegrationEngine"
    assert result["solver"]["drag_model"] == "G7"
    assert result["warnings"] == []


def test_core_validation_helpers_raise_structured_errors():
    assert parse_optional_positive_decimal(None, "optional") is None
    assert parse_optional_positive_decimal("", "optional") is None
    assert hpa_to_inhg(None) is None

    with pytest.raises(BallisticsError) as invalid_decimal:
        as_decimal("not numeric", "velocity")
    assert invalid_decimal.value.code == "validation_error"

    with pytest.raises(BallisticsError) as non_positive:
        parse_optional_positive_decimal("0", "distance")
    assert non_positive.value.code == "invalid_number"

    with pytest.raises(BallisticsError) as missing_positive:
        parse_required_positive_decimal({}, "target_distance")
    assert missing_positive.value.details == {"target_distance": "required"}

    with pytest.raises(BallisticsError) as missing_number:
        parse_required_number({}, "lat")
    assert missing_number.value.details == {"lat": "required"}

    with pytest.raises(BallisticsError) as invalid_drag_model:
        clean_drag_model("G8")
    assert invalid_drag_model.value.details == {"drag_model": "G1 or G7"}


def test_ballistic_input_warnings_cover_low_and_high_edge_cases():
    low_bc = ballistic_input_warnings("G1", 0.04)
    high_g7_low_weight = ballistic_input_warnings("G7", 0.9, bullet_weight=10)

    assert low_bc[0]["code"] == "implausible_bc"
    assert low_bc[0]["field"] == "ballistic_coefficient"
    assert [warning["code"] for warning in high_g7_low_weight] == [
        "implausible_bc",
        "implausible_bullet_weight",
    ]


def test_g1_drag_table_calculation_has_realistic_velocity_loss():
    result = calculate_ballistics({
        "target_distance": "300",
        "zero_distance": "100",
        "muzzle_velocity": "1486",
        "ballistic_coefficient": "0.206",
        "drag_model": "G1",
        "sight_height": "1.5",
        "wind_speed": "0",
        "wind_angle": "90",
        "bullet_weight": "158",
        "environment": {
            "temperature_f": "82.9",
            "pressure_inhg": "29.707",
            "humidity_percent": "33",
            "altitude_ft": "226",
            "source": "test",
        },
    })

    assert result["solver"]["drag_model"] == "G1"
    assert 900 < result["trajectory"]["remaining_velocity_fps"] < 1100
    assert result["trajectory"]["remaining_velocity_fps"] < 1486 - 300
    assert result["vertical"]["offset_inches"] > 60
    assert result["trajectory"]["remaining_energy_ft_lbf"] > 300


def test_zero_distance_solves_near_point_of_aim():
    result = calculate_ballistics({
        "target_distance": "100",
        "zero_distance": "100",
        "muzzle_velocity": "2600",
        "ballistic_coefficient": "0.243",
        "drag_model": "G7",
        "sight_height": "1.5",
        "bullet_weight": "168",
    })

    assert abs(result["vertical"]["offset_inches"]) < 0.01
    assert abs(result["vertical"]["correction_moa"]) < 0.01


def test_wind_correction_is_zero_without_wind_and_positive_with_crosswind():
    base = {
        "target_distance": "300",
        "zero_distance": "100",
        "muzzle_velocity": "2600",
        "ballistic_coefficient": "0.243",
        "drag_model": "G7",
        "sight_height": "1.5",
        "bullet_weight": "168",
        "wind_angle": "90",
    }

    calm = calculate_ballistics({**base, "wind_speed": "0"})
    crosswind = calculate_ballistics({**base, "wind_speed": "10"})

    assert calm["wind"]["correction_moa"] == 0
    assert crosswind["wind"]["correction_moa"] > 0
    assert crosswind["wind"]["offset_inches"] > calm["wind"]["offset_inches"]


def test_environment_mapping_changes_density_ratio():
    standard = calculate_ballistics({
        "target_distance": "300",
        "zero_distance": "100",
        "muzzle_velocity": "2600",
        "ballistic_coefficient": "0.243",
        "drag_model": "G7",
        "sight_height": "1.5",
    })
    hot_thin = calculate_ballistics({
        "target_distance": "300",
        "zero_distance": "100",
        "muzzle_velocity": "2600",
        "ballistic_coefficient": "0.243",
        "drag_model": "G7",
        "sight_height": "1.5",
        "environment": {
            "temperature_f": "95",
            "pressure_inhg": "24.70",
            "humidity_percent": "35",
            "altitude_ft": "5280",
        },
    })

    assert hot_thin["inputs"]["air_density_ratio"] < standard["inputs"]["air_density_ratio"]


def test_implausible_bc_warning_does_not_block_calculation():
    result = calculate_ballistics({
        "target_distance": "300",
        "zero_distance": "100",
        "muzzle_velocity": "1486",
        "ballistic_coefficient": "1.7",
        "drag_model": "G1",
        "sight_height": "1.5",
    })

    assert result["trajectory"]["remaining_velocity_fps"] > 0
    assert result["warnings"][0]["code"] == "implausible_bc"
    assert result["warnings"][0]["field"] == "ballistic_coefficient"


def test_library_failure_returns_calculation_error(monkeypatch):
    class BrokenCalculator:
        def __init__(self, *_args, **_kwargs):
            pass

        def set_weapon_zero(self, *_args, **_kwargs):
            raise RuntimeError("solver exploded")

    monkeypatch.setattr("ballistics_service.app.requests.get", auth_response)
    monkeypatch.setattr("ballistics_service.core.Calculator", BrokenCalculator)
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
        },
    )

    assert response.status_code == 422
    assert response.json["error"]["code"] == "calculation_error"


def test_weather_routes_validate_query_and_coordinate_inputs(monkeypatch):
    monkeypatch.setattr("ballistics_service.app.requests.get", auth_response)
    app = create_app({"TESTING": True, "STORAGE_URL": "http://storage.test"})
    client = app.test_client()
    headers = {"Authorization": "Bearer token"}

    short_query = client.get("/api/weather/geocode", headers=headers, query_string={"q": "D"})
    missing_lat = client.get("/api/weather/current", headers=headers, query_string={"lon": "0"})
    invalid_lat = client.get("/api/weather/current", headers=headers, query_string={"lat": "91", "lon": "0"})
    invalid_lon = client.get("/api/weather/current", headers=headers, query_string={"lat": "0", "lon": "-181"})

    assert short_query.status_code == 400
    assert short_query.json["error"]["details"] == {"q": "too short"}
    assert missing_lat.status_code == 400
    assert missing_lat.json["error"]["details"] == {"lat": "required"}
    assert invalid_lat.status_code == 400
    assert invalid_lat.json["error"]["details"] == {"lat": "invalid"}
    assert invalid_lon.status_code == 400
    assert invalid_lon.json["error"]["details"] == {"lon": "invalid"}


def test_open_meteo_helpers_wrap_provider_request_and_json_failures(monkeypatch):
    config = {
        "OPEN_METEO_GEOCODE_URL": "http://weather.test/geocode",
        "OPEN_METEO_FORECAST_URL": "http://weather.test/forecast",
        "WEATHER_HTTP_TIMEOUT_SECONDS": 1,
    }

    def unavailable(*_args, **_kwargs):
        raise requests.RequestException("offline")

    monkeypatch.setattr("ballistics_service.core.requests.get", unavailable)
    with pytest.raises(BallisticsError) as geocode_request_error:
        fetch_open_meteo_geocode(config, "Denver")
    assert geocode_request_error.value.code == "weather_unavailable"

    with pytest.raises(BallisticsError) as current_request_error:
        fetch_open_meteo_current(config, 39.739, -104.99)
    assert current_request_error.value.code == "weather_unavailable"

    monkeypatch.setattr(
        "ballistics_service.core.requests.get",
        lambda *_args, **_kwargs: InvalidJsonResponse({}),
    )
    with pytest.raises(BallisticsError) as geocode_json_error:
        fetch_open_meteo_geocode(config, "Denver")
    assert geocode_json_error.value.message == "Weather location lookup returned invalid JSON"

    with pytest.raises(BallisticsError) as current_json_error:
        fetch_open_meteo_current(config, 39.739, -104.99)
    assert current_json_error.value.message == "Current weather lookup returned invalid JSON"


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
