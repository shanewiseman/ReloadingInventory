from __future__ import annotations

import base64
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from .job_store import cleanup_old_jobs, create_job_dir, load_job, save_job, save_target_image
from .marksmanship import (
    InvalidAnalysisInput,
    aggregate_confidence,
    group_statistics,
    normalize_distance,
    prepare_shots,
)
from .prompts import (
    DETECTION_INSTRUCTIONS,
    VERIFICATION_INSTRUCTIONS,
    detection_prompt,
    verification_prompt,
)
from .schemas import DETECTION_RESPONSE_SCHEMA, VERIFICATION_RESPONSE_SCHEMA
from .target_render import render_target


class AnalysisError(Exception):
    status_code = 400


class AnalysisConfigurationError(AnalysisError):
    status_code = 503


class AnalysisProcessingError(AnalysisError):
    status_code = 502


@dataclass
class NormalizedImage:
    content: bytes
    width: int
    height: int
    media_type: str = "image/jpeg"


def process_uploaded_target(upload, description, distance_value, distance_unit, config):
    distance = normalize_distance(distance_value, distance_unit)
    max_bytes = int(config.get("ANALYSIS_MAX_IMAGE_BYTES", 12 * 1024 * 1024))
    image = normalize_image(upload.read(), max_bytes)

    job_root = config["ANALYSIS_JOB_DIR"]
    cleanup_old_jobs(job_root, config.get("ANALYSIS_JOB_TTL_SECONDS", 3600))

    detection = detect_shots_with_openai(image, description, distance, config)
    included, excluded = prepare_shots(detection.get("shots", []))
    target_bytes = render_target(included)

    analysis_id = str(uuid.uuid4())
    create_job_dir(job_root, analysis_id)
    job = {
        "analysis_id": analysis_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "processed",
        "description": description or "",
        "distance": distance,
        "source_image": {
            "filename": getattr(upload, "filename", "") or "target-photo",
            "content_type": getattr(upload, "mimetype", "") or image.media_type,
            "normalized_width": image.width,
            "normalized_height": image.height,
        },
        "detection": detection,
        "shots": included,
        "excluded_shots": excluded,
        "corrections": {
            "available": True,
            "applied": False,
            "shots": None,
        },
    }
    save_target_image(job_root, analysis_id, target_bytes)
    save_job(job_root, job)

    return {
        "analysis_id": analysis_id,
        "status": job["status"],
        "target_image_url": f"/analysis/jobs/{analysis_id}/target.png",
        "detected_shot_count": len(included),
        "excluded_shot_count": len(excluded),
        "warnings": detection.get("warnings", []),
    }


def analyze_processed_target(analysis_id, config):
    job_root = config["ANALYSIS_JOB_DIR"]
    job = load_job(job_root, analysis_id)
    if job.get("analysis"):
        return job["analysis"]

    preliminary_group = group_statistics(
        job.get("shots", []),
        job["distance"]["yards_normalized"],
    )
    verification = verify_analysis_with_openai(job, preliminary_group, config)
    analysis = build_analysis_result(job, preliminary_group, verification)
    job["analysis"] = analysis
    job["status"] = "complete"
    save_job(job_root, job)
    return analysis


def build_analysis_result(job, preliminary_group, verification):
    detection = job.get("detection") or {}
    included = job.get("shots") or []
    confidence = aggregate_confidence(
        detection.get("confidence", 0),
        (verification or {}).get("confidence"),
        included,
    )
    warnings = []
    warnings.extend(detection.get("warnings") or [])
    warnings.extend((verification or {}).get("warnings") or [])
    if job.get("excluded_shots"):
        warnings.append("One or more detected shots were outside the 6 inch target radius and were excluded.")
    if len(included) < 2:
        warnings.append("Fewer than two included shots were detected, so group size is limited.")
    if confidence < 0.75:
        warnings.append("Low-confidence analysis. Review the detected shot placement before relying on the result.")

    return {
        "analysis_id": job["analysis_id"],
        "distance": job["distance"],
        "description": job.get("description", ""),
        "shots": included,
        "excluded_shots": job.get("excluded_shots", []),
        "group": preliminary_group,
        "confidence": confidence,
        "warnings": dedupe(warnings),
        "model_review": verification,
        "corrections": job.get("corrections"),
    }


def normalize_image(content, max_bytes):
    if not content:
        raise InvalidAnalysisInput("Choose an image to analyze.")
    if len(content) > max_bytes:
        raise InvalidAnalysisInput("Image is too large for analysis.")

    try:
        image = Image.open(BytesIO(content))
        image = ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidAnalysisInput("Choose a valid image file.") from exc

    image.thumbnail((2400, 2400))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=92, optimize=True)
    return NormalizedImage(buffer.getvalue(), image.width, image.height)


def detect_shots_with_openai(image, description, distance, config):
    prompt = detection_prompt(
        description,
        distance["value"],
        distance["unit"],
        image.width,
        image.height,
    )
    response = create_openai_response(
        config,
        instructions=DETECTION_INSTRUCTIONS,
        prompt=prompt,
        images=[
            image_data_url(image.content, image.media_type),
            image_data_url(render_target([]), "image/png"),
        ],
        schema_name="target_detection",
        schema=DETECTION_RESPONSE_SCHEMA,
        max_output_tokens=int(config.get("ANALYSIS_DETECTION_MAX_OUTPUT_TOKENS", 6000)),
    )
    return parse_response_json(response)


def verify_analysis_with_openai(job, preliminary_group, config):
    prompt = verification_prompt(job, preliminary_group)
    with open(os.path.join(config["ANALYSIS_JOB_DIR"], job["analysis_id"], "target.png"), "rb") as image_file:
        target_image = image_file.read()
    response = create_openai_response(
        config,
        instructions=VERIFICATION_INSTRUCTIONS,
        prompt=prompt,
        images=[image_data_url(target_image, "image/png")],
        schema_name="target_analysis_review",
        schema=VERIFICATION_RESPONSE_SCHEMA,
        max_output_tokens=int(config.get("ANALYSIS_REVIEW_MAX_OUTPUT_TOKENS", 3000)),
    )
    return parse_response_json(response)


def create_openai_response(config, instructions, prompt, images, schema_name, schema, max_output_tokens):
    api_key = config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise AnalysisConfigurationError("OpenAI API key is not configured.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise AnalysisConfigurationError("The OpenAI Python SDK is not installed.") from exc

    client = OpenAI(api_key=api_key, timeout=float(config.get("ANALYSIS_OPENAI_TIMEOUT_SECONDS", 90)))
    content = [{"type": "input_text", "text": prompt}]
    for image_url in images:
        content.append({"type": "input_image", "image_url": image_url, "detail": "original"})

    try:
        request_payload = {
            "model": config.get("ANALYSIS_OPENAI_MODEL", "gpt-5.5"),
            "instructions": instructions,
            "input": [{"role": "user", "content": content}],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                }
            },
            "max_output_tokens": max_output_tokens,
            "store": False,
        }
        reasoning_effort = config.get("ANALYSIS_REASONING_EFFORT", "medium")
        if reasoning_effort:
            request_payload["reasoning"] = {"effort": reasoning_effort}
        return client.responses.create(**request_payload)
    except Exception as exc:
        raise AnalysisProcessingError(f"OpenAI analysis failed: {exc}") from exc


def parse_response_json(response):
    output_text = getattr(response, "output_text", None) or extract_response_text(response)
    if not output_text:
        raise AnalysisProcessingError(f"OpenAI returned no structured output ({response_summary(response)}).")
    try:
        return json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise AnalysisProcessingError("OpenAI returned invalid structured output.") from exc


def extract_response_text(response):
    texts = []
    for output in getattr(response, "output", []) or []:
        if getattr(output, "type", None) != "message":
            continue
        for content in getattr(output, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                texts.append(text)
    return "".join(texts)


def response_summary(response):
    parts = [f"status={getattr(response, 'status', 'unknown')}"]
    error = getattr(response, "error", None)
    if error:
        parts.append(f"error={safe_model_value(error)}")
    incomplete = getattr(response, "incomplete_details", None)
    if incomplete:
        parts.append(f"incomplete={safe_model_value(incomplete)}")

    output_parts = []
    refusals = []
    for output in getattr(response, "output", []) or []:
        output_type = getattr(output, "type", "unknown")
        if output_type != "message":
            output_parts.append(output_type)
            continue
        content_types = []
        for content in getattr(output, "content", []) or []:
            content_type = getattr(content, "type", "unknown")
            content_types.append(content_type)
            refusal = getattr(content, "refusal", None)
            if refusal:
                refusals.append(str(refusal))
        output_parts.append(f"message:{','.join(content_types) or 'empty'}")
    if output_parts:
        parts.append(f"output={';'.join(output_parts)}")
    if refusals:
        parts.append(f"refusal={'; '.join(refusals)[:180]}")
    return "; ".join(parts)


def safe_model_value(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True)
    return str(value)


def image_data_url(content, media_type):
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def dedupe(values):
    seen = set()
    result = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
