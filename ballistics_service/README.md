# Reload Ledger Ballistics Service

This service provides authenticated trajectory calculations and weather lookup for Reload Ledger. It is a separate Flask app used by the renderer's **Ballistics** page and by storage APIs that persist saved ballistic calculations.

The service is descriptive only. It calculates corrections from user-provided inputs; it does not recommend load data, infer safe powder charges, validate recipe safety, or certify that a recipe is suitable for any firearm.

## Runtime

The Docker Compose stack runs the service as `ballistics` on port `5002` inside the private Reload Ledger network. It is not published directly to the host in normal deployments.

Relevant `compose.yaml` environment:

```dotenv
STORAGE_URL=http://storage:5001
OPEN_METEO_GEOCODE_URL=https://geocoding-api.open-meteo.com/v1/search
OPEN_METEO_FORECAST_URL=https://api.open-meteo.com/v1/forecast
WEATHER_HTTP_TIMEOUT_SECONDS=6
AUTH_HTTP_TIMEOUT_SECONDS=5
```

`STORAGE_URL` is used to validate bearer tokens against `/api/auth/me`. Weather endpoints proxy Open-Meteo responses and normalize units for the calculator UI.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/health` | No | Container health check. |
| `GET` | `/api/weather/geocode?q=<query>` | Bearer token | Search Open-Meteo locations. |
| `GET` | `/api/weather/current?lat=<lat>&lon=<lon>` | Bearer token | Fetch current weather and normalize environment values. |
| `POST` | `/api/ballistics/calculate` | Bearer token | Calculate trajectory correction. |

Authenticated routes require:

```http
Authorization: Bearer <reload-ledger-session-token>
```

## Calculation Input

Required fields:

- `target_distance` in yards.
- `zero_distance` in yards.
- `muzzle_velocity` in fps.
- `ballistic_coefficient`.
- `drag_model`, either `G1` or `G7`.
- `sight_height` in inches.

Optional fields:

- `wind_speed` in mph, default `0`.
- `wind_angle` in degrees, default `90`.
- `bullet_weight` in grains.
- `shooting_angle` in degrees, default `0`.
- `environment.temperature_f`.
- `environment.pressure_inhg`.
- `environment.humidity_percent`.
- `environment.altitude_ft`.

If pressure is omitted, the service estimates pressure from altitude. If environment values are omitted, it uses standard atmosphere values.

Example:

```json
{
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
    "altitude_ft": "0"
  }
}
```

## Calculation Output

Responses include:

- Normalized inputs and air-density ratio.
- Vertical drop/correction in inches, MOA, and mil.
- Wind offset/correction in inches, MOA, and mil.
- Zero angle, time of flight, remaining velocity, and remaining energy when bullet weight is supplied.
- Solver metadata: `py-ballisticcalc`, `RK4IntegrationEngine`, version, and drag model.
- Non-blocking warnings for implausible inputs.

Errors are JSON objects with `error.code`, `error.message`, and optional `error.details`.

## Weather Lookup

`/api/weather/geocode` requires at least two characters and returns matching locations with latitude, longitude, elevation in feet, and timezone.

`/api/weather/current` validates latitude and longitude, fetches Open-Meteo current conditions, and returns:

- Temperature in Fahrenheit.
- Relative humidity.
- Surface and sea-level pressure converted to inHg.
- Elevation in feet.
- Wind speed in mph and wind direction in degrees.
- Provider/source timestamps.

## Local Testing

Run the service tests from the repository root:

```bash
docker compose run --rm storage pytest tests/test_ballistics_service.py tests/test_ballistics_routing_config.py -q
```

The full repository test suite also covers the renderer's ballistics routes and saved-calculation storage behavior:

```bash
docker compose run --rm storage pytest -q
```
