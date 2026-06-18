from __future__ import annotations

from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint, UniqueConstraint

db = SQLAlchemy()


def utcnow():
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class User(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(320), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(120))
    reset_required = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class AuthSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    revoked_at = db.Column(db.DateTime(timezone=True))


class Item(db.Model, TimestampMixin):
    __table_args__ = (UniqueConstraint("user_id", "id", name="uq_item_owner_id"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    category = db.Column(db.String(40), nullable=False)
    manufacturer = db.Column(db.String(120), nullable=False)
    product_line = db.Column(db.String(120))
    name = db.Column(db.String(160), nullable=False)
    characteristics = db.Column(db.String(255))
    caliber = db.Column(db.String(80))
    bullet_weight = db.Column(db.Numeric(10, 3))
    bullet_type = db.Column(db.String(80))
    primer_type = db.Column(db.String(80))
    powder_type = db.Column(db.String(80))
    attributes = db.Column(db.JSON, nullable=False, default=dict)
    notes = db.Column(db.Text)
    archived = db.Column(db.Boolean, nullable=False, default=False)


class InventoryLot(db.Model, TimestampMixin):
    __table_args__ = (
        CheckConstraint("original_quantity > 0", name="ck_lot_original_positive"),
        CheckConstraint("normalized_quantity >= 0", name="ck_lot_normalized_nonnegative"),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey("item.id"), nullable=False, index=True)
    manufacturer_lot = db.Column(db.String(120))
    acquired_on = db.Column(db.Date)
    opened_on = db.Column(db.Date)
    original_quantity = db.Column(db.Numeric(18, 6), nullable=False)
    original_unit = db.Column(db.String(20), nullable=False)
    normalized_quantity = db.Column(db.Numeric(18, 6), nullable=False)
    normalized_unit = db.Column(db.String(20), nullable=False)
    reserved_quantity = db.Column(db.Numeric(18, 6), nullable=False, default=0)
    consumed_quantity = db.Column(db.Numeric(18, 6), nullable=False, default=0)
    active = db.Column(db.Boolean, nullable=False, default=False)
    depleted = db.Column(db.Boolean, nullable=False, default=False)
    notes = db.Column(db.Text)
    item = db.relationship("Item")

    @property
    def available_quantity(self):
        return self.normalized_quantity - self.reserved_quantity - self.consumed_quantity


class Recipe(db.Model, TimestampMixin):
    __table_args__ = (UniqueConstraint("user_id", "slug", name="uq_recipe_user_slug"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    slug = db.Column(db.String(80), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    state = db.Column(db.String(30), nullable=False, default="UNDER DEVELOPMENT")
    cartridge = db.Column(db.String(80), nullable=False)
    overall_length = db.Column(db.Numeric(10, 4))
    case_length = db.Column(db.Numeric(10, 4))
    crimp_type = db.Column(db.String(80))
    seating_depth = db.Column(db.Numeric(10, 4))
    source_notes = db.Column(db.Text)
    notes = db.Column(db.Text)
    public_notes = db.Column(db.Text)
    public = db.Column(db.Boolean, nullable=False, default=False)
    public_token = db.Column(db.String(64), unique=True, index=True)
    archived = db.Column(db.Boolean, nullable=False, default=False)
    components = db.relationship(
        "RecipeComponent", cascade="all, delete-orphan", order_by="RecipeComponent.id"
    )
    sources = db.relationship("SourceMaterial", cascade="all, delete-orphan")


class RecipeComponent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey("recipe.id"), nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey("item.id"), nullable=False)
    role = db.Column(db.String(40), nullable=False)
    quantity = db.Column(db.Numeric(18, 6), nullable=False)
    unit = db.Column(db.String(20), nullable=False)
    alternative_group = db.Column(db.String(60))
    item = db.relationship("Item")


class SourceMaterial(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey("recipe.id"), nullable=False, index=True)
    kind = db.Column(db.String(40), nullable=False)
    citation = db.Column(db.String(255))
    url = db.Column(db.String(1000))
    page = db.Column(db.String(40))
    file_name = db.Column(db.String(255))
    notes = db.Column(db.Text)


class Batch(db.Model, TimestampMixin):
    __table_args__ = (UniqueConstraint("user_id", "slug", name="uq_batch_user_slug"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey("recipe.id"), nullable=False, index=True)
    slug = db.Column(db.String(80), nullable=False)
    iterations = db.Column(db.Integer, nullable=False)
    state = db.Column(db.String(30), nullable=False, default="UNDER PRODUCTION")
    notes = db.Column(db.Text)
    locked = db.Column(db.Boolean, nullable=False, default=True)
    recipe = db.relationship("Recipe")
    reservations = db.relationship(
        "BatchInventoryReservation", cascade="all, delete-orphan", order_by="BatchInventoryReservation.id"
    )
    consumptions = db.relationship(
        "BatchInventoryConsumption", cascade="all, delete-orphan", order_by="BatchInventoryConsumption.id"
    )


class BatchInventoryReservation(db.Model, TimestampMixin):
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_reservation_positive"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("batch.id"), nullable=False, index=True)
    inventory_lot_id = db.Column(db.Integer, db.ForeignKey("inventory_lot.id"), nullable=False)
    recipe_component_id = db.Column(db.Integer, db.ForeignKey("recipe_component.id"), nullable=False)
    quantity = db.Column(db.Numeric(18, 6), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="RESERVED")
    inventory_lot = db.relationship("InventoryLot")
    recipe_component = db.relationship("RecipeComponent")


class BatchInventoryConsumption(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("batch.id"), nullable=False, index=True)
    inventory_lot_id = db.Column(db.Integer, db.ForeignKey("inventory_lot.id"), nullable=False)
    recipe_component_id = db.Column(db.Integer, db.ForeignKey("recipe_component.id"), nullable=False)
    quantity = db.Column(db.Numeric(18, 6), nullable=False)
    inventory_lot = db.relationship("InventoryLot")


class InventoryReturn(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("batch.id"), nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey("item.id"), nullable=False)
    source_lot_id = db.Column(db.Integer, db.ForeignKey("inventory_lot.id"), nullable=False)
    destination_lot_id = db.Column(db.Integer, db.ForeignKey("inventory_lot.id"))
    quantity_returned = db.Column(db.Numeric(18, 6), nullable=False, default=0)
    quantity_lost = db.Column(db.Numeric(18, 6), nullable=False, default=0)
    reason = db.Column(db.String(160), nullable=False)
    notes = db.Column(db.Text)


class StorageContainer(db.Model, TimestampMixin):
    __table_args__ = (UniqueConstraint("user_id", "identifier", name="uq_container_user_identifier"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    identifier = db.Column(db.String(80), nullable=False)
    name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text)
    state = db.Column(db.String(30), nullable=False, default="EMPTY")
    notes = db.Column(db.Text)


class ContainerAssignment(db.Model, TimestampMixin):
    __table_args__ = (UniqueConstraint("container_id", "batch_id", name="uq_container_batch"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    container_id = db.Column(db.Integer, db.ForeignKey("storage_container.id"), nullable=False)
    batch_id = db.Column(db.Integer, db.ForeignKey("batch.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    container = db.relationship("StorageContainer")
    batch = db.relationship("Batch")


class PerformanceRecord(db.Model, TimestampMixin):
    __table_args__ = (UniqueConstraint("batch_id", name="uq_performance_batch"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("batch.id"), nullable=False, index=True)
    recorded_on = db.Column(db.Date)
    firearm = db.Column(db.String(160))
    barrel_length = db.Column(db.Numeric(10, 3))
    distance = db.Column(db.Numeric(10, 3))
    group_size = db.Column(db.Numeric(10, 3))
    shot_count = db.Column(db.Integer)
    velocity_average = db.Column(db.Numeric(10, 3))
    velocity_minimum = db.Column(db.Numeric(10, 3))
    velocity_maximum = db.Column(db.Numeric(10, 3))
    standard_deviation = db.Column(db.Numeric(10, 3))
    extreme_spread = db.Column(db.Numeric(10, 3))
    temperature = db.Column(db.Numeric(10, 3))
    weather_notes = db.Column(db.Text)
    reliability_notes = db.Column(db.Text)
    pressure_sign_notes = db.Column(db.Text)
    recoil_perception = db.Column(db.Integer)
    accuracy_perception = db.Column(db.Integer)
    cleanliness_perception = db.Column(db.Integer)
    subjective_rating = db.Column(db.Integer)
    notes = db.Column(db.Text)
    raw_data = db.Column(db.Text)
    processed_data = db.Column(db.JSON, nullable=False, default=dict)
    edited = db.Column(db.Boolean, nullable=False, default=False)


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    entity_type = db.Column(db.String(60), nullable=False)
    entity_id = db.Column(db.String(80), nullable=False)
    action = db.Column(db.String(80), nullable=False)
    previous_value = db.Column(db.JSON)
    new_value = db.Column(db.JSON)
    notes = db.Column(db.Text)


class UserAcknowledgement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    entity_type = db.Column(db.String(60), nullable=False)
    entity_id = db.Column(db.String(80), nullable=False)
    acknowledgement_type = db.Column(db.String(80), nullable=False)
    text_version = db.Column(db.String(255), nullable=False)
    related_warning = db.Column(db.String(255))

