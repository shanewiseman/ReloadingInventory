from __future__ import annotations

from datetime import timezone, datetime
from decimal import Decimal, InvalidOperation

import py_ballisticcalc
import requests
from py_ballisticcalc import (
    Ammo,
    Angular,
    Atmo,
    Calculator,
    Distance,
    DragModel,
    Pressure,
    Shot,
    Temperature,
    Velocity,
    Weapon,
    Wind,
)
from py_ballisticcalc.drag_tables import TableG1, TableG7
from py_ballisticcalc.engines.rk4 import RK4IntegrationEngine


DRAG_MODELS = {"G1", "G7"}
DRAG_TABLES = {"G1": TableG1, "G7": TableG7}
SOLVER_NAME = "py-ballisticcalc"
SOLVER_ENGINE = "RK4IntegrationEngine"
STANDARD_ENVIRONMENT = {
    "temperature_f": 59.0,
    "pressure_inhg": 29.92,
    "humidity_percent": 0.0,
    "altitude_ft": 0.0,
}


class BallisticsError(Exception):
    def __init__(self, code, message, details=None, status=400):
        self.code = code
        self.message = message
        self.details = details or {}
        self.status = status
        super().__init__(message)


def utcnow():
    return datetime.now(timezone.utc)


def as_decimal(value, field):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise BallisticsError("validation_error", f"{field} must be numeric", {field: "invalid number"})


def parse_optional_positive_decimal(value, field):
    if value in (None, ""):
        return None
    result = as_decimal(value, field)
    if result <= 0:
        raise BallisticsError("invalid_number", f"{field} must be positive", {field: "must be positive"})
    return result


def parse_optional_non_negative_decimal(value, field):
    if value in (None, ""):
        return None
    result = as_decimal(value, field)
    if result < 0:
        raise BallisticsError(
            "invalid_number",
            f"{field} must be zero or positive",
            {field: "must be zero or positive"},
        )
    return result


def parse_required_positive_decimal(data, field):
    if data.get(field) in (None, ""):
        raise BallisticsError("validation_error", f"{field} is required", {field: "required"})
    return parse_optional_positive_decimal(data.get(field), field)


def parse_required_number(data, field):
    if data.get(field) in (None, ""):
        raise BallisticsError("validation_error", f"{field} is required", {field: "required"})
    return as_decimal(data.get(field), field)


def clean_drag_model(value):
    drag_model = str(value or "").strip().upper()
    if drag_model not in DRAG_MODELS:
        raise BallisticsError("validation_error", "Drag model must be G1 or G7", {"drag_model": "G1 or G7"})
    return drag_model


def fetch_open_meteo_geocode(config, query):
    try:
        response = requests.get(
            config["OPEN_METEO_GEOCODE_URL"],
            params={"name": query, "count": 8, "language": "en", "format": "json"},
            timeout=config["WEATHER_HTTP_TIMEOUT_SECONDS"],
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        raise BallisticsError("weather_unavailable", f"Weather location lookup failed: {exc}", status=502)
    except ValueError as exc:
        raise BallisticsError("weather_unavailable", "Weather location lookup returned invalid JSON", status=502) from exc
    return [
        {
            "id": row.get("id"),
            "name": row.get("name"),
            "admin1": row.get("admin1"),
            "country": row.get("country"),
            "country_code": row.get("country_code"),
            "latitude": row.get("latitude"),
            "longitude": row.get("longitude"),
            "elevation_ft": (
                float(row["elevation"]) * 3.280839895
                if row.get("elevation") is not None else None
            ),
            "timezone": row.get("timezone"),
        }
        for row in data.get("results") or []
        if row.get("latitude") is not None and row.get("longitude") is not None
    ]


def fetch_open_meteo_current(config, latitude, longitude):
    try:
        response = requests.get(
            config["OPEN_METEO_FORECAST_URL"],
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": ",".join([
                    "temperature_2m",
                    "relative_humidity_2m",
                    "pressure_msl",
                    "surface_pressure",
                    "wind_speed_10m",
                    "wind_direction_10m",
                ]),
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "forecast_days": 1,
            },
            timeout=config["WEATHER_HTTP_TIMEOUT_SECONDS"],
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        raise BallisticsError("weather_unavailable", f"Current weather lookup failed: {exc}", status=502)
    except ValueError as exc:
        raise BallisticsError("weather_unavailable", "Current weather lookup returned invalid JSON", status=502) from exc
    current = data.get("current") or {}
    surface_pressure = current.get("surface_pressure")
    sea_level_pressure = current.get("pressure_msl")
    return {
        "provider": "open-meteo",
        "source": "Open-Meteo current conditions",
        "fetched_at": utcnow().isoformat(),
        "observed_at": current.get("time"),
        "latitude": latitude,
        "longitude": longitude,
        "elevation_ft": (
            float(data["elevation"]) * 3.280839895
            if data.get("elevation") is not None else None
        ),
        "temperature_f": current.get("temperature_2m"),
        "humidity_percent": current.get("relative_humidity_2m"),
        "pressure_inhg": hpa_to_inhg(surface_pressure),
        "surface_pressure_inhg": hpa_to_inhg(surface_pressure),
        "sea_level_pressure_inhg": hpa_to_inhg(sea_level_pressure),
        "wind_speed_mph": current.get("wind_speed_10m"),
        "wind_direction_degrees": current.get("wind_direction_10m"),
    }


def hpa_to_inhg(value):
    if value is None:
        return None
    return float(value) * 0.0295299830714


def calculate_ballistics(data):
    target_yards = positive_float(data, "target_distance")
    zero_yards = positive_float(data, "zero_distance")
    muzzle_velocity = positive_float(data, "muzzle_velocity")
    ballistic_coefficient = positive_float(data, "ballistic_coefficient")
    drag_model = clean_drag_model(data.get("drag_model"))
    sight_height = positive_float(data, "sight_height")
    wind_speed = optional_non_negative_float(data, "wind_speed", 0.0)
    wind_angle = optional_float(data, "wind_angle", 90.0)
    bullet_weight = optional_positive_float(data, "bullet_weight", None)
    shooting_angle = optional_float(data, "shooting_angle", 0.0)
    environment = normalized_ballistic_environment(data)
    atmo = ballistic_atmosphere(environment)
    try:
        weapon = Weapon(sight_height=Distance.Inch(sight_height))
        ammo = Ammo(
            DragModel(
                ballistic_coefficient,
                DRAG_TABLES[drag_model],
                weight=bullet_weight or 0,
            ),
            mv=Velocity.FPS(muzzle_velocity),
        )
        winds = [
            Wind(
                Velocity.MPH(wind_speed),
                Angular.Degree(wind_angle),
                until_distance=Distance.Yard(target_yards),
            )
        ] if wind_speed else []
        shot = Shot(
            ammo=ammo,
            atmo=atmo,
            weapon=weapon,
            winds=winds,
            look_angle=Angular.Degree(shooting_angle),
        )
        calculator = Calculator(engine=RK4IntegrationEngine)
        zero_elevation = calculator.set_weapon_zero(shot, Distance.Yard(zero_yards))
        hit_result = calculator.fire(
            shot,
            trajectory_range=Distance.Yard(target_yards),
            trajectory_step=Distance.Yard(target_yards),
            raise_range_error=True,
        )
        trajectory_row = list(hit_result)[-1]
    except Exception as exc:
        raise BallisticsError(
            "calculation_error",
            f"Ballistic calculation failed: {exc}",
            status=422,
        ) from exc

    vertical_inches = -(trajectory_row.height >> Distance.Inch)
    wind_inches = trajectory_row.windage >> Distance.Inch
    remaining_velocity = trajectory_row.velocity >> Velocity.FPS
    energy = (
        bullet_weight * remaining_velocity * remaining_velocity / 450240.0
        if bullet_weight and remaining_velocity > 0 else None
    )
    return {
        "inputs": {
            "target_distance": target_yards,
            "zero_distance": zero_yards,
            "muzzle_velocity": muzzle_velocity,
            "ballistic_coefficient": ballistic_coefficient,
            "drag_model": drag_model,
            "sight_height": sight_height,
            "wind_speed": wind_speed,
            "wind_angle": wind_angle,
            "bullet_weight": bullet_weight,
            "shooting_angle": shooting_angle,
            "environment": environment,
            "air_density_ratio": atmo.density_ratio,
        },
        "vertical": {
            "offset_inches": vertical_inches,
            "correction_moa": angular_moa(vertical_inches, target_yards),
            "correction_mil": angular_mil(vertical_inches, target_yards),
        },
        "wind": {
            "offset_inches": wind_inches,
            "correction_moa": angular_moa(wind_inches, target_yards),
            "correction_mil": angular_mil(wind_inches, target_yards),
        },
        "trajectory": {
            "zero_angle_degrees": zero_elevation >> Angular.Degree,
            "time_of_flight_seconds": trajectory_row.time,
            "remaining_velocity_fps": remaining_velocity,
            "remaining_energy_ft_lbf": energy,
        },
        "solver": {
            "name": SOLVER_NAME,
            "version": py_ballisticcalc.__version__,
            "engine": SOLVER_ENGINE,
            "drag_model": drag_model,
        },
        "warnings": ballistic_input_warnings(drag_model, ballistic_coefficient, bullet_weight),
    }


def positive_float(data, field):
    value = parse_required_positive_decimal(data, field)
    return float(value)


def optional_float(data, field, default):
    value = data.get(field)
    if value in (None, ""):
        return default
    return float(as_decimal(value, field))


def optional_positive_float(data, field, default):
    value = parse_optional_positive_decimal(data.get(field), field)
    return default if value is None else float(value)


def optional_non_negative_float(data, field, default):
    value = parse_optional_non_negative_decimal(data.get(field), field)
    return default if value is None else float(value)


def normalized_ballistic_environment(data):
    supplied = data.get("environment") if isinstance(data.get("environment"), dict) else data
    temperature = optional_float(supplied, "temperature_f", STANDARD_ENVIRONMENT["temperature_f"])
    humidity = optional_float(supplied, "humidity_percent", STANDARD_ENVIRONMENT["humidity_percent"])
    altitude = optional_float(supplied, "altitude_ft", STANDARD_ENVIRONMENT["altitude_ft"])
    pressure = optional_float(supplied, "pressure_inhg", None)
    if pressure is None:
        pressure = pressure_from_altitude(altitude)
    return {
        "temperature_f": temperature,
        "pressure_inhg": pressure,
        "humidity_percent": min(max(humidity, 0.0), 100.0),
        "altitude_ft": altitude,
        "source": supplied.get("source") or "manual/default",
    }


def pressure_from_altitude(altitude_ft):
    altitude_ft = max(float(altitude_ft or 0.0), -1500.0)
    return STANDARD_ENVIRONMENT["pressure_inhg"] * (1 - 0.00000687535 * altitude_ft) ** 5.2559


def ballistic_atmosphere(environment):
    return Atmo(
        altitude=Distance.Foot(environment["altitude_ft"]),
        pressure=Pressure.InHg(environment["pressure_inhg"]),
        temperature=Temperature.Fahrenheit(environment["temperature_f"]),
        humidity=environment["humidity_percent"],
    )


def ballistic_input_warnings(drag_model, ballistic_coefficient, bullet_weight=None):
    warnings = []
    if ballistic_coefficient < 0.05:
        warnings.append({
            "code": "implausible_bc",
            "field": "ballistic_coefficient",
            "message": "Ballistic coefficient is unusually low; verify the entered value and drag model.",
        })
    if drag_model == "G1" and ballistic_coefficient >= 1.1:
        warnings.append({
            "code": "implausible_bc",
            "field": "ballistic_coefficient",
            "message": "G1 ballistic coefficient is unusually high for common small-arms bullets; check decimal placement.",
        })
    if drag_model == "G7" and ballistic_coefficient >= 0.8:
        warnings.append({
            "code": "implausible_bc",
            "field": "ballistic_coefficient",
            "message": "G7 ballistic coefficient is unusually high for common small-arms bullets; check decimal placement.",
        })
    if bullet_weight is not None and bullet_weight < 15:
        warnings.append({
            "code": "implausible_bullet_weight",
            "field": "bullet_weight",
            "message": "Bullet weight is unusually low for grains; verify the unit and value.",
        })
    return warnings


def angular_moa(offset_inches, range_yards):
    return offset_inches / (float(range_yards) * 1.047 / 100.0)


def angular_mil(offset_inches, range_yards):
    return offset_inches / (float(range_yards) * 36.0 / 1000.0)
