from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request
from jinja2 import Undefined
from PIL import UnidentifiedImageError

from .escpos import (
    ALIGN_CENTER,
    ALIGN_LEFT,
    BOLD_OFF,
    BOLD_ON,
    build_document,
    command_text,
    image_bytes,
    image_from_bytes,
    qr_image,
    send_tcp_print_job,
)


EVENT_TEMPLATES = {
    "batch_created": ("batch_created.txt", "Batch Created"),
    "batch_produced": ("batch_produced.txt", "Batch Produced"),
}


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        POS_PRINT_DRY_RUN=env_bool("POS_PRINT_DRY_RUN"),
        DRY_RUN_JOB_LIMIT=int(os.getenv("DRY_RUN_JOB_LIMIT", "100")),
        PRINTER_HOST=os.getenv("PRINTER_HOST", ""),
        PRINTER_PORT=int(os.getenv("PRINTER_PORT", "9100")),
        PRINTER_TIMEOUT_SECONDS=float(os.getenv("PRINTER_TIMEOUT_SECONDS", "5")),
        PRINT_WIDTH_CHARS=int(os.getenv("PRINT_WIDTH_CHARS", "42")),
        PRINT_IMAGE_WIDTH_PX=int(os.getenv("PRINT_IMAGE_WIDTH_PX", "576")),
        LOGO_PATH=os.getenv("LOGO_PATH", ""),
    )
    if test_config:
        app.config.update(test_config)
    app.print_jobs = []
    app.print_job_sequence = 0

    @app.template_filter("value")
    def value_filter(value, fallback="N/A"):
        if isinstance(value, Undefined) or value in (None, ""):
            return fallback
        return value

    @app.template_filter("number")
    def number_filter(value, fallback="N/A"):
        if isinstance(value, Undefined) or value in (None, ""):
            return fallback
        try:
            return f"{float(value):g}"
        except (TypeError, ValueError):
            return value

    @app.template_filter("money")
    def money_filter(value, fallback="N/A"):
        if isinstance(value, Undefined) or value in (None, ""):
            return fallback
        try:
            return f"${float(value):.4f}"
        except (TypeError, ValueError):
            return value

    @app.get("/health")
    def health():
        return jsonify(
            status="ok",
            mode="dry_run" if app.config["POS_PRINT_DRY_RUN"] else "printer",
            printer_host_configured=bool(app.config["PRINTER_HOST"]),
        )

    @app.post("/print/batch-created")
    def print_batch_created():
        return print_event(app, "batch_created")

    @app.post("/print/batch-produced")
    def print_batch_produced():
        return print_event(app, "batch_produced")

    @app.post("/print/test")
    def print_test():
        data = json_payload()
        try:
            document = render_test_document(app, data)
        except ValueError as error:
            return jsonify(error={"message": str(error)}), 400
        return send_document_response(app, document, event="test", payload=data)

    @app.get("/print/jobs")
    def list_print_jobs():
        return jsonify(mode="dry_run" if app.config["POS_PRINT_DRY_RUN"] else "printer", jobs=app.print_jobs)

    @app.delete("/print/jobs")
    def clear_print_jobs():
        app.print_jobs.clear()
        return jsonify(status="cleared")

    return app


def json_payload():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def print_event(app, event):
    data = json_payload()
    try:
        document = render_event_document(app, event, data)
    except ValueError as error:
        return jsonify(error={"message": str(error)}), 400
    return send_document_response(app, document, event=event, payload=data)


def send_document_response(app, document, event=None, payload=None):
    if app.config["POS_PRINT_DRY_RUN"]:
        job = record_dry_run_job(app, document, event=event, payload=payload)
        return jsonify(status="accepted", mode="dry_run", bytes=len(document), job_id=job["id"])
    try:
        send_to_printer(app, document)
    except Exception as error:
        app.logger.exception("POS print failed")
        return jsonify(error={"message": str(error)}), 502
    job = record_dry_run_job(app, document, event=event, payload=payload)
    return jsonify(status="printed", mode="printer", bytes=len(document), job_id=job["id"])


def record_dry_run_job(app, document, event=None, payload=None):
    app.print_job_sequence += 1
    batch = payload.get("batch") if isinstance(payload, dict) else None
    urls = payload.get("urls") if isinstance(payload, dict) else None
    recipe = batch.get("recipe") if isinstance(batch, dict) and isinstance(batch.get("recipe"), dict) else {}
    recipe_id = recipe.get("id") if isinstance(recipe, dict) else None
    if isinstance(batch, dict) and not recipe_id:
        recipe_id = batch.get("recipe_id")
    job = {
        "id": app.print_job_sequence,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "bytes": len(document),
        "sha256": hashlib.sha256(document).hexdigest(),
        "batch_id": batch.get("id") if isinstance(batch, dict) else None,
        "batch_slug": batch.get("slug") if isinstance(batch, dict) else None,
        "recipe_id": recipe_id,
        "company": payload.get("company") if isinstance(payload, dict) else None,
        "urls": urls if isinstance(urls, dict) else {},
    }
    app.print_jobs.append(job)
    limit = int(app.config["DRY_RUN_JOB_LIMIT"] or 0)
    if limit > 0:
        del app.print_jobs[:-limit]
    return job


def send_to_printer(app, document):
    send_tcp_print_job(
        app.config["PRINTER_HOST"],
        app.config["PRINTER_PORT"],
        document,
        timeout=app.config["PRINTER_TIMEOUT_SECONDS"],
    )


def render_event_document(app, event, data):
    if event not in EVENT_TEMPLATES:
        raise ValueError("Unknown print event")
    batch = data.get("batch")
    if not isinstance(batch, dict):
        raise ValueError("batch object is required")
    template_name, title = EVENT_TEMPLATES[event]
    urls = data.get("urls") if isinstance(data.get("urls"), dict) else {}
    company = data.get("company") or "Wiseman Precision Cartridges"
    receipt = render_template(
        template_name,
        company=company,
        title=title,
        batch=batch,
        urls=urls,
        generated_at=data.get("generated_at") or datetime.now(timezone.utc).isoformat(),
    )
    return receipt_document(
        app,
        company=company,
        title=title,
        body=receipt,
        urls=urls,
        logo=load_logo(app, data.get("logo")),
    )


def render_test_document(app, data):
    text = data.get("text") or ""
    if not text and not data.get("image"):
        raise ValueError("text or image is required")
    parts = [ALIGN_CENTER, BOLD_ON, command_text("Wiseman Precision Cartridges", app.config["PRINT_WIDTH_CHARS"]), BOLD_OFF]
    parts.extend([command_text("Printer Test", app.config["PRINT_WIDTH_CHARS"]), ALIGN_LEFT])
    if text:
        parts.append(command_text(text, app.config["PRINT_WIDTH_CHARS"]))
    image = load_logo(app, data.get("image"), allow_fallback=False)
    if image:
        parts.extend([ALIGN_CENTER, image_bytes(image, app.config["PRINT_IMAGE_WIDTH_PX"]), ALIGN_LEFT])
    return build_document(parts)


def receipt_document(app, company, title, body, urls, logo=None):
    parts = [ALIGN_CENTER]
    if logo:
        parts.append(image_bytes(logo, app.config["PRINT_IMAGE_WIDTH_PX"]))
    parts.extend([
        BOLD_ON,
        command_text(company, app.config["PRINT_WIDTH_CHARS"]),
        command_text(title, app.config["PRINT_WIDTH_CHARS"]),
        BOLD_OFF,
        ALIGN_LEFT,
        command_text(body, app.config["PRINT_WIDTH_CHARS"]),
    ])
    if urls.get("batch"):
        parts.extend([
            ALIGN_CENTER,
            command_text("Batch QR", app.config["PRINT_WIDTH_CHARS"]),
            image_bytes(qr_image(urls["batch"]), app.config["PRINT_IMAGE_WIDTH_PX"]),
        ])
    if urls.get("recipe"):
        parts.extend([
            ALIGN_CENTER,
            command_text("Recipe QR", app.config["PRINT_WIDTH_CHARS"]),
            image_bytes(qr_image(urls["recipe"]), app.config["PRINT_IMAGE_WIDTH_PX"]),
        ])
    parts.append(ALIGN_LEFT)
    return build_document(parts)


def load_logo(app, logo_payload, allow_fallback=True):
    content = None
    if isinstance(logo_payload, dict) and logo_payload.get("base64"):
        try:
            content = base64.b64decode(logo_payload["base64"], validate=True)
        except (ValueError, TypeError):
            raise ValueError("logo image must be valid base64")
    elif isinstance(logo_payload, str):
        try:
            content = base64.b64decode(logo_payload, validate=True)
        except (ValueError, TypeError):
            raise ValueError("image must be valid base64")
    elif allow_fallback and app.config.get("LOGO_PATH"):
        path = app.config["LOGO_PATH"]
        if os.path.exists(path):
            with open(path, "rb") as source:
                content = source.read()
    if not content:
        return None
    try:
        image = image_from_bytes(content)
        if image.format != "PNG":
            raise ValueError("logo image must be a PNG")
        image.load()
        return image.copy()
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise ValueError("logo image must be a valid PNG")
