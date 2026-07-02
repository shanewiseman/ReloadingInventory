from io import BytesIO
from pathlib import Path

from PIL import Image

from Analysis.marksmanship import group_statistics, normalize_distance, prepare_shots
from Analysis.service import AnalysisProcessingError, parse_response_json
from Analysis.target_render import render_target
from rendering_app.app import create_app


def authenticated_client(app):
    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["token"] = "test-token"
        flask_session["user"] = {"email": "test@example.com"}
    return client


def test_prepare_shots_excludes_centers_outside_six_inches():
    included, excluded = prepare_shots([
        {"shot_id": 1, "x_inches": 6, "y_inches": 0, "confidence": 0.9},
        {"shot_id": 2, "x_inches": 6.01, "y_inches": 0, "confidence": 0.8},
    ])

    assert [shot["shot_id"] for shot in included] == [1]
    assert [shot["shot_id"] for shot in excluded] == [2]
    assert excluded[0]["reason"] == "outside_6_inch_target_radius"


def test_group_statistics_uses_center_to_center_moa():
    distance = normalize_distance(100, "yards")
    group = group_statistics([
        {"shot_id": 1, "x_inches": 0, "y_inches": 0, "confidence": 1},
        {"shot_id": 2, "x_inches": 1.047, "y_inches": 0, "confidence": 1},
    ], distance["yards_normalized"])

    assert group["extreme_spread_inches_center_to_center"] == 1.047
    assert group["moa"] == 1.0
    assert group["center_x_inches"] == 0.5235


def test_normalize_distance_supports_meters():
    distance = normalize_distance(100, "meters")

    assert distance["value"] == 100
    assert distance["unit"] == "meters"
    assert distance["yards_normalized"] == 109.3613


def test_render_target_creates_reference_png_with_shot_dot():
    content = render_target([{"shot_id": 1, "x_inches": 1, "y_inches": 1}])
    image = Image.open(BytesIO(content))

    assert image.format == "PNG"
    assert image.size == (1200, 1200)
    assert image.getpixel((600, 600))[0] > 200


class FakeContent:
    def __init__(self, content_type, text=None, refusal=None):
        self.type = content_type
        self.text = text
        self.refusal = refusal


class FakeOutput:
    def __init__(self, output_type, content=None):
        self.type = output_type
        self.content = content or []


class FakeResponse:
    def __init__(self, output_text="", status="completed", output=None, incomplete_details=None):
        self.output_text = output_text
        self.status = status
        self.output = output or []
        self.incomplete_details = incomplete_details
        self.error = None


def test_parse_response_json_falls_back_to_message_text():
    response = FakeResponse(output=[
        FakeOutput("message", [FakeContent("output_text", text='{"shots": []}')])
    ])

    assert parse_response_json(response) == {"shots": []}


def test_parse_response_json_reports_incomplete_context():
    response = FakeResponse(status="incomplete", incomplete_details={"reason": "max_output_tokens"})

    try:
        parse_response_json(response)
    except AnalysisProcessingError as error:
        assert "status=incomplete" in str(error)
        assert "max_output_tokens" in str(error)
    else:
        raise AssertionError("Expected AnalysisProcessingError")


def test_analysis_page_renders_distance_and_unit_controls():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    client = authenticated_client(app)

    response = client.get("/analysis")

    assert response.status_code == 200
    assert b'<option value="5"' in response.data
    assert b'<option value="200"' in response.data
    assert b'<option value="yards">' in response.data
    assert b'<option value="meters">' in response.data
    assert b'/analysis/static/analysis.css?v=1' in response.data
    assert b'/analysis/static/analysis.js?v=1' in response.data


def test_analysis_process_requires_login_with_json_response():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    response = app.test_client().post("/analysis/process")

    assert response.status_code == 401
    assert response.json["error"]["message"] == "Sign in to use analysis."


def test_analysis_script_captures_form_data_before_disabling_file_input():
    script = Path("Analysis/static/analysis.js").read_text()

    assert script.index("const formData = new FormData(form);") < script.index("setBusy(true);")
    assert 'body: formData' in script
    assert 'headers: { Accept: "application/json" }' in script
    assert "Analysis failed before the server returned details." in script


def test_analysis_process_route_uses_feature_service(monkeypatch, tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test",
        "ANALYSIS_JOB_DIR": str(tmp_path),
    })
    client = authenticated_client(app)
    calls = []

    def fake_process(upload, description, distance_value, distance_unit, config):
        calls.append({
            "filename": upload.filename,
            "description": description,
            "distance_value": distance_value,
            "distance_unit": distance_unit,
            "job_dir": config["ANALYSIS_JOB_DIR"],
        })
        return {
            "analysis_id": "analysis-1",
            "status": "processed",
            "target_image_url": "/analysis/jobs/analysis-1/target.png",
            "detected_shot_count": 2,
            "excluded_shot_count": 0,
            "warnings": [],
        }

    monkeypatch.setattr("Analysis.blueprint.process_uploaded_target", fake_process)

    response = client.post("/analysis/process", data={
        "target_photo": (BytesIO(b"image"), "target.jpg"),
        "description": "standing unsupported",
        "distance_value": "50",
        "distance_unit": "yards",
    })

    assert response.status_code == 200
    assert response.json["analysis_id"] == "analysis-1"
    assert calls == [{
        "filename": "target.jpg",
        "description": "standing unsupported",
        "distance_value": "50",
        "distance_unit": "yards",
        "job_dir": str(tmp_path),
    }]


def test_analysis_analyze_route_returns_structured_result(monkeypatch, tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test",
        "ANALYSIS_JOB_DIR": str(tmp_path),
    })
    client = authenticated_client(app)

    def fake_analyze(analysis_id, config):
        return {
            "analysis_id": analysis_id,
            "distance": {"value": 100, "unit": "yards", "yards_normalized": 100},
            "shots": [],
            "excluded_shots": [],
            "group": {"shot_count": 0},
            "confidence": 0.4,
            "warnings": ["Low-confidence analysis."],
        }

    monkeypatch.setattr("Analysis.blueprint.analyze_processed_target", fake_analyze)

    response = client.post("/analysis/jobs/analysis-1/analyze")

    assert response.status_code == 200
    assert response.json["analysis"]["analysis_id"] == "analysis-1"
    assert response.json["analysis"]["confidence"] == 0.4
