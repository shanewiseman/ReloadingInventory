ALLOWED_DISTANCES = (5, 15, 25, 50, 100, 125, 150, 175, 200)
DISTANCE_UNITS = ("yards", "meters")
SHOT_EXCLUSION_RADIUS_INCHES = 6.0


DETECTION_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "target_center": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "x_pixel": {"type": "number"},
                "y_pixel": {"type": "number"},
                "confidence": {"type": "number"},
            },
            "required": ["x_pixel", "y_pixel", "confidence"],
        },
        "scale": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "inches_per_ring": {"type": "number"},
                "pixels_per_inch": {"type": "number"},
                "confidence": {"type": "number"},
                "notes": {"type": "string"},
            },
            "required": ["inches_per_ring", "pixels_per_inch", "confidence", "notes"],
        },
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "shot_id": {"type": "integer"},
                    "x_pixel": {"type": "number"},
                    "y_pixel": {"type": "number"},
                    "x_inches": {"type": "number"},
                    "y_inches": {"type": "number"},
                    "confidence": {"type": "number"},
                },
                "required": [
                    "shot_id",
                    "x_pixel",
                    "y_pixel",
                    "x_inches",
                    "y_inches",
                    "confidence",
                ],
            },
        },
        "confidence": {"type": "number"},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
    "required": ["target_center", "scale", "shots", "confidence", "warnings", "notes"],
}


VERIFICATION_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "measurement_notes": {"type": "string"},
        "confidence": {"type": "number"},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "suggested_corrections": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "shot_id": {"type": "integer"},
                    "x_inches": {"type": "number"},
                    "y_inches": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["shot_id", "x_inches", "y_inches", "reason"],
            },
        },
    },
    "required": [
        "summary",
        "measurement_notes",
        "confidence",
        "warnings",
        "suggested_corrections",
    ],
}
