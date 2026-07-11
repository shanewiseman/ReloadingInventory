from __future__ import annotations

import math
from datetime import timezone, datetime
from decimal import Decimal, InvalidOperation

import requests


DRAG_MODELS = {"G1", "G7"}
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
    wind_speed = optional_float(data, "wind_speed", 0.0)
    wind_angle = optional_float(data, "wind_angle", 90.0)
    bullet_weight = optional_float(data, "bullet_weight", None)
    shooting_angle = optional_float(data, "shooting_angle", 0.0)
    environment = normalized_ballistic_environment(data)
    density_ratio = air_density_ratio(environment)
    zero_angle = solve_zero_angle(
        zero_yards,
        muzzle_velocity,
        ballistic_coefficient,
        drag_model,
        sight_height,
        density_ratio,
        shooting_angle,
    )
    trajectory = simulate_trajectory(
        target_yards,
        muzzle_velocity,
        ballistic_coefficient,
        drag_model,
        sight_height,
        density_ratio,
        zero_angle,
        shooting_angle,
    )
    vertical_inches = -trajectory["y_ft"] * 12.0
    wind_inches = wind_drift_inches(wind_speed, wind_angle, trajectory, muzzle_velocity)
    energy = (
        bullet_weight * trajectory["velocity_fps"] * trajectory["velocity_fps"] / 450240.0
        if bullet_weight and trajectory["velocity_fps"] > 0 else None
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
            "air_density_ratio": density_ratio,
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
            "zero_angle_degrees": math.degrees(zero_angle),
            "time_of_flight_seconds": trajectory["time_seconds"],
            "remaining_velocity_fps": trajectory["velocity_fps"],
            "remaining_energy_ft_lbf": energy,
        },
    }


def positive_float(data, field):
    value = parse_required_positive_decimal(data, field)
    return float(value)


def optional_float(data, field, default):
    value = data.get(field)
    if value in (None, ""):
        return default
    return float(as_decimal(value, field))


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


def air_density_ratio(environment):
    temp_rankine = float(environment["temperature_f"]) + 459.67
    pressure_ratio = float(environment["pressure_inhg"]) / STANDARD_ENVIRONMENT["pressure_inhg"]
    temperature_ratio = 518.67 / max(temp_rankine, 1.0)
    humidity_ratio = 1.0 - 0.00378 * (float(environment["humidity_percent"]) / 100.0)
    return max(0.25, min(1.4, pressure_ratio * temperature_ratio * humidity_ratio))


def solve_zero_angle(zero_yards, muzzle_velocity, bc, drag_model, sight_height, density_ratio, shooting_angle):
    low = math.radians(-5)
    high = math.radians(10)
    for _ in range(48):
        mid = (low + high) / 2
        impact = simulate_trajectory(
            zero_yards,
            muzzle_velocity,
            bc,
            drag_model,
            sight_height,
            density_ratio,
            mid,
            shooting_angle,
        )["y_ft"]
        if impact > 0:
            high = mid
        else:
            low = mid
    return (low + high) / 2


def simulate_trajectory(range_yards, muzzle_velocity, bc, drag_model, sight_height, density_ratio, bore_angle, shooting_angle):
    range_ft = float(range_yards) * 3.0 * math.cos(math.radians(float(shooting_angle or 0.0)))
    range_ft = max(range_ft, 0.1)
    x = 0.0
    y = -float(sight_height) / 12.0
    vx = float(muzzle_velocity) * math.cos(bore_angle)
    vy = float(muzzle_velocity) * math.sin(bore_angle)
    elapsed = 0.0
    previous = (x, y, vx, vy, elapsed)
    while x < range_ft and elapsed < 8.0 and vx > 1.0:
        previous = (x, y, vx, vy, elapsed)
        remaining = range_ft - x
        dt = min(0.003, remaining / max(vx, 1.0))
        speed = max(math.hypot(vx, vy), 1.0)
        drag = drag_acceleration(speed, bc, drag_model, density_ratio)
        x += vx * dt
        y += vy * dt
        vx -= drag * (vx / speed) * dt
        vy -= (32.174 + drag * (vy / speed)) * dt
        elapsed += dt
    px, py, pvx, pvy, pt = previous
    if x != px:
        ratio = min(max((range_ft - px) / (x - px), 0.0), 1.0)
        y = py + (y - py) * ratio
        elapsed = pt + (elapsed - pt) * ratio
        vx = pvx + (vx - pvx) * ratio
        vy = pvy + (vy - pvy) * ratio
    return {"y_ft": y, "time_seconds": elapsed, "velocity_fps": max(math.hypot(vx, vy), 0.0)}


def drag_acceleration(speed, bc, drag_model, density_ratio):
    mach = speed / 1116.0
    transonic = 1.0 + 0.25 * math.exp(-((mach - 1.1) / 0.32) ** 2)
    supersonic = 1.0 + max(mach - 1.0, 0.0) * 0.08
    base = 0.000026 if drag_model == "G1" else 0.000020
    return base * density_ratio * transonic * supersonic * speed * speed / max(float(bc), 0.001)


def wind_drift_inches(wind_speed_mph, wind_angle_degrees, trajectory, muzzle_velocity):
    crosswind = float(wind_speed_mph or 0.0) * math.sin(math.radians(float(wind_angle_degrees or 0.0)))
    crosswind_fps = crosswind * 1.466666667
    velocity_loss = max(0.0, min(1.0, 1.0 - trajectory["velocity_fps"] / max(float(muzzle_velocity), 1.0)))
    lag_factor = 0.14 + velocity_loss * 0.24
    return crosswind_fps * trajectory["time_seconds"] * lag_factor * 12.0


def angular_moa(offset_inches, range_yards):
    return offset_inches / (float(range_yards) * 1.047 / 100.0)


def angular_mil(offset_inches, range_yards):
    return offset_inches / (float(range_yards) * 36.0 / 1000.0)

