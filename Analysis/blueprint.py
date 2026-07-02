from __future__ import annotations

from flask import Blueprint, Response, current_app, jsonify, redirect, render_template, request, session, url_for

from .job_store import target_image_path
from .marksmanship import InvalidAnalysisInput
from .schemas import ALLOWED_DISTANCES, DISTANCE_UNITS
from .service import AnalysisError, analyze_processed_target, process_uploaded_target

analysis_bp = Blueprint(
    "analysis",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/static",
)


@analysis_bp.before_request
def require_login():
    if session.get("token"):
        return None
    if (
        request.path.startswith("/analysis/process")
        or request.path.startswith("/analysis/jobs")
        or request.accept_mimetypes.best == "application/json"
    ):
        return jsonify({"error": {"message": "Sign in to use analysis."}}), 401
    return redirect(url_for("login", next=request.path))


@analysis_bp.get("")
@analysis_bp.get("/")
def page():
    return render_template(
        "analysis.html",
        distances=ALLOWED_DISTANCES,
        distance_units=DISTANCE_UNITS,
    )


@analysis_bp.post("/process")
def process_target():
    try:
        upload = request.files.get("target_photo")
        if not upload or not upload.filename:
            raise InvalidAnalysisInput("Choose an image to analyze.")
        payload = process_uploaded_target(
            upload,
            request.form.get("description", "").strip(),
            request.form.get("distance_value"),
            request.form.get("distance_unit"),
            current_app.config,
        )
        return jsonify(payload)
    except (AnalysisError, InvalidAnalysisInput) as error:
        return jsonify({"error": {"message": str(error)}}), getattr(error, "status_code", 400)


@analysis_bp.post("/jobs/<analysis_id>/analyze")
def analyze_target(analysis_id):
    try:
        return jsonify({"analysis": analyze_processed_target(analysis_id, current_app.config)})
    except (AnalysisError, InvalidAnalysisInput, FileNotFoundError) as error:
        status_code = getattr(error, "status_code", 404 if isinstance(error, FileNotFoundError) else 400)
        return jsonify({"error": {"message": str(error)}}), status_code


@analysis_bp.get("/jobs/<analysis_id>/target.png")
def target_image(analysis_id):
    path = target_image_path(current_app.config["ANALYSIS_JOB_DIR"], analysis_id)
    if not path.exists():
        return Response(status=404)
    return Response(
        path.read_bytes(),
        mimetype="image/png",
        headers={"Cache-Control": "no-store"},
    )
