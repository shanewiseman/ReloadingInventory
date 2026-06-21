from __future__ import annotations

import json
import os
from decimal import Decimal, InvalidOperation
from functools import wraps

import requests
from flask import Flask, Response, flash, redirect, render_template, request, send_file, session, url_for


CORE_RECIPE_COMPONENT_ROLES = {"BULLET", "POWDER", "PRIMER", "CASE"}


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
                session["token_expires_at"] = data.get("expires_at")
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
                "item_id", "manufacturer_lot", "acquired_on", "quantity", "unit", "notes"
            )
            data["active"] = bool(request.form.get("active"))
            data["replace_active"] = request.form.get("replace_active") == "true"
            api_data("POST", "/api/inventory-lots", json=data)
            flash("Inventory lot created.", "success")
            return redirect(url_for("inventory"))
        historical = request.args.get("historical", "false")
        lots = api_data("GET", "/api/inventory-lots", params={"historical": historical})["lots"]
        item_records = [
            item for item in api_data("GET", "/api/items", params={"archived": "false"})["items"]
            if item["category"] != "COMPLETED CARTRIDGE"
        ]
        active_item_ids = {
            lot["item_id"] for lot in api_data(
                "GET", "/api/inventory-lots", params={"historical": "true"}
            )["lots"] if lot["active"] and not lot["depleted"]
        }
        return render_template(
            "inventory.html",
            lots=lots,
            inventory_groups=inventory_lot_groups(lots),
            items=item_records,
            historical=historical,
            active_item_ids=active_item_ids,
        )

    @app.post("/inventory/<int:lot_id>/activate")
    @login_required
    def activate_lot(lot_id):
        api_data("PATCH", f"/api/inventory-lots/{lot_id}", json={"active": True})
        flash("Active consumption lot updated.", "success")
        return redirect(url_for("inventory"))

    @app.post("/inventory/<int:lot_id>/adjust")
    @login_required
    def adjust_inventory_lot(lot_id):
        data = form_payload("quantity_change", "reason", "notes")
        data["deplete_remaining"] = bool(request.form.get("deplete_remaining"))
        api_data("POST", f"/api/inventory-lots/{lot_id}/adjustments", json=data)
        flash("Inventory adjustment recorded.", "success")
        return redirect(url_for("inventory", historical=request.form.get("historical", "false")))

    @app.route("/recipes", methods=["GET", "POST"])
    @login_required
    def recipes():
        if request.method == "POST":
            data = form_payload(
                "title", "cartridge", "overall_length", "case_length", "crimp_type",
                "seating_depth", "source_notes", "notes", "public_notes",
                "suggested_title",
            )
            data["acknowledge_responsibility"] = bool(request.form.get("acknowledge_responsibility"))
            created = api_data("POST", "/api/recipes", json=data)["recipe"]
            flash("Recipe created. Add its exact components and source material.", "success")
            return redirect(url_for("recipe_detail", recipe_id=created["id"]))
        retired = request.args.get("retired", "false")
        records = api_data("GET", "/api/recipes")["recipes"]
        if retired != "true":
            records = [recipe for recipe in records if recipe["state"] != "RETIRED"]
        suggested_identity = api_data("GET", "/api/recipes/suggested-identity")["identity"]
        return render_template(
            "recipes.html",
            recipes=records,
            retired=retired,
            suggested_identity=suggested_identity,
        )

    @app.get("/recipes/<recipe_id>")
    @login_required
    def recipe_detail(recipe_id):
        recipe = api_data("GET", f"/api/recipes/{recipe_id}")["recipe"]
        item_records = api_data("GET", "/api/items")["items"]
        return render_template(
            "recipe_detail.html",
            recipe=recipe,
            items=item_records,
            component_items=recipe_component_item_options(recipe, item_records),
            garmin_performance_series=recipe_garmin_performance_series(recipe),
            component_form_open=request.args.get("component_form") == "open",
        )

    @app.post("/recipes/<recipe_id>/components")
    @login_required
    def add_recipe_component(recipe_id):
        result = api_data("POST", f"/api/recipes/{recipe_id}/components", json=form_payload(
            "item_id", "quantity", "unit",
        ))
        flash("Recipe component added.", "success")
        missing_components = any(
            warning.endswith(" component is missing.")
            for warning in result.get("warnings", [])
        )
        if missing_components:
            return redirect(url_for(
                "recipe_detail", recipe_id=recipe_id,
                component_form="open", _anchor="add-component",
            ))
        return redirect(url_for("recipe_detail", recipe_id=recipe_id, _anchor="components"))

    @app.post("/recipes/<recipe_id>/sources")
    @login_required
    def add_recipe_source(recipe_id):
        upload = request.files.get("source_file")
        if upload and upload.filename:
            data = form_payload("kind", "citation", "url", "page", "notes")
            files = {
                "source_file": (
                    upload.filename,
                    upload.stream,
                    upload.mimetype or "application/octet-stream",
                )
            }
            api_data("POST", f"/api/recipes/{recipe_id}/sources", data=data, files=files)
        else:
            api_data("POST", f"/api/recipes/{recipe_id}/sources", json=form_payload(
                "kind", "citation", "url", "page", "notes",
            ))
        flash("Source material added.", "success")
        return redirect(url_for("recipe_detail", recipe_id=recipe_id))

    @app.post("/recipes/<recipe_id>/state")
    @login_required
    def recipe_state(recipe_id):
        api_data("POST", f"/api/recipes/{recipe_id}/transition", json={
            "state": request.form["state"],
            "acknowledge_missing_source": bool(request.form.get("acknowledge_missing_source")),
        })
        flash("Recipe state changed.", "success")
        return redirect(url_for("recipe_detail", recipe_id=recipe_id))

    @app.post("/recipes/<recipe_id>/sharing")
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
        depleted = request.args.get("depleted", "false")
        records = api_data("GET", "/api/batches")["batches"]
        if depleted != "true":
            records = [batch for batch in records if batch["state"] != "DEPLETED"]
        return render_template("batches.html", batches=records, depleted=depleted)

    @app.route("/batches/new", methods=["GET", "POST"])
    @login_required
    def new_batch():
        recipes_data = api_data("GET", "/api/recipes")["recipes"]
        recipe_id = request.values.get("recipe_id")
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
                allocations = recipe_allocations(recipe, request.form)
            created = api_data("POST", "/api/batches", json={
                "recipe_id": recipe_id, "iterations": request.form.get("iterations"),
                "allocations": allocations, "notes": request.form.get("notes"),
                "acknowledge_non_approved": bool(request.form.get("acknowledge_non_approved")),
                "acknowledge_missing_source": bool(request.form.get("acknowledge_missing_source")),
            })["batch"]
            flash("Batch created and inventory reserved.", "success")
            return redirect(url_for("batch_detail", batch_id=created["id"]))
        return render_template("batch_new.html", recipes=recipes_data, recipe=recipe, lots=lots)

    @app.get("/batches/<batch_id>")
    @login_required
    def batch_detail(batch_id):
        batch = api_data("GET", f"/api/batches/{batch_id}")["batch"]
        lots = api_data("GET", "/api/inventory-lots", params={"historical": "true"})["lots"]
        containers_data = api_data("GET", "/api/containers")["containers"]
        return render_template("batch_detail.html", batch=batch, lots=lots, containers=containers_data)

    @app.post("/batches/<batch_id>/state")
    @login_required
    def batch_state(batch_id):
        api_data("POST", f"/api/batches/{batch_id}/transition", json={"state": request.form["state"]})
        flash("Batch state changed.", "success")
        return redirect(url_for("batch_detail", batch_id=batch_id))

    @app.post("/batches/<batch_id>/returns")
    @login_required
    def batch_return(batch_id):
        api_data("POST", f"/api/batches/{batch_id}/returns", json=form_payload(
            "source_lot_id", "destination_lot_id", "quantity_returned", "quantity_lost", "reason", "notes",
        ))
        flash("Inventory return/loss recorded.", "success")
        return redirect(url_for("batch_detail", batch_id=batch_id))

    @app.post("/batches/<batch_id>/performance")
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

    @app.post("/batches/<batch_id>/garmin-import")
    @login_required
    def import_garmin_data(batch_id):
        uploads = [upload for upload in request.files.getlist("files") if upload and upload.filename]
        if not uploads:
            flash("Choose one or more Garmin FIT files to import.", "error")
            return redirect(url_for("batch_detail", batch_id=batch_id))
        files = [
            ("files", (upload.filename, upload.stream, upload.mimetype or "application/octet-stream"))
            for upload in uploads
        ]
        result = api_data("POST", f"/api/batches/{batch_id}/performance/garmin-import", files=files)
        performance = result["performance"]
        flash(
            f"Imported Garmin data from {len(result['files'])} file(s); {performance['shot_count']} shots.",
            "success",
        )
        return redirect(url_for("batch_detail", batch_id=batch_id, _anchor="performance"))

    @app.route("/containers", methods=["GET", "POST"])
    @login_required
    def containers():
        if request.method == "POST":
            api_data(
                "POST", "/api/containers",
                json=form_payload("identifier", "name", "cartridge_limit", "description", "notes"),
            )
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

    @app.post("/containers/<int:container_id>/state")
    @login_required
    def container_state(container_id):
        api_data("PATCH", f"/api/containers/{container_id}", json={"state": request.form["state"]})
        flash("Container state changed.", "success")
        return redirect(url_for("containers", _anchor=f"container-{container_id}"))

    @app.get("/audit")
    @login_required
    def audit():
        records = api_data("GET", "/api/audit", params={"limit": 200})["audit"]
        return render_template("audit.html", audit=records)

    @app.get("/settings")
    @login_required
    def settings():
        files = api_data("GET", "/api/files")["files"]
        return render_template(
            "settings.html",
            api_token=session.get("token", ""),
            token_expires_at=session.get("token_expires_at"),
            files=files,
        )

    @app.post("/settings/files/<int:file_id>/delete")
    @login_required
    def delete_file(file_id):
        api_data("DELETE", f"/api/files/{file_id}")
        flash("Stored file removed.", "success")
        return redirect(url_for("settings", _anchor="stored-files"))

    @app.post("/settings/backup")
    @login_required
    def create_backup():
        result = api_data("POST", "/api/admin/backup")["backup"]
        flash(f"Backup created: {result['filename']}", "success")
        return redirect(url_for("settings"))

    @app.get("/download/help/llm-context")
    @login_required
    def download_llm_context():
        return send_file(
            os.path.join(app.root_path, "help", "llm_context.txt"),
            mimetype="text/plain",
            as_attachment=True,
            download_name="reload-ledger-llm-context.txt",
        )

    @app.get("/qr/<entity_type>/<entity_id>")
    @login_required
    def qr_page(entity_type, entity_id):
        if entity_type == "recipe":
            back_url = url_for("recipe_detail", recipe_id=entity_id)
            title = "Recipe QR label"
        elif entity_type == "batch":
            back_url = url_for("batch_detail", batch_id=entity_id)
            title = "Batch QR label"
        else:
            raise ApiError("Unable to generate QR code", {}, 404)
        return render_template(
            "qr.html",
            entity_type=entity_type,
            entity_id=entity_id,
            title=title,
            back_url=back_url,
        )

    @app.get("/download/qr/<entity_type>/<entity_id>")
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

    @app.get("/download/files/<int:file_id>")
    @login_required
    def download_file(file_id):
        response = api("GET", f"/api/files/{file_id}/download")
        if not response.ok:
            raise ApiError("Unable to download stored file", {}, response.status_code)
        return Response(
            response.content,
            mimetype=response.headers.get("Content-Type"),
            headers={"Content-Disposition": response.headers.get("Content-Disposition", "attachment")},
        )

    return app


class ApiError(Exception):
    def __init__(self, message, details, status):
        self.message, self.details, self.status = message, details, status
        super().__init__(message)


def form_payload(*fields):
    return {field: request.form.get(field) for field in fields}


def inventory_lot_groups(lots):
    groups = []
    groups_by_item = {}
    for lot in lots:
        item = lot.get("item") or {}
        item_key = lot.get("item_id") or item.get("id") or (
            item.get("manufacturer"),
            item.get("name"),
            item.get("category"),
        )
        group = groups_by_item.get(item_key)
        if group is None:
            group = {
                "item": item,
                "lots": [],
                "lot_count": 0,
                "available_quantity": Decimal("0"),
                "reserved_quantity": Decimal("0"),
                "consumed_quantity": Decimal("0"),
                "normalized_unit": lot.get("normalized_unit") or "",
            }
            groups_by_item[item_key] = group
            groups.append(group)

        group["lots"].append(lot)
        group["lot_count"] += 1
        group["available_quantity"] += decimal_quantity(lot.get("available_quantity"))
        group["reserved_quantity"] += decimal_quantity(lot.get("reserved_quantity"))
        group["consumed_quantity"] += decimal_quantity(lot.get("consumed_quantity"))
        if lot.get("normalized_unit") and lot.get("normalized_unit") != group["normalized_unit"]:
            group["normalized_unit"] = "mixed units"

    for group in groups:
        for field in ("available_quantity", "reserved_quantity", "consumed_quantity"):
            group[field] = display_quantity(group[field])
    return groups


def decimal_quantity(value):
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def display_quantity(value):
    if value == value.to_integral_value():
        return str(value.quantize(Decimal("1")))
    return format(value.normalize(), "f")


def recipe_component_item_options(recipe, items):
    used_core_roles = {
        str(component.get("role", "")).upper()
        for component in recipe.get("components", [])
        if str(component.get("role", "")).upper() in CORE_RECIPE_COMPONENT_ROLES
    }
    return [
        item for item in items
        if str(item.get("category", "")).upper() not in used_core_roles
        or str(item.get("category", "")).upper() == "OTHER"
    ]


def recipe_allocations(recipe, form):
    try:
        iterations = int(form.get("iterations", ""))
    except (TypeError, ValueError):
        return []
    if iterations <= 0:
        return []

    allocations = []
    for component in recipe["components"]:
        lot_id = form.get(f"component_{component['id']}_lot")
        if not lot_id:
            continue
        try:
            quantity = Decimal(str(component["quantity"])) * iterations
        except (InvalidOperation, TypeError, ValueError):
            continue
        allocations.append({
            "component_id": component["id"],
            "lot_id": lot_id,
            "quantity": format(quantity, "f"),
        })
    return allocations


def recipe_garmin_performance_series(recipe):
    records = recipe.get("aggregate_performance", {}).get("records", [])
    series = []
    for record in records:
        processed = record.get("processed_data") or {}
        if processed.get("chronograph") != "Garmin Xero C1 Pro":
            continue
        shots = [
            {
                "shot": int(shot.get("sequence") or index + 1),
                "speed": float(shot["velocity_fps"]),
            }
            for index, shot in enumerate(processed.get("shots") or [])
            if shot.get("velocity_fps") is not None
        ]
        if not shots:
            continue
        date_label = record.get("recorded_on") or str(processed.get("recorded_on_source") or "")[:10] or "Undated"
        batch_id = record.get("batch_id") or "batch"
        series.append({
            "id": f"{batch_id}-{len(series)}",
            "batch_id": batch_id,
            "date": date_label,
            "label": f"{date_label} · {batch_id}",
            "shots": shots,
        })
    return series


def format_details(details):
    if not details:
        return ""
    return " ".join(f"{key}: {value}" for key, value in details.items() if value)
