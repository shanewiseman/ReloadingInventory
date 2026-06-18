from __future__ import annotations

import json
import os
from functools import wraps

import requests
from flask import Flask, Response, flash, redirect, render_template, request, session, url_for


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY", "development-renderer-secret"),
        STORAGE_URL=os.getenv("STORAGE_URL", "http://localhost:5001").rstrip("/"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
        PERMANENT_SESSION_LIFETIME=12 * 60 * 60,
    )
    if test_config:
        app.config.update(test_config)

    def api(method, path, **kwargs):
        headers = kwargs.pop("headers", {})
        if session.get("token"):
            headers["Authorization"] = f"Bearer {session['token']}"
        try:
            response = requests.request(
                method, f"{app.config['STORAGE_URL']}{path}", headers=headers, timeout=15, **kwargs
            )
        except requests.RequestException as exc:
            raise RuntimeError("Storage service is unavailable") from exc
        if response.status_code == 401 and session.get("token"):
            session.clear()
        return response

    def api_data(method, path, **kwargs):
        response = api(method, path, **kwargs)
        data = response.json() if response.content else {}
        if not response.ok:
            error = data.get("error", {})
            raise ApiError(error.get("message", "Request failed"), error.get("details", {}), response.status_code)
        return data

    def login_required(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not session.get("token"):
                return redirect(url_for("login", next=request.path))
            return view(*args, **kwargs)
        return wrapper

    @app.context_processor
    def template_context():
        return {"current_user": session.get("user")}

    @app.errorhandler(ApiError)
    def api_error(error):
        if error.status == 401:
            return redirect(url_for("login"))
        flash(f"{error.message} {format_details(error.details)}".strip(), "error")
        return redirect(request.referrer or url_for("dashboard"))

    @app.errorhandler(RuntimeError)
    def service_error(error):
        return render_template("error.html", message=str(error)), 503

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            response = api("POST", "/api/auth/login", json={
                "email": request.form.get("email"), "password": request.form.get("password"),
            })
            data = response.json()
            if response.ok:
                session.permanent = True
                session["token"], session["user"] = data["token"], data["user"]
                return redirect(request.args.get("next") or url_for("dashboard"))
            error = data.get("error", {})
            if error.get("code") == "password_reset_required":
                return redirect(url_for("reset_password", email=request.form.get("email")))
            flash(error.get("message", "Login failed"), "error")
        return render_template("auth.html", mode="login")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            try:
                api_data("POST", "/api/auth/register", json={
                    "email": request.form.get("email"), "password": request.form.get("password"),
                    "display_name": request.form.get("display_name"),
                })
                flash("Account created. Sign in to continue.", "success")
                return redirect(url_for("login"))
            except ApiError as error:
                flash(f"{error.message} {format_details(error.details)}", "error")
        return render_template("auth.html", mode="register")

    @app.route("/reset-password", methods=["GET", "POST"])
    def reset_password():
        if request.method == "POST":
            try:
                api_data("POST", "/api/auth/reset", json={
                    "email": request.form.get("email"), "new_password": request.form.get("new_password"),
                })
                flash("Password reset. Sign in with the new password.", "success")
                return redirect(url_for("login"))
            except ApiError as error:
                flash(error.message, "error")
        return render_template("auth.html", mode="reset", email=request.args.get("email", ""))

    @app.post("/logout")
    def logout():
        if session.get("token"):
            api("POST", "/api/auth/logout")
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    @login_required
    def dashboard():
        metrics = api_data("GET", "/api/dashboard")["metrics"]
        return render_template("dashboard.html", metrics=metrics)

    @app.route("/items", methods=["GET", "POST"])
    @login_required
    def items():
        if request.method == "POST":
            api_data("POST", "/api/items", json=form_payload(
                "category", "manufacturer", "product_line", "name", "characteristics",
                "caliber", "bullet_weight", "bullet_type", "primer_type", "powder_type", "attributes", "notes",
            ))
            flash("Item created.", "success")
            return redirect(url_for("items"))
        params = {"q": request.args.get("q", ""), "category": request.args.get("category", ""),
                  "archived": request.args.get("archived", "false")}
        records = api_data("GET", "/api/items", params=params)["items"]
        return render_template("items.html", items=records)

    @app.post("/items/<int:item_id>/archive")
    @login_required
    def archive_item(item_id):
        api_data("PATCH", f"/api/items/{item_id}", json={"archived": True})
        flash("Item archived.", "success")
        return redirect(url_for("items"))

    @app.route("/inventory", methods=["GET", "POST"])
    @login_required
    def inventory():
        if request.method == "POST":
            data = form_payload(
                "item_id", "manufacturer_lot", "acquired_on", "opened_on", "quantity", "unit", "notes"
            )
            data["active"] = bool(request.form.get("active"))
            api_data("POST", "/api/inventory-lots", json=data)
            flash("Inventory lot created.", "success")
            return redirect(url_for("inventory"))
        historical = request.args.get("historical", "false")
        lots = api_data("GET", "/api/inventory-lots", params={"historical": historical})["lots"]
        item_records = api_data("GET", "/api/items")["items"]
        return render_template("inventory.html", lots=lots, items=item_records, historical=historical)

    @app.post("/inventory/<int:lot_id>/activate")
    @login_required
    def activate_lot(lot_id):
        api_data("PATCH", f"/api/inventory-lots/{lot_id}", json={"active": True})
        flash("Active consumption lot updated.", "success")
        return redirect(url_for("inventory"))

    @app.route("/recipes", methods=["GET", "POST"])
    @login_required
    def recipes():
        if request.method == "POST":
            data = form_payload(
                "title", "cartridge", "overall_length", "case_length", "crimp_type",
                "seating_depth", "source_notes", "notes", "public_notes",
            )
            data["acknowledge_responsibility"] = bool(request.form.get("acknowledge_responsibility"))
            created = api_data("POST", "/api/recipes", json=data)["recipe"]
            flash("Recipe created. Add its exact components and source material.", "success")
            return redirect(url_for("recipe_detail", recipe_id=created["id"]))
        records = api_data("GET", "/api/recipes")["recipes"]
        return render_template("recipes.html", recipes=records)

    @app.get("/recipes/<int:recipe_id>")
    @login_required
    def recipe_detail(recipe_id):
        recipe = api_data("GET", f"/api/recipes/{recipe_id}")["recipe"]
        item_records = api_data("GET", "/api/items")["items"]
        return render_template("recipe_detail.html", recipe=recipe, items=item_records)

    @app.post("/recipes/<int:recipe_id>/components")
    @login_required
    def add_recipe_component(recipe_id):
        api_data("POST", f"/api/recipes/{recipe_id}/components", json=form_payload(
            "item_id", "role", "quantity", "unit", "alternative_group",
        ))
        flash("Recipe component added.", "success")
        return redirect(url_for("recipe_detail", recipe_id=recipe_id))

    @app.post("/recipes/<int:recipe_id>/sources")
    @login_required
    def add_recipe_source(recipe_id):
        api_data("POST", f"/api/recipes/{recipe_id}/sources", json=form_payload(
            "kind", "citation", "url", "page", "file_name", "notes",
        ))
        flash("Source material added.", "success")
        return redirect(url_for("recipe_detail", recipe_id=recipe_id))

    @app.post("/recipes/<int:recipe_id>/state")
    @login_required
    def recipe_state(recipe_id):
        api_data("POST", f"/api/recipes/{recipe_id}/transition", json={"state": request.form["state"]})
        flash("Recipe state changed.", "success")
        return redirect(url_for("recipe_detail", recipe_id=recipe_id))

    @app.post("/recipes/<int:recipe_id>/sharing")
    @login_required
    def recipe_sharing(recipe_id):
        api_data("PATCH", f"/api/recipes/{recipe_id}", json={"public": request.form.get("public") == "true"})
        flash("Recipe sharing updated.", "success")
        return redirect(url_for("recipe_detail", recipe_id=recipe_id))

    @app.get("/public/recipes/<token>")
    def public_recipe(token):
        response = api("GET", f"/api/public/recipes/{token}")
        if response.status_code == 404:
            return render_template("error.html", message="Public recipe not found."), 404
        return render_template("public_recipe.html", recipe=response.json()["recipe"])

    @app.get("/batches")
    @login_required
    def batches():
        records = api_data("GET", "/api/batches")["batches"]
        return render_template("batches.html", batches=records)

    @app.route("/batches/new", methods=["GET", "POST"])
    @login_required
    def new_batch():
        recipes_data = api_data("GET", "/api/recipes")["recipes"]
        recipe_id = request.values.get("recipe_id", type=int)
        recipe = next((record for record in recipes_data if record["id"] == recipe_id), None)
        lots = api_data("GET", "/api/inventory-lots")["lots"]
        if request.method == "POST":
            allocations = []
            if request.form.get("advanced_allocations"):
                try:
                    allocations = json.loads(request.form["advanced_allocations"])
                except json.JSONDecodeError:
                    flash("Advanced allocations must be valid JSON.", "error")
                    return redirect(url_for("new_batch", recipe_id=recipe_id))
            elif recipe:
                for component in recipe["components"]:
                    lot_id = request.form.get(f"component_{component['id']}_lot")
                    quantity = request.form.get(f"component_{component['id']}_quantity")
                    selected = request.form.get(f"component_{component['id']}_selected")
                    if lot_id and quantity and (not component["alternative_group"] or selected):
                        allocations.append({"component_id": component["id"], "lot_id": lot_id, "quantity": quantity})
            created = api_data("POST", "/api/batches", json={
                "recipe_id": recipe_id, "iterations": request.form.get("iterations"),
                "allocations": allocations, "notes": request.form.get("notes"),
                "acknowledge_non_approved": bool(request.form.get("acknowledge_non_approved")),
            })["batch"]
            flash("Batch created and inventory reserved.", "success")
            return redirect(url_for("batch_detail", batch_id=created["id"]))
        return render_template("batch_new.html", recipes=recipes_data, recipe=recipe, lots=lots)

    @app.get("/batches/<int:batch_id>")
    @login_required
    def batch_detail(batch_id):
        batch = api_data("GET", f"/api/batches/{batch_id}")["batch"]
        lots = api_data("GET", "/api/inventory-lots", params={"historical": "true"})["lots"]
        containers_data = api_data("GET", "/api/containers")["containers"]
        return render_template("batch_detail.html", batch=batch, lots=lots, containers=containers_data)

    @app.post("/batches/<int:batch_id>/state")
    @login_required
    def batch_state(batch_id):
        api_data("POST", f"/api/batches/{batch_id}/transition", json={"state": request.form["state"]})
        flash("Batch state changed.", "success")
        return redirect(url_for("batch_detail", batch_id=batch_id))

    @app.post("/batches/<int:batch_id>/returns")
    @login_required
    def batch_return(batch_id):
        api_data("POST", f"/api/batches/{batch_id}/returns", json=form_payload(
            "source_lot_id", "destination_lot_id", "quantity_returned", "quantity_lost", "reason", "notes",
        ))
        flash("Inventory return/loss recorded.", "success")
        return redirect(url_for("batch_detail", batch_id=batch_id))

    @app.post("/batches/<int:batch_id>/performance")
    @login_required
    def save_performance(batch_id):
        api_data("PUT", f"/api/batches/{batch_id}/performance", json=form_payload(
            "recorded_on", "firearm", "barrel_length", "distance", "group_size", "shot_count",
            "velocity_average", "velocity_minimum", "velocity_maximum", "standard_deviation",
            "extreme_spread", "temperature", "weather_notes", "reliability_notes",
            "pressure_sign_notes", "recoil_perception", "accuracy_perception",
            "cleanliness_perception", "subjective_rating", "notes", "raw_data", "processed_data",
        ))
        flash("Performance record saved.", "success")
        return redirect(url_for("batch_detail", batch_id=batch_id))

    @app.route("/containers", methods=["GET", "POST"])
    @login_required
    def containers():
        if request.method == "POST":
            api_data("POST", "/api/containers", json=form_payload("identifier", "name", "description", "notes"))
            flash("Container created.", "success")
            return redirect(url_for("containers"))
        records = api_data("GET", "/api/containers")["containers"]
        batch_records = api_data("GET", "/api/batches")["batches"]
        return render_template("containers.html", containers=records, batches=batch_records)

    @app.post("/containers/<int:container_id>/assign")
    @login_required
    def assign_container(container_id):
        data = form_payload("batch_id", "quantity")
        data["acknowledge_mixed_batch"] = bool(request.form.get("acknowledge_mixed_batch"))
        api_data("POST", f"/api/containers/{container_id}/assignments", json=data)
        flash("Batch assigned to container.", "success")
        return redirect(url_for("containers"))

    @app.get("/audit")
    @login_required
    def audit():
        records = api_data("GET", "/api/audit", params={"limit": 200})["audit"]
        return render_template("audit.html", audit=records)

    @app.get("/settings")
    @login_required
    def settings():
        return render_template("settings.html")

    @app.post("/settings/backup")
    @login_required
    def create_backup():
        result = api_data("POST", "/api/admin/backup")["backup"]
        flash(f"Backup created: {result['filename']}", "success")
        return redirect(url_for("settings"))

    @app.get("/download/qr/<entity_type>/<int:entity_id>")
    @login_required
    def download_qr(entity_type, entity_id):
        response = api("GET", f"/api/qr/{entity_type}/{entity_id}")
        if not response.ok:
            raise ApiError("Unable to generate QR code", {}, response.status_code)
        return Response(response.content, mimetype="image/png",
                        headers={"Content-Disposition": response.headers.get("Content-Disposition", "attachment")})

    @app.get("/download/export/<entity>/<output_format>")
    @login_required
    def download_export(entity, output_format):
        response = api("GET", f"/api/export/{entity}", params={"format": output_format})
        if not response.ok:
            raise ApiError("Unable to export data", {}, response.status_code)
        return Response(response.content, mimetype=response.headers.get("Content-Type"),
                        headers={"Content-Disposition": response.headers.get("Content-Disposition", "attachment")})

    return app


class ApiError(Exception):
    def __init__(self, message, details, status):
        self.message, self.details, self.status = message, details, status
        super().__init__(message)


def form_payload(*fields):
    return {field: request.form.get(field) for field in fields}


def format_details(details):
    if not details:
        return ""
    return " ".join(f"{key}: {value}" for key, value in details.items() if value)
