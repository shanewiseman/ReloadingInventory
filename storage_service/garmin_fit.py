from __future__ import annotations

import math
import struct
from datetime import datetime, timedelta, timezone
from decimal import Decimal


FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)
MPS_TO_FPS = Decimal("3.280839895013123")
THOUSAND = Decimal("1000")

BASE_TYPES = {
    0: ("enum", 1, "B", 0xFF),
    1: ("sint8", 1, "b", 0x7F),
    2: ("uint8", 1, "B", 0xFF),
    3: ("sint16", 2, "h", 0x7FFF),
    4: ("uint16", 2, "H", 0xFFFF),
    5: ("sint32", 4, "i", 0x7FFFFFFF),
    6: ("uint32", 4, "I", 0xFFFFFFFF),
    7: ("string", 1, None, None),
    8: ("float32", 4, "f", None),
    9: ("float64", 8, "d", None),
    10: ("uint8z", 1, "B", 0),
    11: ("uint16z", 2, "H", 0),
    12: ("uint32z", 4, "I", 0),
    13: ("byte", 1, "B", None),
    14: ("sint64", 8, "q", 0x7FFFFFFFFFFFFFFF),
    15: ("uint64", 8, "Q", 0xFFFFFFFFFFFFFFFF),
    16: ("uint64z", 8, "Q", 0),
}


class FitParseError(ValueError):
    pass


def parse_xero_c1_fit(content, filename=""):
    messages = parse_fit_messages(content)
    file_id = {}
    device = {}
    summaries = []
    shots = []

    for message in messages:
        values = message["values"]
        if message["global"] == 0:
            file_id = {
                "type": values.get(0),
                "manufacturer": values.get(1),
                "product": values.get(2),
                "serial_number": values.get(3),
                "time_created": fit_datetime(values.get(4)),
            }
        elif message["global"] == 23:
            device = {
                "manufacturer": values.get(2),
                "product": values.get(4),
                "serial_number": values.get(3),
                "software_version": scaled(values.get(5), Decimal("100")),
            }
        elif message["global"] == 387:
            summaries.append(
                {
                    "timestamp": fit_datetime(values.get(253)),
                    "velocity_minimum_mps": scaled(values.get(0), THOUSAND),
                    "velocity_maximum_mps": scaled(values.get(1), THOUSAND),
                    "velocity_average_mps": scaled(values.get(2), THOUSAND),
                    "shot_count": values.get(3),
                    "velocity_unit": values.get(4),
                    "projectile_weight_gr": scaled(values.get(5), Decimal("10")),
                    "standard_deviation_mps": scaled(values.get(6), THOUSAND),
                }
            )
        elif message["global"] == 388:
            velocity_mps = scaled(values.get(0), THOUSAND)
            if velocity_mps is None:
                continue
            shots.append(
                {
                    "timestamp": fit_datetime(values.get(253)),
                    "velocity_mps": velocity_mps,
                    "source_shot_number": values.get(1),
                }
            )

    if not shots:
        raise FitParseError(f"{filename or 'FIT file'} does not contain Garmin shot velocity data")

    shots.sort(key=lambda shot: (shot["timestamp"] or datetime.max.replace(tzinfo=timezone.utc), shot["source_shot_number"] or 0))
    started_at = next((shot["timestamp"] for shot in shots if shot["timestamp"]), None)
    finished_at = next((shot["timestamp"] for shot in reversed(shots) if shot["timestamp"]), None)
    summary = summaries[0] if summaries else {}
    return {
        "filename": filename,
        "file_id": serialize_datetimes(file_id),
        "device": serialize_datetimes(device),
        "summary": serialize_datetimes(summary),
        "started_at": started_at,
        "finished_at": finished_at,
        "projectile_weight_gr": summary.get("projectile_weight_gr"),
        "shots": shots,
    }


def parse_fit_messages(content):
    data = bytes(content)
    if len(data) < 14:
        raise FitParseError("FIT file is too small")
    header_size = data[0]
    if header_size not in (12, 14) or len(data) < header_size:
        raise FitParseError("FIT header is invalid")
    if data[8:12] != b".FIT":
        raise FitParseError("File is not a FIT activity file")
    data_size = struct.unpack_from("<I", data, 4)[0]
    start = header_size
    end = start + data_size
    if end > len(data):
        raise FitParseError("FIT data section is truncated")

    definitions = {}
    messages = []
    position = start
    while position < end:
        header = data[position]
        position += 1
        if header & 0x80:
            raise FitParseError("Compressed FIT timestamp records are not supported for Garmin shot imports")
        local_type = header & 0x0F
        is_definition = bool(header & 0x40)
        has_developer_fields = bool(header & 0x20)
        if is_definition:
            if position + 5 > end:
                raise FitParseError("FIT message definition is truncated")
            position += 1  # reserved byte
            architecture = data[position]
            position += 1
            endian = ">" if architecture == 1 else "<"
            global_message = struct.unpack_from(endian + "H", data, position)[0]
            position += 2
            field_count = data[position]
            position += 1
            fields = []
            for _ in range(field_count):
                if position + 3 > end:
                    raise FitParseError("FIT field definition is truncated")
                fields.append(
                    {
                        "number": data[position],
                        "size": data[position + 1],
                        "base_type": data[position + 2],
                    }
                )
                position += 3
            developer_fields = []
            if has_developer_fields:
                developer_field_count = data[position]
                position += 1
                for _ in range(developer_field_count):
                    if position + 3 > end:
                        raise FitParseError("FIT developer field definition is truncated")
                    developer_fields.append({"size": data[position + 1]})
                    position += 3
            definitions[local_type] = {
                "global": global_message,
                "endian": endian,
                "fields": fields,
                "developer_fields": developer_fields,
            }
            continue

        definition = definitions.get(local_type)
        if not definition:
            raise FitParseError("FIT data record references an unknown local message definition")
        values = {}
        for field in definition["fields"]:
            size = field["size"]
            if position + size > end:
                raise FitParseError("FIT data record is truncated")
            raw = data[position:position + size]
            position += size
            values[field["number"]] = decode_value(raw, field["base_type"], definition["endian"])
        for developer_field in definition["developer_fields"]:
            position += developer_field["size"]
            if position > end:
                raise FitParseError("FIT developer data record is truncated")
        messages.append({"global": definition["global"], "values": values})
    return messages


def decode_value(raw, base_type, endian):
    type_number = base_type & 0x1F
    name, unit_size, fmt, invalid = BASE_TYPES.get(type_number, ("unknown", 1, None, None))
    if name == "string":
        return raw.split(b"\x00", 1)[0].decode("utf-8", "replace")
    if fmt is None or len(raw) % unit_size:
        return raw.hex()
    count = len(raw) // unit_size
    values = list(struct.unpack(endian + fmt * count, raw))
    result = [None if invalid is not None and value == invalid else value for value in values]
    return result[0] if len(result) == 1 else result


def fit_datetime(value):
    if value in (None, 0):
        return None
    return FIT_EPOCH + timedelta(seconds=int(value))


def scaled(value, divisor):
    if value is None:
        return None
    return Decimal(str(value)) / divisor


def serialize_datetimes(value):
    if isinstance(value, dict):
        return {key: serialize_datetimes(item) for key, item in value.items()}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def combine_xero_c1_sessions(parsed_files, stored_files, imported_at):
    file_pairs = list(zip(parsed_files, stored_files))
    file_pairs.sort(
        key=lambda pair: (
            pair[0]["started_at"]
            or pair[0]["finished_at"]
            or datetime.max.replace(tzinfo=timezone.utc),
            pair[0]["filename"],
        )
    )

    shots = []
    source_files = []
    for parsed, stored_file in file_pairs:
        source_files.append(
            {
                "id": stored_file.id,
                "filename": stored_file.original_filename,
                "sha256": stored_file.sha256,
                "size_bytes": stored_file.size_bytes,
                "started_at": parsed["started_at"].isoformat() if parsed["started_at"] else None,
                "finished_at": parsed["finished_at"].isoformat() if parsed["finished_at"] else None,
                "shot_count": len(parsed["shots"]),
                "device": parsed["device"],
                "file_id": parsed["file_id"],
                "summary": parsed["summary"],
            }
        )
        for shot in parsed["shots"]:
            velocity_fps = shot["velocity_mps"] * MPS_TO_FPS
            shots.append(
                {
                    "sequence": len(shots) + 1,
                    "source_file_id": stored_file.id,
                    "source_filename": stored_file.original_filename,
                    "source_shot_number": shot["source_shot_number"],
                    "timestamp": shot["timestamp"].isoformat() if shot["timestamp"] else None,
                    "velocity_mps": quantize(shot["velocity_mps"]),
                    "velocity_fps": quantize(velocity_fps),
                }
            )

    velocities = [Decimal(str(shot["velocity_fps"])) for shot in shots]
    average = sum(velocities) / len(velocities)
    minimum = min(velocities)
    maximum = max(velocities)
    variance = sum((velocity - average) ** 2 for velocity in velocities) / len(velocities)
    standard_deviation = Decimal(str(math.sqrt(float(variance))))
    earliest = min(
        (
            parsed["started_at"]
            for parsed in parsed_files
            if parsed["started_at"] is not None
        ),
        default=None,
    )
    projectile_weights = [
        parsed["projectile_weight_gr"]
        for parsed in parsed_files
        if parsed["projectile_weight_gr"] is not None
    ]

    raw_data = format_raw_garmin_data(source_files, shots)
    return {
        "recorded_on": earliest.date().isoformat() if earliest else None,
        "shot_count": len(shots),
        "velocity_average": quantize(average),
        "velocity_minimum": quantize(minimum),
        "velocity_maximum": quantize(maximum),
        "standard_deviation": quantize(standard_deviation),
        "extreme_spread": quantize(maximum - minimum),
        "raw_data": raw_data,
        "processed_data": {
            "chronograph": "Garmin Xero C1 Pro",
            "imported_at": imported_at.isoformat(),
            "velocity_unit": "fps",
            "recorded_on_source": earliest.isoformat() if earliest else None,
            "projectile_weight_gr": quantize(projectile_weights[0]) if projectile_weights else None,
            "source_files": source_files,
            "summary": {
                "shot_count": len(shots),
                "velocity_average_fps": quantize(average),
                "velocity_minimum_fps": quantize(minimum),
                "velocity_maximum_fps": quantize(maximum),
                "standard_deviation_fps": quantize(standard_deviation),
                "extreme_spread_fps": quantize(maximum - minimum),
            },
            "shots": shots,
        },
    }


def quantize(value):
    if value is None:
        return None
    return float(Decimal(str(value)).quantize(Decimal("0.001")))


def format_raw_garmin_data(source_files, shots):
    lines = ["Garmin Xero C1 Pro import"]
    for source_file in source_files:
        lines.append(
            "Source file "
            f"{source_file['id']}: {source_file['filename']} "
            f"({source_file['shot_count']} shots)"
        )
    lines.append("")
    lines.append("Shot list")
    for shot in shots:
        timestamp = f" at {shot['timestamp']}" if shot["timestamp"] else ""
        source = f", {shot['source_filename']}"
        lines.append(
            f"{shot['sequence']}. {shot['velocity_fps']:.3f} fps "
            f"({shot['velocity_mps']:.3f} m/s{source}{timestamp})"
        )
    return "\n".join(lines)
