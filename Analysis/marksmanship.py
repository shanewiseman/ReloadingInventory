from __future__ import annotations

import math

from .schemas import ALLOWED_DISTANCES, DISTANCE_UNITS, SHOT_EXCLUSION_RADIUS_INCHES

METERS_TO_YARDS = 1.0936132983
INCHES_PER_MOA_AT_100_YARDS = 1.047


class InvalidAnalysisInput(ValueError):
    pass


def normalize_distance(value, unit):
    try:
        distance_value = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidAnalysisInput("Choose a valid distance.") from exc

    if distance_value not in ALLOWED_DISTANCES:
        raise InvalidAnalysisInput("Choose one of the supported distances.")
    if unit not in DISTANCE_UNITS:
        raise InvalidAnalysisInput("Choose yards or meters.")

    yards = distance_value if unit == "yards" else distance_value * METERS_TO_YARDS
    return {
        "value": distance_value,
        "unit": unit,
        "yards_normalized": round(yards, 4),
    }


def distance_from_center(x_inches, y_inches):
    return math.hypot(float(x_inches), float(y_inches))


def moa_for_inches(size_inches, distance_yards):
    distance_yards = float(distance_yards)
    if distance_yards <= 0:
        return None
    return float(size_inches) / (distance_yards * INCHES_PER_MOA_AT_100_YARDS / 100.0)


def prepare_shots(raw_shots, radius_inches=SHOT_EXCLUSION_RADIUS_INCHES):
    included = []
    excluded = []

    for index, raw in enumerate(raw_shots or [], start=1):
        shot_id = int(raw.get("shot_id") or index)
        x_inches = float(raw.get("x_inches", 0))
        y_inches = float(raw.get("y_inches", 0))
        center_distance = distance_from_center(x_inches, y_inches)
        record = {
            "shot_id": shot_id,
            "x_inches": round(x_inches, 4),
            "y_inches": round(y_inches, 4),
            "distance_from_center_inches": round(center_distance, 4),
            "confidence": clamp_confidence(raw.get("confidence", 0)),
            "source_pixel": {
                "x": round(float(raw.get("x_pixel", 0)), 2),
                "y": round(float(raw.get("y_pixel", 0)), 2),
            },
        }
        if center_distance > radius_inches:
            record["included"] = False
            record["reason"] = "outside_6_inch_target_radius"
            excluded.append(record)
        else:
            record["included"] = True
            included.append(record)

    return included, excluded


def group_statistics(included_shots, distance_yards):
    shot_count = len(included_shots)
    center_x = (
        sum(shot["x_inches"] for shot in included_shots) / shot_count
        if shot_count else 0.0
    )
    center_y = (
        sum(shot["y_inches"] for shot in included_shots) / shot_count
        if shot_count else 0.0
    )
    offset_inches = distance_from_center(center_x, center_y)
    extreme_spread = extreme_spread_inches(included_shots)

    return {
        "shot_count": shot_count,
        "extreme_spread_inches_center_to_center": round(extreme_spread, 4),
        "moa": round_or_none(moa_for_inches(extreme_spread, distance_yards)),
        "center_x_inches": round(center_x, 4),
        "center_y_inches": round(center_y, 4),
        "distance_from_bullseye_inches": round(offset_inches, 4),
        "distance_from_bullseye_moa": round_or_none(moa_for_inches(offset_inches, distance_yards)),
    }


def extreme_spread_inches(shots):
    if len(shots) < 2:
        return 0.0

    largest = 0.0
    for index, first in enumerate(shots):
        for second in shots[index + 1:]:
            distance = math.hypot(
                first["x_inches"] - second["x_inches"],
                first["y_inches"] - second["y_inches"],
            )
            largest = max(largest, distance)
    return largest


def aggregate_confidence(detection_confidence, verification_confidence, included_shots):
    values = [clamp_confidence(detection_confidence)]
    if verification_confidence is not None:
        values.append(clamp_confidence(verification_confidence))
    if included_shots:
        values.append(
            sum(clamp_confidence(shot.get("confidence", 0)) for shot in included_shots)
            / len(included_shots)
        )
    return round(sum(values) / len(values), 3)


def clamp_confidence(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, number))


def round_or_none(value, digits=4):
    if value is None:
        return None
    return round(value, digits)
