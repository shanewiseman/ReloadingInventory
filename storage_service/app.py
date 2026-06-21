from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import secrets
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import wraps

import qrcode
import click
from flask import Flask, Response, g, jsonify, request, send_file
from flask_migrate import Migrate
from sqlalchemy import func, or_
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from .domain import (
    BATCH_TRANSITIONS,
    CONTAINER_TRANSITIONS,
    MISSING_SOURCE_WARNING,
    RECIPE_TRANSITIONS,
    DomainError,
    acknowledge,
    as_decimal,
    audit,
    ensure_transition,
    make_slug,
    new_public_token,
    normalize_quantity,
    parse_json_object,
    recipe_warnings,
    snapshot,
    token_hash,
)
from .garmin_fit import FitParseError, combine_xero_c1_sessions, parse_xero_c1_fit
from .models import (
    AuditLog,
    AuthSession,
    Batch,
    BatchInventoryConsumption,
    BatchInventoryReservation,
    ContainerAssignment,
    InventoryLot,
    InventoryAdjustment,
    InventoryReturn,
    Item,
    PerformanceRecord,
    Recipe,
    RecipeComponent,
    SourceMaterial,
    StoredFile,
    StorageContainer,
    User,
    UserAcknowledgement,
    db,
    utcnow,
)

migrate = Migrate()
ITEM_CATEGORIES = {"BULLET", "POWDER", "PRIMER", "CASE", "COMPLETED CARTRIDGE", "OTHER"}
ITEM_CATEGORY_FIELDS = {
    "BULLET": {"caliber", "bullet_weight", "bullet_type"},
    "POWDER": {"powder_type"},
    "PRIMER": {"primer_type"},
    "CASE": {"caliber"},
    "COMPLETED CARTRIDGE": {"caliber"},
    "OTHER": set(),
}
RECIPE_STATES = set(RECIPE_TRANSITIONS)
CONTAINER_STATES = set(CONTAINER_TRANSITIONS)


def default_file_storage_dir(database_url):
    if database_url.startswith("sqlite:///"):
        database_path = database_url.removeprefix("sqlite:///")
        database_dir = os.path.dirname(database_path)
        if database_dir:
            return os.path.join(database_dir, "files")
    return "/tmp/reloading-files"


def create_app(test_config=None):
    app = Flask(__name__)
    database_url = os.getenv("DATABASE_URL", "sqlite:////tmp/reloading.sqlite3")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SECRET_KEY=os.getenv("SECRET_KEY", secrets.token_hex(32)),
        SESSION_HOURS=int(os.getenv("SESSION_HOURS", "12")),
        LOCAL_RESET_ENABLED=os.getenv("LOCAL_RESET_ENABLED", "true").lower() == "true",
        PUBLIC_BASE_URL=os.getenv("PUBLIC_BASE_URL", "http://localhost:8080").rstrip("/"),
        FILE_STORAGE_DIR=os.getenv("FILE_STORAGE_DIR", default_file_storage_dir(database_url)),
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    db.init_app(app)
    migrate.init_app(app, db)
    register_error_handlers(app)
    register_routes(app)
    register_commands(app)
    return app


def register_commands(app):
    @app.cli.command("mark-reset")
    @click.argument("email")
    def mark_reset(email):
        """Mark an account as requiring a local password reset."""
        user = User.query.filter_by(email=email.strip().lower()).first()
        if not user:
            raise click.ClickException("Account not found")
        user.reset_required = True
        AuthSession.query.filter_by(user_id=user.id, revoked_at=None).update({"revoked_at": utcnow()})
        audit(user.id, "User", user.id, "RESET_REQUIRED")
        db.session.commit()
        click.echo(f"Reset required for {user.email}")

    @app.cli.command("delete-user")
    @click.argument("email")
    def delete_user(email):
        """Delete one account and all tenant-scoped records for repeatable local tests."""
        user = User.query.filter_by(email=email.strip().lower()).first()
        if not user:
            click.echo(f"No account found for {email.strip().lower()}")
            return

        user_id = user.id
        for model in (
            UserAcknowledgement,
            AuditLog,
            StoredFile,
            ContainerAssignment,
            PerformanceRecord,
            InventoryReturn,
            BatchInventoryConsumption,
            BatchInventoryReservation,
            Batch,
            SourceMaterial,
            RecipeComponent,
            Recipe,
            InventoryAdjustment,
            InventoryLot,
            Item,
            AuthSession,
        ):
            model.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        db.session.delete(user)
        db.session.commit()
        click.echo(f"Deleted account and tenant data for {user.email}")


def register_error_handlers(app):
    @app.errorhandler(DomainError)
    def handle_domain_error(error):
        return jsonify(error={"code": error.code, "message": error.message, "details": error.details}), error.status

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify(error={"code": "not_found", "message": "Resource not found", "details": {}}), 404

    @app.errorhandler(405)
    def method_not_allowed(_error):
        return jsonify(error={"code": "method_not_allowed", "message": "Method not allowed", "details": {}}), 405


def payload():
    return request.get_json(silent=True) or {}


def require_fields(data, *fields):
    missing = {field: "required" for field in fields if data.get(field) in (None, "")}
    if missing:
        raise DomainError("validation_error", "Required fields are missing", missing)


def parse_date(value, field):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise DomainError("validation_error", f"{field} must use YYYY-MM-DD", {field: "invalid date"})


def owned(model, entity_id):
    record = db.session.get(model, entity_id)
    if not record or record.user_id != g.user.id:
        raise DomainError("not_found", "Resource not found", status=404)
    return record


def owned_recipe(identifier):
    record = Recipe.query.filter_by(identifier=str(identifier), user_id=g.user.id).first()
    if not record:
        raise DomainError("not_found", "Resource not found", status=404)
    return record


def owned_batch(identifier):
    record = Batch.query.filter_by(identifier=str(identifier), user_id=g.user.id).first()
    if not record:
        raise DomainError("not_found", "Resource not found", status=404)
    return record


def auth_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        token = header[7:] if header.startswith("Bearer ") else ""
        if not token:
            raise DomainError("authentication_required", "Authentication is required", status=401)
        session = AuthSession.query.filter_by(token_hash=token_hash(token), revoked_at=None).first()
        now = utcnow()
        if not session or session.expires_at.replace(tzinfo=timezone.utc) <= now:
            raise DomainError("session_expired", "Session has expired", status=401)
        user = db.session.get(User, session.user_id)
        if not user or not user.is_active:
            raise DomainError("authentication_required", "Account is unavailable", status=401)
        g.user, g.auth_session = user, session
        return view(*args, **kwargs)
    return wrapper


def num(value):
    return float(value) if value is not None else None


def edit_state(can_edit, reason=None):
    return {"can_edit": can_edit, "edit_lock_reason": None if can_edit else reason}


def item_edit_state(item):
    if InventoryLot.query.filter_by(user_id=item.user_id, item_id=item.id).first():
        return edit_state(False, "Inventory lots reference this item.")
    if RecipeComponent.query.filter_by(user_id=item.user_id, item_id=item.id).first():
        return edit_state(False, "Recipe components reference this item.")
    return edit_state(True)


def lot_edit_state(lot):
    if BatchInventoryReservation.query.filter_by(user_id=lot.user_id, inventory_lot_id=lot.id).first():
        return edit_state(False, "Batches reserve this inventory lot.")
    if BatchInventoryConsumption.query.filter_by(user_id=lot.user_id, inventory_lot_id=lot.id).first():
        return edit_state(False, "Batches consume this inventory lot.")
    if InventoryAdjustment.query.filter_by(user_id=lot.user_id, inventory_lot_id=lot.id).first():
        return edit_state(False, "Inventory adjustments reference this lot.")
    if InventoryReturn.query.filter(
        InventoryReturn.user_id == lot.user_id,
        or_(InventoryReturn.source_lot_id == lot.id, InventoryReturn.destination_lot_id == lot.id),
    ).first():
        return edit_state(False, "Inventory return/loss records reference this lot.")
    return edit_state(True)


def recipe_edit_state(recipe):
    if Batch.query.filter_by(user_id=recipe.user_id, recipe_id=recipe.id).first():
        return edit_state(False, "Batches reference this recipe.")
    return edit_state(True)


def batch_edit_state(batch):
    if ContainerAssignment.query.filter_by(user_id=batch.user_id, batch_id=batch.id).first():
        return edit_state(False, "Container assignments reference this batch.")
    if PerformanceRecord.query.filter_by(user_id=batch.user_id, batch_id=batch.id).first():
        return edit_state(False, "Performance data references this batch.")
    if InventoryReturn.query.filter_by(user_id=batch.user_id, batch_id=batch.id).first():
        return edit_state(False, "Inventory return/loss records reference this batch.")
    return edit_state(True)


def container_edit_state(container):
    if ContainerAssignment.query.filter_by(user_id=container.user_id, container_id=container.id).first():
        return edit_state(False, "Batch assignments reference this container.")
    return edit_state(True)


def ensure_editable(state):
    if not state["can_edit"]:
        raise DomainError("traceability_lock", state["edit_lock_reason"], status=409)


def item_json(item):
    result = {
        "id": item.id, "category": item.category, "manufacturer": item.manufacturer,
        "product_line": item.product_line, "name": item.name, "characteristics": item.characteristics,
        "caliber": item.caliber, "bullet_weight": num(item.bullet_weight), "bullet_type": item.bullet_type,
        "primer_type": item.primer_type, "powder_type": item.powder_type, "attributes": item.attributes or {},
        "notes": item.notes, "archived": item.archived, "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }
    result.update(item_edit_state(item))
    return result


def lot_json(lot):
    result = {
        "id": lot.id, "item_id": lot.item_id, "item": item_json(lot.item),
        "manufacturer_lot": lot.manufacturer_lot,
        "acquired_on": lot.acquired_on.isoformat() if lot.acquired_on else None,
        "opened_on": lot.opened_on.isoformat() if lot.opened_on else None,
        "original_quantity": num(lot.original_quantity), "original_unit": lot.original_unit,
        "normalized_quantity": num(lot.normalized_quantity), "normalized_unit": lot.normalized_unit,
        "adjustment_quantity": num(lot.adjustment_quantity),
        "available_quantity": num(lot.available_quantity), "reserved_quantity": num(lot.reserved_quantity),
        "consumed_quantity": num(lot.consumed_quantity), "active": lot.active,
        "depleted": lot.depleted, "notes": lot.notes,
    }
    result.update(lot_edit_state(lot))
    return result


def component_json(component, public=False):
    return {
        "id": component.id, "item_id": component.item_id, "role": component.role,
        "quantity": num(component.quantity), "unit": component.unit,
        "item": {
            "category": component.item.category, "manufacturer": component.item.manufacturer,
            "product_line": component.item.product_line, "name": component.item.name,
            "caliber": component.item.caliber, "bullet_weight": num(component.item.bullet_weight),
            "bullet_type": component.item.bullet_type, "primer_type": component.item.primer_type,
            "powder_type": component.item.powder_type,
        } if public else item_json(component.item),
    }


def source_json(source, public=False):
    result = {
        "id": source.id, "kind": source.kind, "citation": source.citation, "url": source.url,
        "page": source.page, "file_name": source.file_name, "notes": source.notes,
    }
    if not public:
        result.update(
            stored_file_id=source.stored_file_id,
            stored_file=stored_file_json(source.stored_file) if source.stored_file else None,
        )
    return result


def stored_file_json(record):
    return {
        "id": record.id,
        "original_filename": record.original_filename,
        "content_type": record.content_type,
        "size_bytes": record.size_bytes,
        "sha256": record.sha256,
        "purpose": record.purpose,
        "entity_type": record.entity_type,
        "entity_id": record.entity_id,
        "description": record.description,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


def recipe_json(recipe, public=False):
    result = {
        "id": recipe.identifier, "title": recipe.title, "state": recipe.state,
        "cartridge": recipe.cartridge, "overall_length": num(recipe.overall_length),
        "case_length": num(recipe.case_length), "crimp_type": recipe.crimp_type,
        "seating_depth": num(recipe.seating_depth), "public": recipe.public,
        "components": [component_json(c, public=public) for c in recipe.components],
        "sources": [source_json(s, public=public) for s in recipe.sources],
        "created_at": recipe.created_at.isoformat(), "updated_at": recipe.updated_at.isoformat(),
        "warnings": recipe_warnings(recipe),
    }
    if public:
        result["notes"] = recipe.public_notes
    else:
        result.update(
            source_notes=recipe.source_notes, notes=recipe.notes, public_notes=recipe.public_notes,
            public_token=recipe.public_token, archived=recipe.archived,
        )
        result.update(recipe_edit_state(recipe))
    return result


def batch_json(batch):
    container_assigned_quantity = db.session.query(
        func.coalesce(func.sum(ContainerAssignment.quantity), 0)
    ).filter_by(user_id=batch.user_id, batch_id=batch.id).scalar()
    container_assigned_quantity = int(container_assigned_quantity or 0)
    container_depleted_quantity = int(batch.container_depleted_quantity or 0)
    container_assignments = ContainerAssignment.query.filter_by(
        user_id=batch.user_id, batch_id=batch.id
    ).all()
    result = {
        "id": batch.identifier, "slug": batch.slug, "recipe_id": batch.recipe.identifier,
        "recipe": {
            "id": batch.recipe.identifier,
            "title": batch.recipe.title,
            "state": batch.recipe.state,
            "components": [component_json(component) for component in batch.recipe.components],
        },
        "iterations": batch.iterations, "state": batch.state,
        "characteristics": batch.characteristics, "notes": batch.notes, "locked": batch.locked,
        "reservations": [
            {
                "id": r.id, "lot_id": r.inventory_lot_id, "component_id": r.recipe_component_id,
                "quantity": num(r.quantity), "status": r.status,
                "item": r.inventory_lot.item.name, "lot": r.inventory_lot.manufacturer_lot,
            } for r in batch.reservations
        ],
        "consumptions": [
            {"id": c.id, "lot_id": c.inventory_lot_id, "component_id": c.recipe_component_id,
             "quantity": num(c.quantity), "item": c.inventory_lot.item.name}
            for c in batch.consumptions
        ],
        "created_at": batch.created_at.isoformat(), "updated_at": batch.updated_at.isoformat(),
        "container_assigned_quantity": container_assigned_quantity,
        "container_depleted_quantity": container_depleted_quantity,
        "container_unassigned_quantity": max(
            batch.iterations - container_assigned_quantity - container_depleted_quantity, 0
        ),
        "containers": [
            {
                "id": assignment.container.id,
                "identifier": assignment.container.identifier,
                "name": assignment.container.name,
                "state": assignment.container.state,
                "quantity": assignment.quantity,
                "cartridge_limit": assignment.container.cartridge_limit,
            }
            for assignment in container_assignments
        ],
    }
    result.update(batch_edit_state(batch))
    return result


def register_routes(app):
    @app.get("/health")
    def health():
        try:
            db.session.execute(db.select(func.count(User.id))).scalar()
            return jsonify(status="ok", database="ready")
        except Exception:
            return jsonify(status="error", database="unavailable"), 503

    @app.post("/api/auth/register")
    def register():
        data = payload()
        require_fields(data, "email", "password")
        email = data["email"].strip().lower()
        if "@" not in email or len(data["password"]) < 10:
            raise DomainError(
                "validation_error", "Email must be valid and password must be at least 10 characters",
                {"email": "invalid" if "@" not in email else None, "password": "too short" if len(data["password"]) < 10 else None},
            )
        if User.query.filter_by(email=email).first():
            raise DomainError("email_exists", "An account with this email already exists", {"email": "already exists"}, 409)
        user = User(email=email, display_name=data.get("display_name"), password_hash=generate_password_hash(data["password"]))
        db.session.add(user)
        db.session.flush()
        audit(user.id, "User", user.id, "CREATED", new={"email": email})
        db.session.commit()
        return jsonify(user={"id": user.id, "email": user.email}), 201

    @app.post("/api/auth/login")
    def login():
        data = payload()
        require_fields(data, "email", "password")
        user = User.query.filter_by(email=data["email"].strip().lower()).first()
        if not user or not check_password_hash(user.password_hash, data["password"]):
            raise DomainError("invalid_credentials", "Email or password is incorrect", status=401)
        if user.reset_required:
            return jsonify(error={"code": "password_reset_required", "message": "Password reset is required", "details": {"email": user.email}}), 403
        token = secrets.token_urlsafe(32)
        session = AuthSession(
            user_id=user.id, token_hash=token_hash(token),
            expires_at=utcnow() + timedelta(hours=app.config["SESSION_HOURS"]),
        )
        db.session.add(session)
        audit(user.id, "User", user.id, "LOGIN")
        db.session.commit()
        return jsonify(
            token=token, expires_at=session.expires_at.isoformat(),
            user={"id": user.id, "email": user.email, "display_name": user.display_name},
        )

    @app.post("/api/auth/reset")
    def reset_password():
        if not app.config["LOCAL_RESET_ENABLED"]:
            raise DomainError("reset_disabled", "Local password reset is disabled", status=403)
        data = payload()
        require_fields(data, "email", "new_password")
        if len(data["new_password"]) < 10:
            raise DomainError("validation_error", "Password must be at least 10 characters", {"new_password": "too short"})
        user = User.query.filter_by(email=data["email"].strip().lower()).first()
        if not user or not user.reset_required:
            raise DomainError("reset_unavailable", "This account is not eligible for local reset", status=403)
        user.password_hash = generate_password_hash(data["new_password"])
        user.reset_required = False
        AuthSession.query.filter_by(user_id=user.id, revoked_at=None).update({"revoked_at": utcnow()})
        audit(user.id, "User", user.id, "PASSWORD_RESET")
        db.session.commit()
        return jsonify(status="password_reset")

    @app.post("/api/auth/logout")
    @auth_required
    def logout():
        g.auth_session.revoked_at = utcnow()
        db.session.commit()
        return jsonify(status="logged_out")

    @app.get("/api/auth/me")
    @auth_required
    def me():
        return jsonify(user={"id": g.user.id, "email": g.user.email, "display_name": g.user.display_name})

    @app.route("/api/files", methods=["GET", "POST"])
    @auth_required
    def files():
        if request.method == "POST":
            uploads = request.files.getlist("files") or request.files.getlist("file")
            uploads = [upload for upload in uploads if upload and upload.filename]
            if not uploads:
                raise DomainError("validation_error", "At least one file is required", {"files": "required"})
            stored = [
                store_file_bytes(
                    app,
                    g.user.id,
                    upload.filename,
                    upload.read(),
                    upload.mimetype,
                    purpose=request.form.get("purpose") or "GENERAL",
                    entity_type=request.form.get("entity_type") or None,
                    entity_id=request.form.get("entity_id") or None,
                    description=request.form.get("description") or None,
                )
                for upload in uploads
            ]
            db.session.commit()
            return jsonify(files=[stored_file_json(record) for record in stored]), 201

        query = StoredFile.query.filter_by(user_id=g.user.id)
        if request.args.get("purpose"):
            query = query.filter_by(purpose=request.args["purpose"].strip().upper())
        if request.args.get("entity_type"):
            query = query.filter_by(entity_type=request.args["entity_type"])
        if request.args.get("entity_id"):
            query = query.filter_by(entity_id=request.args["entity_id"])
        return jsonify(files=[stored_file_json(record) for record in query.order_by(StoredFile.created_at.desc())])

    @app.get("/api/files/<int:file_id>/download")
    @auth_required
    def download_file(file_id):
        record = owned(StoredFile, file_id)
        path = stored_file_path(app, record)
        if not os.path.exists(path):
            raise DomainError("not_found", "Stored file content was not found", status=404)
        return send_file(
            path,
            mimetype=record.content_type or "application/octet-stream",
            as_attachment=True,
            download_name=record.original_filename,
        )

    @app.delete("/api/files/<int:file_id>")
    @auth_required
    def delete_file(file_id):
        record = owned(StoredFile, file_id)
        previous = stored_file_json(record)
        path = stored_file_path(app, record)
        if os.path.exists(path):
            os.remove(path)
        audit(g.user.id, "StoredFile", record.id, "DELETED", previous=previous)
        db.session.delete(record)
        db.session.commit()
        return jsonify(status="deleted")

    @app.get("/api/items")
    @auth_required
    def list_items():
        query = Item.query.filter_by(user_id=g.user.id)
        if request.args.get("archived") != "true":
            query = query.filter_by(archived=False)
        if request.args.get("category"):
            query = query.filter_by(category=request.args["category"].upper())
        search = request.args.get("q", "").strip()
        if search:
            term = f"%{search}%"
            query = query.filter(or_(Item.manufacturer.ilike(term), Item.product_line.ilike(term), Item.name.ilike(term), Item.characteristics.ilike(term)))
        return jsonify(items=[item_json(item) for item in query.order_by(Item.manufacturer, Item.name)])

    @app.post("/api/items")
    @auth_required
    def create_item():
        data = payload()
        require_fields(data, "category", "manufacturer", "name")
        category = data["category"].upper()
        if category not in ITEM_CATEGORIES:
            category = "OTHER"
        category_fields = ITEM_CATEGORY_FIELDS[category]
        item = Item(
            user_id=g.user.id, category=category, manufacturer=data["manufacturer"].strip(),
            product_line=data.get("product_line"), name=data["name"].strip(),
            characteristics=data.get("characteristics"),
            caliber=data.get("caliber") if "caliber" in category_fields else None,
            bullet_weight=(data.get("bullet_weight") or None) if "bullet_weight" in category_fields else None,
            bullet_type=data.get("bullet_type") if "bullet_type" in category_fields else None,
            primer_type=data.get("primer_type") if "primer_type" in category_fields else None,
            powder_type=data.get("powder_type") if "powder_type" in category_fields else None,
            attributes=parse_json_object(data.get("attributes"), "attributes"), notes=data.get("notes"),
        )
        db.session.add(item)
        db.session.flush()
        audit(g.user.id, "Item", item.id, "CREATED", new=item_json(item))
        db.session.commit()
        return jsonify(item=item_json(item)), 201

    @app.route("/api/items/<int:item_id>", methods=["GET", "PATCH"])
    @auth_required
    def item_detail(item_id):
        item = owned(Item, item_id)
        if request.method == "GET":
            return jsonify(item=item_json(item))
        data = payload()
        ensure_editable(item_edit_state(item))
        previous = item_json(item)
        if "category" in data:
            category = str(data["category"]).upper()
            item.category = category if category in ITEM_CATEGORIES else "OTHER"
        category_fields = ITEM_CATEGORY_FIELDS.get(item.category, set())
        if "archived" in data:
            item.archived = bool(data["archived"])
        for field in ("manufacturer", "product_line", "name", "characteristics", "notes"):
            if field in data:
                setattr(item, field, data[field])
        for field in ("caliber", "bullet_type", "primer_type", "powder_type"):
            if field in data:
                setattr(item, field, data[field] if field in category_fields else None)
        if "bullet_weight" in data and "bullet_weight" in category_fields:
            item.bullet_weight = data["bullet_weight"] or None
        elif "bullet_weight" in data:
            item.bullet_weight = None
        if "attributes" in data:
            item.attributes = parse_json_object(data["attributes"], "attributes")
        audit(g.user.id, "Item", item.id, "UPDATED", previous, item_json(item))
        db.session.commit()
        return jsonify(item=item_json(item))

    @app.get("/api/inventory-lots")
    @auth_required
    def list_lots():
        query = InventoryLot.query.filter_by(user_id=g.user.id)
        if request.args.get("historical") != "true":
            query = query.filter_by(depleted=False)
        return jsonify(lots=[lot_json(lot) for lot in query.order_by(InventoryLot.created_at.desc())])

    @app.post("/api/inventory-lots")
    @auth_required
    def create_lot():
        data = payload()
        require_fields(data, "item_id", "quantity", "unit")
        item = owned(Item, int(data["item_id"]))
        normalized_quantity, normalized_unit = normalize_quantity(item.category, data["quantity"], data["unit"])
        active = bool(data.get("active", False))
        existing_active = None
        if active:
            existing_active = InventoryLot.query.filter_by(
                user_id=g.user.id, item_id=item.id, active=True, depleted=False
            ).first()
            if existing_active and not data.get("replace_active"):
                raise DomainError(
                    "active_lot_exists",
                    "This item already has an active consumption lot",
                    {
                        "active": "only one active lot is allowed",
                        "existing_lot_id": existing_active.id,
                    },
                    409,
                )
            if existing_active:
                existing_active.active = False
                audit(
                    g.user.id,
                    "InventoryLot",
                    existing_active.id,
                    "DEACTIVATED",
                    previous={"active": True},
                    new={"active": False},
                    notes="Replaced by a newly created active lot.",
                )
        lot = InventoryLot(
            user_id=g.user.id, item_id=item.id, manufacturer_lot=data.get("manufacturer_lot"),
            acquired_on=parse_date(data.get("acquired_on"), "acquired_on"),
            opened_on=None,
            original_quantity=as_decimal(data["quantity"]), original_unit=data["unit"],
            normalized_quantity=normalized_quantity, normalized_unit=normalized_unit,
            active=active, notes=data.get("notes"),
        )
        db.session.add(lot)
        db.session.flush()
        audit(g.user.id, "InventoryLot", lot.id, "CREATED", new=lot_json(lot))
        if active:
            audit(
                g.user.id,
                "InventoryLot",
                lot.id,
                "ACTIVATED",
                previous={"active": False},
                new={"active": True},
                notes="Activated during inventory lot creation.",
            )
        db.session.commit()
        return jsonify(lot=lot_json(lot)), 201

    @app.patch("/api/inventory-lots/<int:lot_id>")
    @auth_required
    def update_lot(lot_id):
        lot = owned(InventoryLot, lot_id)
        data = payload()
        previous = lot_json(lot)
        metadata_fields = {
            "item_id", "manufacturer_lot", "acquired_on", "opened_on",
            "quantity", "original_quantity", "unit", "original_unit", "notes",
        }
        if metadata_fields.intersection(data):
            ensure_editable(lot_edit_state(lot))
        if data.get("active") is True:
            target_item_id = int(data.get("item_id") or lot.item_id)
            other = InventoryLot.query.filter(
                InventoryLot.user_id == g.user.id, InventoryLot.item_id == target_item_id,
                InventoryLot.active.is_(True), InventoryLot.depleted.is_(False), InventoryLot.id != lot.id,
            ).first()
            if other:
                raise DomainError("active_lot_exists", "This item already has an active consumption lot", status=409)
            if lot.depleted:
                raise DomainError("depleted_lot", "A depleted lot cannot be activated")
            lot.active = True
            mark_lot_opened_if_drawn(lot)
        elif data.get("active") is False:
            lot.active = False
        if "item_id" in data:
            item = owned(Item, int(data["item_id"]))
            if lot.active:
                other = InventoryLot.query.filter(
                    InventoryLot.user_id == g.user.id, InventoryLot.item_id == item.id,
                    InventoryLot.active.is_(True), InventoryLot.depleted.is_(False), InventoryLot.id != lot.id,
                ).first()
                if other:
                    raise DomainError("active_lot_exists", "This item already has an active consumption lot", status=409)
            lot.item_id = item.id
            lot.item = item
        for field in ("manufacturer_lot", "notes"):
            if field in data:
                setattr(lot, field, data[field])
        if "acquired_on" in data:
            lot.acquired_on = parse_date(data["acquired_on"], "acquired_on")
        if "opened_on" in data:
            lot.opened_on = parse_date(data["opened_on"], "opened_on")
        if any(field in data for field in ("quantity", "original_quantity", "unit", "original_unit", "item_id")):
            quantity = data.get("quantity", data.get("original_quantity", lot.original_quantity))
            unit = data.get("unit", data.get("original_unit", lot.original_unit))
            normalized_quantity, normalized_unit = normalize_quantity(lot.item.category, quantity, unit)
            lot.original_quantity = as_decimal(quantity)
            lot.original_unit = unit
            lot.normalized_quantity = normalized_quantity
            lot.normalized_unit = normalized_unit
        audit(g.user.id, "InventoryLot", lot.id, "UPDATED", previous, lot_json(lot))
        db.session.commit()
        return jsonify(lot=lot_json(lot))

    @app.post("/api/inventory-lots/<int:lot_id>/adjustments")
    @auth_required
    def create_inventory_adjustment(lot_id):
        lot = owned(InventoryLot, lot_id)
        data = payload()
        require_fields(data, "reason")
        reason = data["reason"].strip()
        if not reason:
            raise DomainError(
                "validation_error",
                "Inventory adjustment reason is required",
                {"reason": "required"},
            )
        if lot.reserved_quantity > 0:
            raise DomainError(
                "inventory_reserved",
                "Inventory cannot be adjusted while this lot has active reservations",
                {"reserved_quantity": num(lot.reserved_quantity)},
                409,
            )

        available_before = lot.available_quantity
        if data.get("deplete_remaining"):
            quantity_change = -available_before
        else:
            require_fields(data, "quantity_change")
            quantity_change = as_decimal(data["quantity_change"], "quantity_change")

        if quantity_change == 0:
            raise DomainError(
                "invalid_quantity",
                "Inventory adjustment must change the available quantity",
                {"quantity_change": "must not be zero"},
            )
        if lot.normalized_unit == "count" and quantity_change != quantity_change.to_integral_value():
            raise DomainError(
                "invalid_quantity",
                "Count-based inventory adjustments must be whole numbers",
                {"quantity_change": "must be a whole number"},
            )

        available_after = available_before + quantity_change
        if available_after < 0:
            raise DomainError(
                "invalid_quantity",
                "Inventory adjustment cannot reduce available inventory below zero",
                {
                    "available_quantity": num(available_before),
                    "quantity_change": num(quantity_change),
                },
            )

        previous = lot_json(lot)
        lot.adjustment_quantity += quantity_change
        lot.depleted = available_after == 0
        if lot.depleted:
            lot.active = False

        adjustment = InventoryAdjustment(
            user_id=g.user.id,
            inventory_lot_id=lot.id,
            quantity_change=quantity_change,
            unit=lot.normalized_unit,
            available_before=available_before,
            available_after=available_after,
            reason=reason,
            notes=data.get("notes"),
        )
        db.session.add(adjustment)
        db.session.flush()
        audit(
            g.user.id,
            "InventoryLot",
            lot.id,
            "ADJUSTED",
            previous=previous,
            new=lot_json(lot),
            notes=f"{adjustment.reason}: {quantity_change:+} {lot.normalized_unit}",
        )
        db.session.commit()
        return jsonify(
            adjustment=inventory_adjustment_json(adjustment),
            lot=lot_json(lot),
        ), 201

    @app.get("/api/inventory-lots/<int:lot_id>/adjustments")
    @auth_required
    def list_inventory_adjustments(lot_id):
        lot = owned(InventoryLot, lot_id)
        adjustments = InventoryAdjustment.query.filter_by(
            user_id=g.user.id, inventory_lot_id=lot.id
        ).order_by(InventoryAdjustment.created_at.desc()).all()
        return jsonify(adjustments=[inventory_adjustment_json(row) for row in adjustments])

    @app.get("/api/recipes")
    @auth_required
    def list_recipes():
        query = Recipe.query.filter_by(user_id=g.user.id)
        if request.args.get("archived") != "true":
            query = query.filter_by(archived=False)
        if request.args.get("state"):
            query = query.filter_by(state=request.args["state"].upper())
        return jsonify(recipes=[recipe_json(recipe) for recipe in query.order_by(Recipe.updated_at.desc())])

    @app.get("/api/recipes/suggested-identity")
    @auth_required
    def suggested_recipe_identity():
        return jsonify(identity={"title": make_recipe_title(g.user.id)})

    @app.post("/api/recipes")
    @auth_required
    def create_recipe():
        data = payload()
        require_fields(data, "title", "cartridge")
        title = data["title"].strip()
        suggested_title = (data.get("suggested_title") or "").strip()
        using_default_title = bool(suggested_title and title == suggested_title)

        if using_default_title and recipe_title_exists(g.user.id, title):
            title = make_recipe_title(g.user.id)
        identifier = new_recipe_identifier()

        recipe = Recipe(
            user_id=g.user.id, identifier=identifier, title=title,
            cartridge=data["cartridge"].strip(), overall_length=data.get("overall_length") or None,
            case_length=data.get("case_length") or None, crimp_type=data.get("crimp_type"),
            seating_depth=data.get("seating_depth") or None, source_notes=data.get("source_notes"),
            notes=data.get("notes"), public_notes=data.get("public_notes"),
        )
        db.session.add(recipe)
        db.session.flush()
        audit(
            g.user.id,
            "Recipe",
            recipe.id,
            "CREATED",
            new={"identifier": identifier, "title": recipe.title},
        )
        if data.get("acknowledge_responsibility"):
            acknowledge(g.user.id, "Recipe", recipe.id, "RECIPE_RESPONSIBILITY", "recipe-responsibility-v1")
        db.session.commit()
        return jsonify(recipe=recipe_json(recipe)), 201

    @app.route("/api/recipes/<recipe_id>", methods=["GET", "PATCH"])
    @auth_required
    def recipe_detail(recipe_id):
        recipe = owned_recipe(recipe_id)
        if request.method == "GET":
            aggregate = recipe_aggregate(g.user.id, recipe.id)
            result = recipe_json(recipe)
            result["aggregate_performance"] = aggregate
            return jsonify(recipe=result)
        data = payload()
        ensure_editable(recipe_edit_state(recipe))
        previous = recipe_json(recipe)
        for field in (
            "title", "cartridge", "overall_length", "case_length", "crimp_type",
            "seating_depth", "source_notes", "notes", "public_notes", "archived",
        ):
            if field in data:
                setattr(recipe, field, data[field] if data[field] != "" else None)
        if "public" in data and bool(data["public"]) != recipe.public:
            recipe.public = bool(data["public"])
            if recipe.public and not recipe.public_token:
                recipe.public_token = new_public_token()
            audit(g.user.id, "Recipe", recipe.id, "SHARING_CHANGED", {"public": previous["public"]}, {"public": recipe.public})
        audit(g.user.id, "Recipe", recipe.id, "UPDATED", previous, recipe_json(recipe))
        db.session.commit()
        return jsonify(recipe=recipe_json(recipe))

    @app.post("/api/recipes/<recipe_id>/components")
    @auth_required
    def add_component(recipe_id):
        recipe = owned_recipe(recipe_id)
        ensure_editable(recipe_edit_state(recipe))
        data = payload()
        require_fields(data, "item_id", "quantity", "unit")
        item = owned(Item, int(data["item_id"]))
        role = item.category
        if role in {"BULLET", "POWDER", "PRIMER", "CASE"} and RecipeComponent.query.filter_by(
            user_id=g.user.id, recipe_id=recipe.id, role=role
        ).first():
            raise DomainError(
                "component_role_exists",
                f"This recipe already has a {role.title()} component. Create a separate recipe to use a different item.",
                {"role": role},
                409,
            )
        quantity = as_decimal(data["quantity"])
        if quantity <= 0:
            raise DomainError("invalid_quantity", "Component quantity must be positive", {"quantity": "must be positive"})
        expected_unit = "grains" if item.category == "POWDER" else "count"
        unit = data["unit"].lower()
        if (expected_unit == "grains" and unit not in {"grain", "grains", "gr"}) or (
            expected_unit == "count" and unit not in {"count", "each", "ea"}
        ):
            raise DomainError("invalid_unit", f"{item.category.title()} recipe components require {expected_unit}")
        component = RecipeComponent(
            user_id=g.user.id, recipe_id=recipe.id, item_id=item.id, role=role,
            quantity=quantity, unit=expected_unit, alternative_group=None,
        )
        db.session.add(component)
        db.session.flush()
        audit(g.user.id, "RecipeComponent", component.id, "CREATED", new=component_json(component))
        db.session.commit()
        return jsonify(component=component_json(component), warnings=recipe_warnings(recipe)), 201

    @app.delete("/api/recipes/<recipe_id>/components/<int:component_id>")
    @auth_required
    def delete_component(recipe_id, component_id):
        recipe = owned_recipe(recipe_id)
        ensure_editable(recipe_edit_state(recipe))
        component = db.session.get(RecipeComponent, component_id)
        if not component or component.recipe_id != recipe.id or component.user_id != g.user.id:
            raise DomainError("not_found", "Component not found", status=404)
        audit(g.user.id, "RecipeComponent", component.id, "DELETED", previous=component_json(component))
        db.session.delete(component)
        db.session.commit()
        return Response(status=204)

    @app.post("/api/recipes/<recipe_id>/sources")
    @auth_required
    def add_source(recipe_id):
        recipe = owned_recipe(recipe_id)
        ensure_editable(recipe_edit_state(recipe))
        data = request.form if request.files else payload()
        require_fields(data, "kind")
        stored_file = None
        upload = request.files.get("source_file") if request.files else None
        if upload and upload.filename:
            content = upload.read()
            if not content:
                raise DomainError("validation_error", "Uploaded source file cannot be empty", {"source_file": "empty"})
            stored_file = store_file_bytes(
                app,
                g.user.id,
                upload.filename,
                content,
                upload.mimetype,
                purpose="RECIPE_SOURCE",
                entity_type="Recipe",
                entity_id=recipe.identifier,
                description="Recipe source material.",
                storage_folder=("recipes", recipe.identifier),
            )
        elif data.get("stored_file_id"):
            stored_file = owned(StoredFile, data.get("stored_file_id"))
        source = SourceMaterial(
            user_id=g.user.id, recipe_id=recipe.id, kind=data["kind"].upper(),
            citation=data.get("citation"), url=data.get("url"), page=data.get("page"),
            file_name=data.get("file_name") or (stored_file.original_filename if stored_file else None),
            stored_file_id=stored_file.id if stored_file else None,
            notes=data.get("notes"),
        )
        if not any((source.citation, source.url, source.file_name, source.notes, source.stored_file_id)):
            raise DomainError("validation_error", "Source material needs a source label, URL, uploaded file, or notes")
        db.session.add(source)
        db.session.flush()
        audit(g.user.id, "SourceMaterial", source.id, "CREATED", new=source_json(source))
        db.session.commit()
        return jsonify(source=source_json(source)), 201

    @app.post("/api/recipes/<recipe_id>/transition")
    @auth_required
    def transition_recipe(recipe_id):
        recipe = owned_recipe(recipe_id)
        data = payload()
        require_fields(data, "state")
        target = data["state"].upper()
        if target not in RECIPE_STATES:
            raise DomainError("validation_error", "Unknown recipe state", {"state": target})
        ensure_transition(recipe.state, target, RECIPE_TRANSITIONS, "Recipe")
        warnings = recipe_warnings(recipe)
        blocking_warnings = [warning for warning in warnings if warning != MISSING_SOURCE_WARNING]
        if target in {"UNDER TEST", "APPROVED"} and blocking_warnings:
            raise DomainError(
                "recipe_incomplete",
                "Recipe cannot advance while required information is missing",
                {"warnings": blocking_warnings},
                409,
            )
        missing_source = MISSING_SOURCE_WARNING in warnings
        if missing_source and not data.get("acknowledge_missing_source"):
            raise DomainError(
                "acknowledgement_required",
                "Transitioning a recipe without source material requires acknowledgement",
                {"acknowledgement": "MISSING_SOURCE_RECIPE_TRANSITION"},
                409,
            )
        previous = recipe.state
        recipe.state = target
        if missing_source:
            acknowledge(
                g.user.id,
                "Recipe",
                recipe.id,
                "MISSING_SOURCE_RECIPE_TRANSITION",
                "missing-source-override-v1",
                MISSING_SOURCE_WARNING,
            )
        audit(g.user.id, "Recipe", recipe.id, "STATE_CHANGED", {"state": previous}, {"state": target})
        db.session.commit()
        return jsonify(recipe=recipe_json(recipe))

    @app.post("/api/acknowledgements")
    @auth_required
    def create_acknowledgement():
        data = payload()
        require_fields(data, "entity_type", "entity_id", "acknowledgement_type", "text_version")
        record = acknowledge(
            g.user.id, data["entity_type"], data["entity_id"], data["acknowledgement_type"],
            data["text_version"], data.get("related_warning"),
        )
        db.session.commit()
        return jsonify(acknowledgement={"id": record.id, "created_at": record.created_at.isoformat()}), 201

    @app.get("/api/public/recipes/<token>")
    def public_recipe(token):
        recipe = Recipe.query.filter_by(public_token=token, public=True, archived=False).first()
        if not recipe:
            raise DomainError("not_found", "Public recipe not found", status=404)
        return jsonify(recipe=recipe_json(recipe, public=True))

    @app.get("/api/batches")
    @auth_required
    def list_batches():
        query = Batch.query.filter_by(user_id=g.user.id)
        if request.args.get("state"):
            query = query.filter_by(state=request.args["state"].upper())
        batches = query.order_by(Batch.created_at.desc()).all()
        if any(reconcile_batch_from_container_assignments(batch) for batch in batches):
            db.session.commit()
        return jsonify(batches=[batch_json(batch) for batch in batches])

    @app.post("/api/batches")
    @auth_required
    def create_batch():
        data = payload()
        require_fields(data, "recipe_id", "iterations", "allocations")
        recipe = owned_recipe(data["recipe_id"])
        try:
            iterations = int(data["iterations"])
        except (TypeError, ValueError):
            raise DomainError("validation_error", "Iterations must be a whole number", {"iterations": "invalid"})
        if iterations <= 0:
            raise DomainError("invalid_quantity", "Batch quantity must be positive", {"iterations": "must be positive"})
        if recipe.state != "APPROVED":
            if not data.get("acknowledge_non_approved"):
                raise DomainError(
                    "acknowledgement_required", "Using a non-approved recipe requires acknowledgement",
                    {"acknowledgement": "NON_APPROVED_RECIPE_BATCH"}, 409,
                )
        warnings = recipe_warnings(recipe)
        blocking_warnings = [warning for warning in warnings if warning != MISSING_SOURCE_WARNING]
        if blocking_warnings:
            raise DomainError(
                "recipe_incomplete",
                "Batch cannot be created from an incomplete recipe",
                {"warnings": blocking_warnings},
                409,
            )
        missing_source = MISSING_SOURCE_WARNING in warnings
        if missing_source and not data.get("acknowledge_missing_source"):
            raise DomainError(
                "acknowledgement_required",
                "Creating a batch without recipe source material requires acknowledgement",
                {"acknowledgement": "MISSING_SOURCE_BATCH"},
                409,
            )
        allocations = validate_allocations(recipe, iterations, data["allocations"], g.user.id)
        slug = make_slug(lambda candidate: Batch.query.filter_by(user_id=g.user.id, slug=candidate).first())
        batch = Batch(
            user_id=g.user.id, recipe_id=recipe.id, identifier=new_batch_identifier(),
            slug=slug, iterations=iterations,
            state="UNDER PRODUCTION", characteristics=data.get("characteristics"),
            notes=data.get("notes"), locked=True,
        )
        db.session.add(batch)
        db.session.flush()
        for component, lot, quantity in allocations:
            if lot.available_quantity < quantity:
                raise DomainError(
                    "insufficient_inventory", f"Lot {lot.id} does not have enough available inventory",
                    {"lot_id": lot.id, "available": num(lot.available_quantity), "required": num(quantity)}, 409,
                )
            lot.reserved_quantity += quantity
            mark_lot_opened_if_drawn(lot)
            db.session.add(BatchInventoryReservation(
                user_id=g.user.id, batch_id=batch.id, inventory_lot_id=lot.id,
                recipe_component_id=component.id, quantity=quantity,
            ))
            audit(
                g.user.id, "InventoryLot", lot.id, "RESERVED",
                new={"batch_id": batch.identifier, "quantity": num(quantity)},
            )
        audit(
            g.user.id, "Batch", batch.identifier, "CREATED",
            new={"identifier": batch.identifier, "slug": slug, "iterations": iterations, "state": batch.state},
        )
        if missing_source:
            acknowledge(
                g.user.id,
                "Batch",
                batch.identifier,
                "MISSING_SOURCE_BATCH",
                "missing-source-override-v1",
                MISSING_SOURCE_WARNING,
            )
        if recipe.state != "APPROVED":
            acknowledge(
                g.user.id, "Batch", batch.identifier,
                "NON_APPROVED_RECIPE_BATCH", "non-approved-recipe-v1",
            )
        db.session.commit()
        return jsonify(batch=batch_json(batch)), 201

    @app.route("/api/batches/<batch_id>", methods=["GET", "PATCH"])
    @auth_required
    def get_batch(batch_id):
        batch = owned_batch(batch_id)
        if reconcile_batch_from_container_assignments(batch):
            db.session.commit()
        if request.method == "PATCH":
            ensure_editable(batch_edit_state(batch))
            data = payload()
            previous = batch_json(batch)
            if "slug" in data:
                slug = str(data["slug"]).strip()
                if not slug:
                    raise DomainError("validation_error", "Batch slug is required", {"slug": "required"})
                existing = Batch.query.filter(
                    Batch.user_id == g.user.id,
                    Batch.slug == slug,
                    Batch.id != batch.id,
                ).first()
                if existing:
                    raise DomainError("slug_exists", "Batch slug already exists", {"slug": "already exists"}, 409)
                batch.slug = slug
            for field in ("characteristics", "notes"):
                if field in data:
                    setattr(batch, field, data[field])
            audit(g.user.id, "Batch", batch.identifier, "UPDATED", previous, batch_json(batch))
            db.session.commit()
            return jsonify(batch=batch_json(batch))
        result = batch_json(batch)
        performance = PerformanceRecord.query.filter_by(user_id=g.user.id, batch_id=batch.id).first()
        result["performance"] = performance_json(performance) if performance else None
        return jsonify(batch=result)

    @app.post("/api/batches/<batch_id>/transition")
    @auth_required
    def transition_batch(batch_id):
        batch = owned_batch(batch_id)
        data = payload()
        require_fields(data, "state")
        target = data["state"].upper()
        if target == batch.state:
            return jsonify(batch=batch_json(batch))
        ensure_transition(batch.state, target, BATCH_TRANSITIONS, "Batch")
        if target == "PRODUCED":
            commit_batch_inventory(batch)
        elif target == "CANCELLED":
            outstanding = [r for r in batch.reservations if r.status == "RESERVED"]
            if outstanding:
                raise DomainError(
                    "inventory_accounting_required",
                    "Account for every reserved quantity as returned or lost before cancellation",
                    {"reservation_ids": [r.id for r in outstanding]}, 409,
                )
        previous = batch.state
        batch.state = target
        audit(
            g.user.id, "Batch", batch.identifier,
            "STATE_CHANGED", {"state": previous}, {"state": target},
        )
        db.session.commit()
        return jsonify(batch=batch_json(batch))

    @app.post("/api/batches/<batch_id>/returns")
    @auth_required
    def inventory_return(batch_id):
        batch = owned_batch(batch_id)
        data = payload()
        require_fields(data, "source_lot_id", "quantity_returned", "quantity_lost", "reason")
        source = owned(InventoryLot, int(data["source_lot_id"]))
        returned = as_decimal(data["quantity_returned"], "quantity_returned")
        lost = as_decimal(data["quantity_lost"], "quantity_lost")
        if returned < 0 or lost < 0 or returned + lost <= 0:
            raise DomainError("invalid_quantity", "Returned and lost quantities must account for a positive amount")
        trace_lot_ids = {r.inventory_lot_id for r in batch.reservations}
        trace_lot_ids.update(c.inventory_lot_id for c in batch.consumptions)
        if source.id not in trace_lot_ids:
            raise DomainError("not_found", "This batch has no inventory trace for the selected lot", status=404)
        destination = source
        if data.get("destination_lot_id"):
            destination = owned(InventoryLot, int(data["destination_lot_id"]))
            if destination.id not in trace_lot_ids:
                raise DomainError("invalid_destination", "Return destination must be part of this batch inventory trace")
            if destination.item_id != source.item_id:
                raise DomainError("invalid_destination", "Return destination must contain the same item")
        reservations = [r for r in batch.reservations if r.inventory_lot_id == source.id and r.status == "RESERVED"]
        consumptions = [c for c in batch.consumptions if c.inventory_lot_id == source.id]
        available_to_account = sum((r.quantity for r in reservations), Decimal("0"))
        consumed_to_account = sum((c.quantity for c in consumptions), Decimal("0"))
        amount = returned + lost
        if reservations:
            if amount != available_to_account:
                raise DomainError(
                    "inventory_accounting_incomplete",
                    "Returned plus lost quantity must equal the outstanding reserved quantity for this lot",
                    {"outstanding": num(available_to_account), "accounted": num(amount)},
                )
            remaining = amount
            for reservation in reservations:
                applied = min(reservation.quantity, remaining)
                source.reserved_quantity -= applied
                if lost:
                    loss_applied = min(lost, applied)
                    source.consumed_quantity += loss_applied
                    lost -= loss_applied
                reservation.status = "ACCOUNTED"
                remaining -= applied
                if remaining <= 0:
                    break
        elif consumptions:
            if amount > consumed_to_account:
                raise DomainError("invalid_quantity", "Return exceeds consumed quantity for this batch and lot")
            if destination.id == source.id:
                source.consumed_quantity -= returned
            else:
                destination.normalized_quantity += returned
            # Lost quantity remains consumed.
        else:
            raise DomainError("not_found", "This batch has no inventory trace for the selected lot", status=404)
        source.depleted = source.available_quantity <= 0
        destination.depleted = destination.available_quantity <= 0
        record = InventoryReturn(
            user_id=g.user.id, batch_id=batch.id, item_id=source.item_id, source_lot_id=source.id,
            destination_lot_id=destination.id if returned else None, quantity_returned=as_decimal(data["quantity_returned"]),
            quantity_lost=as_decimal(data["quantity_lost"]), reason=data["reason"], notes=data.get("notes"),
        )
        db.session.add(record)
        db.session.flush()
        acknowledge(g.user.id, "InventoryReturn", record.id, "INVENTORY_RETURN_LOSS", "inventory-return-v1")
        audit(g.user.id, "InventoryReturn", record.id, "CREATED", new={
            "batch_id": batch.identifier, "source_lot_id": source.id,
            "destination_lot_id": record.destination_lot_id,
            "returned": num(record.quantity_returned), "lost": num(record.quantity_lost), "reason": record.reason,
        })
        db.session.commit()
        return jsonify(inventory_return={"id": record.id, "batch_id": batch.identifier}), 201

    @app.get("/api/containers")
    @auth_required
    def list_containers():
        containers = StorageContainer.query.filter_by(user_id=g.user.id).order_by(StorageContainer.name).all()
        return jsonify(containers=[container_json(container, g.user.id) for container in containers])

    @app.post("/api/containers")
    @auth_required
    def create_container():
        data = payload()
        require_fields(data, "identifier", "name", "cartridge_limit")
        try:
            cartridge_limit = int(data["cartridge_limit"])
        except (TypeError, ValueError):
            raise DomainError("invalid_quantity", "Container cartridge limit must be a positive whole number")
        if cartridge_limit <= 0:
            raise DomainError("invalid_quantity", "Container cartridge limit must be a positive whole number")
        if StorageContainer.query.filter_by(user_id=g.user.id, identifier=data["identifier"]).first():
            raise DomainError("identifier_exists", "Container identifier already exists", {"identifier": "already exists"}, 409)
        container = StorageContainer(
            user_id=g.user.id, identifier=data["identifier"].strip(), name=data["name"].strip(),
            cartridge_limit=cartridge_limit, description=data.get("description"), notes=data.get("notes"),
        )
        db.session.add(container)
        db.session.flush()
        audit(
            g.user.id, "StorageContainer", container.id, "CREATED",
            new={"identifier": container.identifier, "cartridge_limit": container.cartridge_limit},
        )
        db.session.commit()
        return jsonify(container=container_json(container, g.user.id)), 201

    @app.patch("/api/containers/<int:container_id>")
    @auth_required
    def update_container(container_id):
        container = owned(StorageContainer, container_id)
        data = payload()
        previous = container_json(container, g.user.id)
        metadata_fields = {"identifier", "name", "description", "notes", "cartridge_limit"}
        if metadata_fields.intersection(data):
            ensure_editable(container_edit_state(container))
        if "identifier" in data:
            identifier = str(data["identifier"]).strip()
            if not identifier:
                raise DomainError("validation_error", "Container identifier is required", {"identifier": "required"})
            existing = StorageContainer.query.filter(
                StorageContainer.user_id == g.user.id,
                StorageContainer.identifier == identifier,
                StorageContainer.id != container.id,
            ).first()
            if existing:
                raise DomainError("identifier_exists", "Container identifier already exists", {"identifier": "already exists"}, 409)
            container.identifier = identifier
        for field in ("name", "description", "notes"):
            if field in data:
                setattr(container, field, data[field])
        if "cartridge_limit" in data:
            try:
                cartridge_limit = int(data["cartridge_limit"])
            except (TypeError, ValueError):
                raise DomainError("invalid_quantity", "Container cartridge limit must be a positive whole number")
            if cartridge_limit <= 0:
                raise DomainError("invalid_quantity", "Container cartridge limit must be a positive whole number")
            assigned_quantity = db.session.query(func.coalesce(func.sum(ContainerAssignment.quantity), 0)).filter_by(
                user_id=g.user.id, container_id=container.id
            ).scalar()
            if int(assigned_quantity or 0) > cartridge_limit:
                raise DomainError(
                    "invalid_quantity",
                    "Container cartridge limit cannot be lower than assigned quantity",
                    status=409,
                )
            container.cartridge_limit = cartridge_limit
        if "state" in data:
            state = data["state"].upper()
            if state not in CONTAINER_STATES:
                raise DomainError("validation_error", "Unknown container state", {"state": state})
            if state != container.state:
                ensure_transition(container.state, state, CONTAINER_TRANSITIONS, "StorageContainer")
                container.state = state
                assignments = ContainerAssignment.query.filter_by(
                    user_id=g.user.id, container_id=container.id
                ).all()
                if state == "EMPTY" and assignments:
                    affected_batches = {assignment.batch for assignment in assignments}
                    for assignment in assignments:
                        assignment.batch.container_depleted_quantity = (
                            int(assignment.batch.container_depleted_quantity or 0)
                            + assignment.quantity
                        )
                    for assignment in assignments:
                        audit(
                            g.user.id,
                            "ContainerAssignment",
                            assignment.id,
                            "CLEARED",
                            previous={
                                "container_id": container.id,
                                "batch_id": assignment.batch.identifier,
                                "quantity": assignment.quantity,
                            },
                            notes="Container transitioned to EMPTY.",
                        )
                        db.session.delete(assignment)
                    db.session.flush()
                    for batch in affected_batches:
                        update_batch_storage_state(batch)
                else:
                    for assignment in assignments:
                        update_batch_storage_state(assignment.batch)
        audit(g.user.id, "StorageContainer", container.id, "UPDATED", previous, container_json(container, g.user.id))
        db.session.commit()
        return jsonify(container=container_json(container, g.user.id))

    @app.post("/api/containers/<int:container_id>/assignments")
    @auth_required
    def assign_container(container_id):
        container = owned(StorageContainer, container_id)
        data = payload()
        require_fields(data, "batch_id", "quantity")
        batch = owned_batch(data["batch_id"])
        if batch.state == "UNDER PRODUCTION":
            raise DomainError(
                "invalid_batch_state",
                "Batch must be produced before cartridges can be assigned to a container",
                status=409,
            )
        if batch.state in {"CANCELLED", "DECOMMISSIONED", "DEPLETED"}:
            raise DomainError(
                "invalid_batch_state",
                "Batch state does not allow container assignment",
                status=409,
            )
        if container.state == "USED":
            raise DomainError(
                "invalid_container_state",
                "Transition the container to EMPTY before assigning more cartridges",
                status=409,
            )
        quantity = int(data["quantity"])
        if quantity <= 0:
            raise DomainError("invalid_quantity", "Assignment quantity must be positive")
        current = ContainerAssignment.query.filter_by(user_id=g.user.id, container_id=container.id).all()
        mixed = any(assignment.batch_id != batch.id for assignment in current)
        if mixed and not data.get("acknowledge_mixed_batch"):
            raise DomainError(
                "acknowledgement_required", "This container already contains another batch",
                {"acknowledgement": "MIXED_BATCH_CONTAINER"}, 409,
            )
        already_assigned = db.session.query(func.coalesce(func.sum(ContainerAssignment.quantity), 0)).filter_by(
            user_id=g.user.id, batch_id=batch.id
        ).scalar()
        if int(already_assigned) + int(batch.container_depleted_quantity or 0) + quantity > batch.iterations:
            raise DomainError("invalid_quantity", "Assignments cannot exceed the batch quantity", status=409)
        if (
            container.cartridge_limit is not None
            and live_container_quantity(container) + quantity > container.cartridge_limit
        ):
            raise DomainError("invalid_quantity", "Assignment exceeds the container cartridge limit", status=409)
        assignment = ContainerAssignment.query.filter_by(container_id=container.id, batch_id=batch.id).first()
        if assignment:
            assignment.quantity += quantity
        else:
            assignment = ContainerAssignment(
                user_id=g.user.id, container_id=container.id, batch_id=batch.id, quantity=quantity,
            )
            db.session.add(assignment)
        container.state = "ASSIGNED"
        db.session.flush()
        update_batch_storage_state(batch)
        if mixed:
            acknowledge(g.user.id, "StorageContainer", container.id, "MIXED_BATCH_CONTAINER", "mixed-batch-container-v1")
        audit(
            g.user.id, "ContainerAssignment", assignment.id, "ASSIGNED",
            new={"batch_id": batch.identifier, "quantity": quantity},
        )
        db.session.commit()
        return jsonify(container=container_json(container, g.user.id)), 201

    @app.route("/api/batches/<batch_id>/performance", methods=["GET", "PUT"])
    @auth_required
    def batch_performance(batch_id):
        batch = owned_batch(batch_id)
        record = PerformanceRecord.query.filter_by(user_id=g.user.id, batch_id=batch.id).first()
        if request.method == "GET":
            if not record:
                raise DomainError("not_found", "Performance record not found", status=404)
            return jsonify(performance=performance_json(record))
        if batch.state == "UNDER PRODUCTION":
            raise DomainError(
                "invalid_batch_state",
                "Performance and quality data cannot be recorded while the batch is under production",
                {"state": batch.state},
                409,
            )
        data = payload()
        fields = (
            "firearm", "barrel_length", "distance", "group_size", "shot_count",
            "velocity_average", "velocity_minimum", "velocity_maximum", "standard_deviation",
            "extreme_spread", "temperature", "weather_notes", "reliability_notes",
            "pressure_sign_notes", "recoil_perception", "accuracy_perception",
            "cleanliness_perception", "subjective_rating", "notes", "raw_data",
        )
        if record:
            previous = performance_json(record)
            record.edited = True
        else:
            previous = None
            record = PerformanceRecord(user_id=g.user.id, batch_id=batch.id)
            db.session.add(record)
        for field in fields:
            if field in data:
                setattr(record, field, data[field] if data[field] != "" else None)
        if "recorded_on" in data:
            record.recorded_on = parse_date(data["recorded_on"], "recorded_on")
        if "processed_data" in data:
            record.processed_data = parse_json_object(data["processed_data"], "processed_data")
        db.session.flush()
        audit(
            g.user.id, "PerformanceRecord", record.id,
            "UPDATED" if previous else "CREATED", previous, performance_json(record),
        )
        db.session.commit()
        return jsonify(performance=performance_json(record)), 200 if previous else 201

    @app.post("/api/batches/<batch_id>/performance/garmin-import")
    @auth_required
    def import_garmin_performance(batch_id):
        batch = owned_batch(batch_id)
        if batch.state == "UNDER PRODUCTION":
            raise DomainError(
                "invalid_batch_state",
                "Performance and quality data cannot be recorded while the batch is under production",
                {"state": batch.state},
                409,
            )
        uploads = request.files.getlist("files") or request.files.getlist("file")
        uploads = [upload for upload in uploads if upload and upload.filename]
        if not uploads:
            raise DomainError("validation_error", "At least one Garmin FIT file is required", {"files": "required"})

        parsed_files = []
        pending_files = []
        for upload in uploads:
            content = upload.read()
            if not content:
                raise DomainError("validation_error", "Uploaded Garmin FIT files cannot be empty", {"filename": upload.filename})
            try:
                parsed_files.append(parse_xero_c1_fit(content, filename=upload.filename))
            except FitParseError as exc:
                raise DomainError("invalid_garmin_fit", str(exc), {"filename": upload.filename})
            pending_files.append((upload.filename, content, upload.mimetype))

        stored_files = [
            store_file_bytes(
                app,
                g.user.id,
                filename,
                content,
                content_type,
                purpose="GARMIN_IMPORT",
                entity_type="Batch",
                entity_id=batch.identifier,
                description="Garmin performance import source file.",
                storage_folder=("batches", batch.slug),
            )
            for filename, content, content_type in pending_files
        ]
        imported = combine_xero_c1_sessions(parsed_files, stored_files, utcnow())
        record = PerformanceRecord.query.filter_by(user_id=g.user.id, batch_id=batch.id).first()
        if record:
            previous = performance_json(record)
            record.edited = True
        else:
            previous = None
            record = PerformanceRecord(user_id=g.user.id, batch_id=batch.id)
            db.session.add(record)

        if imported["recorded_on"]:
            record.recorded_on = parse_date(imported["recorded_on"], "recorded_on")
        for field in (
            "shot_count",
            "velocity_average",
            "velocity_minimum",
            "velocity_maximum",
            "standard_deviation",
            "extreme_spread",
            "raw_data",
        ):
            setattr(record, field, imported[field])
        processed_data = dict(record.processed_data or {})
        processed_data.update(imported["processed_data"])
        record.processed_data = processed_data
        db.session.flush()
        audit(
            g.user.id, "PerformanceRecord", record.id,
            "UPDATED" if previous else "CREATED", previous, performance_json(record),
            notes="Imported Garmin Xero C1 Pro FIT session data.",
        )
        db.session.commit()
        return jsonify(
            performance=performance_json(record),
            files=[stored_file_json(record) for record in stored_files],
        ), 200 if previous else 201

    @app.get("/api/dashboard")
    @auth_required
    def dashboard():
        item_count = Item.query.filter_by(user_id=g.user.id, archived=False).count()
        active_lots = InventoryLot.query.filter_by(user_id=g.user.id, depleted=False).count()
        depleted_lots = InventoryLot.query.filter_by(user_id=g.user.id, depleted=True).count()
        low_lots = [
            lot_json(lot) for lot in InventoryLot.query.filter_by(user_id=g.user.id, depleted=False).all()
            if lot.normalized_quantity and lot.available_quantity / lot.normalized_quantity <= Decimal("0.10")
        ]
        recipe_counts = dict(
            db.session.query(Recipe.state, func.count(Recipe.id)).filter_by(user_id=g.user.id).group_by(Recipe.state).all()
        )
        batch_counts = dict(
            db.session.query(Batch.state, func.count(Batch.id)).filter_by(user_id=g.user.id).group_by(Batch.state).all()
        )
        container_counts = dict(
            db.session.query(StorageContainer.state, func.count(StorageContainer.id))
            .filter_by(user_id=g.user.id).group_by(StorageContainer.state).all()
        )
        recent = AuditLog.query.filter_by(user_id=g.user.id).order_by(AuditLog.created_at.desc()).limit(10).all()
        return jsonify(metrics={
            "items": item_count, "active_inventory_lots": active_lots,
            "depleted_inventory_lots": depleted_lots, "low_inventory": low_lots,
            "recipes_by_state": recipe_counts, "batches_by_state": batch_counts,
            "containers_by_state": container_counts,
            "batches_under_production": batch_counts.get("UNDER PRODUCTION", 0),
            "recent_activity": [audit_json(entry) for entry in recent],
        })

    @app.get("/api/audit")
    @auth_required
    def audit_history():
        query = AuditLog.query.filter_by(user_id=g.user.id)
        if request.args.get("entity_type"):
            query = query.filter_by(entity_type=request.args["entity_type"])
        if request.args.get("entity_id"):
            query = query.filter_by(entity_id=request.args["entity_id"])
        limit = min(int(request.args.get("limit", 100)), 500)
        return jsonify(audit=[audit_json(entry) for entry in query.order_by(AuditLog.created_at.desc()).limit(limit)])

    @app.get("/api/qr/<entity_type>/<entity_id>")
    @auth_required
    def qr_code(entity_type, entity_id):
        if entity_type == "batch":
            entity = owned_batch(entity_id)
            url = app.config["PUBLIC_BASE_URL"] + f"/batches/{entity.identifier}"
        elif entity_type == "recipe":
            entity = owned_recipe(entity_id)
            url = (
                app.config["PUBLIC_BASE_URL"] + f"/public/recipes/{entity.public_token}"
                if entity.public and entity.public_token
                else app.config["PUBLIC_BASE_URL"] + f"/recipes/{entity.identifier}"
            )
        else:
            raise DomainError("validation_error", "QR entity type must be batch or recipe")
        image = qrcode.make(url)
        output = io.BytesIO()
        image.save(output, format="PNG")
        output.seek(0)
        return send_file(output, mimetype="image/png", download_name=f"{entity_type}-{entity_id}.png")

    @app.get("/api/export/<entity>")
    @auth_required
    def export_data(entity):
        rows = export_rows(entity, g.user.id)
        output_format = request.args.get("format", "json").lower()
        audit(g.user.id, "Export", entity, "CREATED", new={"format": output_format})
        db.session.commit()
        if output_format == "json":
            return Response(json.dumps(rows, indent=2, default=str), mimetype="application/json",
                            headers={"Content-Disposition": f"attachment; filename={entity}.json"})
        if output_format == "csv":
            output = io.StringIO()
            if rows:
                writer = csv.DictWriter(output, fieldnames=rows[0].keys(), extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
            return Response(output.getvalue(), mimetype="text/csv",
                            headers={"Content-Disposition": f"attachment; filename={entity}.csv"})
        raise DomainError("validation_error", "Export format must be json or csv")

    @app.post("/api/admin/backup")
    @auth_required
    def backup_database():
        database_url = app.config["SQLALCHEMY_DATABASE_URI"]
        if not database_url.startswith("sqlite:///"):
            raise DomainError("unsupported_database", "Built-in backup currently supports SQLite only")
        source_path = database_url.removeprefix("sqlite:///")
        backup_dir = os.getenv("BACKUP_DIR", "/data/backups")
        os.makedirs(backup_dir, exist_ok=True)
        filename = f"reloading-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.sqlite3"
        destination = os.path.join(backup_dir, filename)
        source_connection = sqlite3.connect(source_path)
        destination_connection = sqlite3.connect(destination)
        try:
            source_connection.backup(destination_connection)
        finally:
            source_connection.close()
            destination_connection.close()
        audit(g.user.id, "Backup", filename, "CREATED")
        db.session.commit()
        return jsonify(backup={"filename": filename})


def validate_allocations(recipe, iterations, raw_allocations, user_id):
    if not isinstance(raw_allocations, list) or not raw_allocations:
        raise DomainError("validation_error", "allocations must be a non-empty list", {"allocations": "required"})
    components = {component.id: component for component in recipe.components}
    totals = {}
    allocations = []
    for raw in raw_allocations:
        try:
            component_id, lot_id = int(raw["component_id"]), int(raw["lot_id"])
        except (KeyError, TypeError, ValueError):
            raise DomainError("validation_error", "Each allocation needs component_id and lot_id")
        component = components.get(component_id)
        if not component:
            raise DomainError("invalid_component", "Allocation component is not part of this recipe")
        lot = db.session.get(InventoryLot, lot_id)
        if not lot or lot.user_id != user_id or lot.item_id != component.item_id or lot.depleted:
            raise DomainError("invalid_lot", "Allocation lot is unavailable or does not match the component")
        quantity = as_decimal(raw.get("quantity"), "quantity")
        if quantity <= 0:
            raise DomainError("invalid_quantity", "Allocation quantity must be positive")
        totals[component_id] = totals.get(component_id, Decimal("0")) + quantity
        allocations.append((component, lot, quantity))

    for component in recipe.components:
        required = component.quantity * iterations
        if totals.get(component.id, Decimal("0")) != required:
            raise DomainError(
                "allocation_mismatch", f"Allocation for {component.role} must total {required} {component.unit}",
                {"component_id": component.id, "required": num(required), "allocated": num(totals.get(component.id, 0))},
            )
    unexpected = set(totals) - set(components)
    if unexpected:
        raise DomainError("invalid_component", "Unexpected recipe component allocation")
    return allocations


def recipe_title_exists(user_id, title):
    return Recipe.query.filter(
        Recipe.user_id == user_id,
        func.lower(Recipe.title) == title.lower(),
    ).first() is not None


def make_recipe_title(user_id):
    slug = make_slug(
        lambda candidate: recipe_title_exists(
            user_id, " ".join(word.capitalize() for word in candidate.split("-"))
        )
    )
    return " ".join(word.capitalize() for word in slug.split("-"))


def new_recipe_identifier():
    while True:
        identifier = str(uuid.uuid4())
        if not Recipe.query.filter_by(identifier=identifier).first():
            return identifier


def new_batch_identifier():
    while True:
        identifier = str(uuid.uuid4())
        if not Batch.query.filter_by(identifier=identifier).first():
            return identifier


def commit_batch_inventory(batch):
    depleted_active_lots = []
    depleted_active_lot_ids = set()
    consumed_lots_by_item = {}
    for reservation in batch.reservations:
        if reservation.status != "RESERVED":
            raise DomainError("inventory_accounting_error", "Reservation has already been accounted for", status=409)
        lot = reservation.inventory_lot
        if lot.reserved_quantity < reservation.quantity:
            raise DomainError("inventory_integrity_error", "Reserved inventory is inconsistent", status=409)
        was_active = lot.active and not lot.depleted
        was_depleted = lot.depleted
        lot.reserved_quantity -= reservation.quantity
        lot.consumed_quantity += reservation.quantity
        mark_lot_opened_if_drawn(lot)
        consumed_lots_by_item.setdefault(lot.item_id, {})[lot.id] = lot
        lot.depleted = lot.available_quantity <= 0
        if lot.depleted and not was_depleted:
            audit(
                batch.user_id,
                "InventoryLot",
                lot.id,
                "DEPLETED",
                previous={"depleted": False},
                new={"depleted": True, "batch_id": batch.identifier},
                notes="Automatically marked depleted after committed batch consumption.",
            )
        if lot.depleted and lot.active:
            lot.active = False
            audit(
                batch.user_id,
                "InventoryLot",
                lot.id,
                "DEACTIVATED",
                previous={"active": True},
                new={"active": False, "batch_id": batch.identifier},
                notes="Automatically deactivated because committed batch consumption depleted the lot.",
            )
        if was_active and lot.depleted and lot.id not in depleted_active_lot_ids:
            depleted_active_lots.append(lot)
            depleted_active_lot_ids.add(lot.id)
        reservation.status = "CONSUMED"
        db.session.add(BatchInventoryConsumption(
            user_id=batch.user_id, batch_id=batch.id, inventory_lot_id=lot.id,
            recipe_component_id=reservation.recipe_component_id, quantity=reservation.quantity,
        ))
        audit(batch.user_id, "InventoryLot", lot.id, "CONSUMED",
              new={"batch_id": batch.identifier, "quantity": num(reservation.quantity)})
    promote_successor_lots(batch, depleted_active_lots, consumed_lots_by_item)


def promote_successor_lots(batch, depleted_active_lots, consumed_lots_by_item):
    for depleted_lot in depleted_active_lots:
        successors = [
            lot for lot in consumed_lots_by_item.get(depleted_lot.item_id, {}).values()
            if lot.id != depleted_lot.id and not lot.depleted and not lot.active
        ]
        if not successors:
            continue

        existing_active = InventoryLot.query.filter(
            InventoryLot.user_id == batch.user_id,
            InventoryLot.item_id == depleted_lot.item_id,
            InventoryLot.active.is_(True),
            InventoryLot.depleted.is_(False),
        ).first()
        if existing_active:
            audit(
                batch.user_id,
                "InventoryLot",
                depleted_lot.id,
                "PROMOTION_SKIPPED",
                new={
                    "batch_id": batch.identifier,
                    "existing_active_lot_id": existing_active.id,
                    "candidate_lot_ids": [lot.id for lot in successors],
                },
                notes="Successor promotion skipped because another active lot already exists.",
            )
            continue

        if len(successors) > 1:
            audit(
                batch.user_id,
                "InventoryLot",
                depleted_lot.id,
                "PROMOTION_SKIPPED",
                new={
                    "batch_id": batch.identifier,
                    "candidate_lot_ids": [lot.id for lot in successors],
                },
                notes="Successor promotion skipped because multiple consumed lots are eligible.",
            )
            continue

        successor = successors[0]
        successor.active = True
        mark_lot_opened_if_drawn(successor)
        audit(
            batch.user_id,
            "InventoryLot",
            successor.id,
            "PROMOTED",
            previous={"active": False},
            new={
                "active": True,
                "opened_on": successor.opened_on.isoformat() if successor.opened_on else None,
                "batch_id": batch.identifier,
                "previous_lot_id": depleted_lot.id,
            },
            notes="Automatically promoted after committed batch consumption depleted the active lot.",
        )


def live_container_quantity(container):
    if container.state in {"EMPTY", "USED"}:
        return 0
    quantity = db.session.query(func.coalesce(func.sum(ContainerAssignment.quantity), 0)).filter_by(
        user_id=container.user_id, container_id=container.id
    ).scalar()
    return int(quantity or 0)


def derived_batch_storage_state(batch):
    assignments = ContainerAssignment.query.filter_by(user_id=batch.user_id, batch_id=batch.id).all()
    assigned_quantity = sum(assignment.quantity for assignment in assignments)
    depleted_quantity = int(batch.container_depleted_quantity or 0)
    if depleted_quantity <= 0 and (not assignments or assigned_quantity <= 0):
        return "PRODUCED"

    depleted_states = {"PARTIALLY USED", "USED", "EMPTY"}
    has_depleted_container = depleted_quantity > 0 or any(
        assignment.container.state in depleted_states for assignment in assignments
    )
    all_assigned_containers_depleted = all(
        assignment.container.state in {"USED", "EMPTY"} for assignment in assignments
    )
    total_accounted_quantity = assigned_quantity + depleted_quantity

    if has_depleted_container:
        if total_accounted_quantity >= batch.iterations and all_assigned_containers_depleted:
            return "DEPLETED"
        return "PARTIALLY DEPLETED"
    if total_accounted_quantity >= batch.iterations:
        return "IN STORAGE"
    return "PARTIALLY IN STORAGE"


def update_batch_storage_state(batch):
    if batch.state in {"UNDER PRODUCTION", "CANCELLED", "DECOMMISSIONED"}:
        return
    target = derived_batch_storage_state(batch)
    if batch.state == target:
        return
    previous = batch.state
    batch.state = target
    audit(
        batch.user_id,
        "Batch",
        batch.identifier,
        "STATE_CHANGED",
        {"state": previous},
        {"state": target},
        notes="Automatically updated from container assignments.",
    )


def reconcile_batch_from_container_assignments(batch):
    assigned_quantity = db.session.query(func.coalesce(func.sum(ContainerAssignment.quantity), 0)).filter_by(
        user_id=batch.user_id, batch_id=batch.id
    ).scalar()
    if int(assigned_quantity or 0) <= 0:
        return False
    changed = False
    if batch.state == "UNDER PRODUCTION":
        reserved = [reservation for reservation in batch.reservations if reservation.status == "RESERVED"]
        if reserved:
            commit_batch_inventory(batch)
            changed = True
    if batch.state not in {"CANCELLED", "DECOMMISSIONED"}:
        target = derived_batch_storage_state(batch)
        if batch.state != target:
            previous = batch.state
            batch.state = target
            audit(
                batch.user_id,
                "Batch",
                batch.identifier,
                "STATE_CHANGED",
                {"state": previous},
                {"state": target},
                notes="Reconciled from existing container assignments.",
            )
            changed = True
    return changed


def mark_lot_opened_if_drawn(lot):
    """Set the system-managed opened date once an active lot has inventory drawdown."""
    has_drawdown = lot.reserved_quantity > 0 or lot.consumed_quantity > 0
    if lot.active and lot.opened_on is None and has_drawdown:
        lot.opened_on = utcnow().date()
        audit(
            lot.user_id, "InventoryLot", lot.id, "OPENED",
            previous={"opened_on": None},
            new={"opened_on": lot.opened_on.isoformat()},
            notes="Automatically marked opened on first drawdown while active.",
        )


def store_file_bytes(app, user_id, filename, content, content_type=None, purpose="GENERAL", entity_type=None, entity_id=None, description=None, storage_folder=None):
    safe_name = secure_filename(filename or "") or "upload.bin"
    folder_parts = storage_folder_parts(storage_folder, purpose, entity_type)
    prefix = "/".join(folder_parts)
    filename_limit = max(40, 300 - len(prefix))
    storage_key = f"{prefix}/{uuid.uuid4().hex}-{safe_name[:filename_limit]}"
    path = os.path.join(app.config["FILE_STORAGE_DIR"], *storage_key.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as output:
        output.write(content)
    record = StoredFile(
        user_id=user_id,
        original_filename=filename or safe_name,
        storage_key=storage_key,
        content_type=content_type or "application/octet-stream",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        purpose=(purpose or "GENERAL").strip().upper(),
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        description=description,
    )
    db.session.add(record)
    db.session.flush()
    audit(
        user_id,
        "StoredFile",
        record.id,
        "CREATED",
        new=stored_file_json(record),
    )
    return record


def stored_file_path(app, record):
    root = os.path.abspath(app.config["FILE_STORAGE_DIR"])
    path = os.path.abspath(os.path.join(root, *record.storage_key.split("/")))
    if os.path.commonpath([root, path]) != root:
        raise DomainError("validation_error", "Stored file path is invalid")
    return path


def storage_folder_parts(storage_folder, purpose, entity_type):
    if storage_folder:
        raw_parts = storage_folder if isinstance(storage_folder, (list, tuple)) else (storage_folder,)
    elif entity_type:
        raw_parts = (entity_storage_folder(entity_type),)
    else:
        raw_parts = ((purpose or "general").strip().lower(),)
    parts = []
    for part in raw_parts:
        safe_part = secure_filename(str(part).strip().lower())[:80]
        if safe_part:
            parts.append(safe_part)
    return parts or ["general"]


def entity_storage_folder(entity_type):
    folders = {
        "Batch": "batches",
        "Recipe": "recipes",
        "Item": "items",
        "InventoryLot": "inventory",
        "StorageContainer": "containers",
        "PerformanceRecord": "batches",
    }
    name = str(entity_type).strip()
    return folders.get(name, f"{name.lower()}s")


def performance_json(record):
    if not record:
        return None
    return {
        "id": record.id, "batch_id": record.batch.identifier,
        "recorded_on": record.recorded_on.isoformat() if record.recorded_on else None,
        "firearm": record.firearm, "barrel_length": num(record.barrel_length),
        "distance": num(record.distance), "group_size": num(record.group_size),
        "shot_count": record.shot_count, "velocity_average": num(record.velocity_average),
        "velocity_minimum": num(record.velocity_minimum), "velocity_maximum": num(record.velocity_maximum),
        "standard_deviation": num(record.standard_deviation), "extreme_spread": num(record.extreme_spread),
        "temperature": num(record.temperature), "weather_notes": record.weather_notes,
        "reliability_notes": record.reliability_notes, "pressure_sign_notes": record.pressure_sign_notes,
        "recoil_perception": record.recoil_perception, "accuracy_perception": record.accuracy_perception,
        "cleanliness_perception": record.cleanliness_perception, "subjective_rating": record.subjective_rating,
        "notes": record.notes, "raw_data": record.raw_data, "processed_data": record.processed_data or {},
        "edited": record.edited, "created_at": record.created_at.isoformat(), "updated_at": record.updated_at.isoformat(),
    }


def inventory_adjustment_json(adjustment):
    return {
        "id": adjustment.id,
        "inventory_lot_id": adjustment.inventory_lot_id,
        "created_at": adjustment.created_at.isoformat(),
        "quantity_change": num(adjustment.quantity_change),
        "unit": adjustment.unit,
        "available_before": num(adjustment.available_before),
        "available_after": num(adjustment.available_after),
        "reason": adjustment.reason,
        "notes": adjustment.notes,
    }


def recipe_aggregate(user_id, recipe_id):
    records = (
        PerformanceRecord.query.join(Batch, Batch.id == PerformanceRecord.batch_id)
        .filter(Batch.user_id == user_id, Batch.recipe_id == recipe_id).all()
    )
    batches = Batch.query.filter_by(user_id=user_id, recipe_id=recipe_id).all()
    def average(field):
        values = [Decimal(getattr(record, field)) for record in records if getattr(record, field) is not None]
        return num(sum(values) / len(values)) if values else None
    moa_values = []
    for record in records:
        if record.group_size is None or record.distance is None or record.distance <= 0:
            continue
        moa_values.append(Decimal(record.group_size) / (Decimal(record.distance) * Decimal("1.047") / Decimal("100")))
    return {
        "batch_count": len(batches), "performance_record_count": len(records),
        "total_rounds_produced": sum(batch.iterations for batch in batches if batch.state != "CANCELLED"),
        "average_velocity": average("velocity_average"),
        "average_standard_deviation": average("standard_deviation"),
        "average_extreme_spread": average("extreme_spread"),
        "average_moa": num(sum(moa_values) / len(moa_values)) if moa_values else None,
        "average_rating": average("subjective_rating"),
        "records": [performance_json(record) for record in records],
    }


def container_json(container, user_id):
    assignments = ContainerAssignment.query.filter_by(user_id=user_id, container_id=container.id).all()
    total_quantity = live_container_quantity(container)
    result = {
        "id": container.id, "identifier": container.identifier, "name": container.name,
        "cartridge_limit": container.cartridge_limit,
        "description": container.description, "state": container.state, "notes": container.notes,
        "total_quantity": total_quantity,
        "remaining_capacity": (
            max(container.cartridge_limit - total_quantity, 0)
            if container.cartridge_limit is not None else None
        ),
        "assignments": [
            {
                "id": assignment.id, "batch_id": assignment.batch.identifier,
                "batch_slug": assignment.batch.slug, "batch_state": assignment.batch.state,
                "recipe": assignment.batch.recipe.title, "quantity": assignment.quantity,
                "batch_quantity": assignment.batch.iterations,
            } for assignment in assignments
        ],
    }
    result.update(container_edit_state(container))
    return result


def audit_json(entry):
    return {
        "id": entry.id, "created_at": entry.created_at.isoformat(),
        "entity_type": entry.entity_type, "entity_id": entry.entity_id,
        "action": entry.action, "previous_value": entry.previous_value,
        "new_value": entry.new_value, "notes": entry.notes,
    }


def export_rows(entity, user_id):
    if entity == "items":
        return [item_json(item) for item in Item.query.filter_by(user_id=user_id).all()]
    if entity == "inventory":
        return [lot_json(lot) for lot in InventoryLot.query.filter_by(user_id=user_id).all()]
    if entity == "recipes":
        return [recipe_json(recipe) for recipe in Recipe.query.filter_by(user_id=user_id).all()]
    if entity == "batches":
        return [batch_json(batch) for batch in Batch.query.filter_by(user_id=user_id).all()]
    if entity == "containers":
        return [container_json(container, user_id) for container in StorageContainer.query.filter_by(user_id=user_id).all()]
    if entity == "performance":
        return [performance_json(record) for record in PerformanceRecord.query.filter_by(user_id=user_id).all()]
    if entity == "audit":
        return [audit_json(entry) for entry in AuditLog.query.filter_by(user_id=user_id).all()]
    raise DomainError("validation_error", "Unknown export entity")
