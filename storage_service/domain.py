from __future__ import annotations

import hashlib
import json
import random
import secrets
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .models import AuditLog, UserAcknowledgement, db

POWDER_TO_GRAINS = {
    "grain": Decimal("1"),
    "grains": Decimal("1"),
    "gr": Decimal("1"),
    "ounce": Decimal("437.5"),
    "ounces": Decimal("437.5"),
    "oz": Decimal("437.5"),
    "pound": Decimal("7000"),
    "pounds": Decimal("7000"),
    "lb": Decimal("7000"),
    "lbs": Decimal("7000"),
    "gram": Decimal("15.4323584"),
    "grams": Decimal("15.4323584"),
    "g": Decimal("15.4323584"),
    "kilogram": Decimal("15432.3584"),
    "kg": Decimal("15432.3584"),
}
COUNT_UNITS = {"count", "each", "ea", "piece", "pieces"}
MISSING_SOURCE_WARNING = "No source material is attached or referenced."
VERBS = (
    "align", "amber", "brisk", "calm", "cast", "craft", "draw", "forge",
    "mark", "prime", "rapid", "steady", "true", "vault",
)
NOUNS = (
    "anvil", "arrow", "cedar", "comet", "falcon", "field", "harbor",
    "lantern", "oak", "ridge", "spark", "summit", "trail", "vector",
)

RECIPE_TRANSITIONS = {
    "UNDER DEVELOPMENT": {"UNDER TEST"},
    "UNDER TEST": {"UNDER DEVELOPMENT", "APPROVED"},
    "APPROVED": {"UNDER TEST", "RETIRED"},
    "RETIRED": {"UNDER DEVELOPMENT"},
}
BATCH_TRANSITIONS = {
    "UNDER PRODUCTION": {"PRODUCED", "CANCELLED"},
    "PRODUCED": {"DECOMMISSIONED"},
    "PARTIALLY IN STORAGE": {"DECOMMISSIONED"},
    "IN STORAGE": {"DECOMMISSIONED"},
    "PARTIALLY DEPLETED": {"DECOMMISSIONED"},
    "DEPLETED": set(),
    "CANCELLED": set(),
    "DECOMMISSIONED": set(),
}
CONTAINER_TRANSITIONS = {
    "EMPTY": set(),
    "ASSIGNED": {"PARTIALLY USED", "USED", "EMPTY"},
    "PARTIALLY USED": {"USED", "EMPTY"},
    "USED": {"EMPTY"},
}


class DomainError(ValueError):
    def __init__(self, code, message, details=None, status=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.status = status


def as_decimal(value, field="quantity"):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise DomainError("invalid_number", f"{field} must be a number", {field: "invalid"})
    return result


def normalize_quantity(category, quantity, unit):
    quantity = as_decimal(quantity)
    if quantity <= 0:
        raise DomainError("invalid_quantity", "Quantity must be positive", {"quantity": "must be positive"})
    normalized_unit = unit.strip().lower()
    if category.upper() == "POWDER":
        factor = POWDER_TO_GRAINS.get(normalized_unit)
        if factor is None:
            raise DomainError("invalid_unit", "Unsupported powder mass unit", {"unit": unit})
        return (quantity * factor).quantize(Decimal("0.000001")), "grains"
    if normalized_unit not in COUNT_UNITS:
        raise DomainError("invalid_unit", "Count-based items require a count unit", {"unit": unit})
    if quantity != quantity.to_integral_value():
        raise DomainError("invalid_quantity", "Count quantity must be a whole number", {"quantity": str(quantity)})
    return quantity, "count"


def make_slug(exists):
    for _ in range(200):
        slug = f"{random.choice(VERBS)}-{random.choice(NOUNS)}"
        if not exists(slug):
            return slug
    return f"craft-{secrets.token_hex(4)}"


def new_public_token():
    return secrets.token_urlsafe(24)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def audit(user_id, entity_type, entity_id, action, previous=None, new=None, notes=None):
    db.session.add(
        AuditLog(
            user_id=user_id,
            entity_type=entity_type,
            entity_id=str(entity_id),
            action=action,
            previous_value=previous,
            new_value=new,
            notes=notes,
        )
    )


def acknowledge(user_id, entity_type, entity_id, acknowledgement_type, text, warning=None):
    record = UserAcknowledgement(
        user_id=user_id,
        entity_type=entity_type,
        entity_id=str(entity_id),
        acknowledgement_type=acknowledgement_type,
        text_version=text,
        related_warning=warning,
    )
    db.session.add(record)
    audit(user_id, entity_type, entity_id, "ACKNOWLEDGED", new={"type": acknowledgement_type})
    return record


def recipe_warnings(recipe):
    roles = {component.role.upper() for component in recipe.components}
    warnings = []
    if not recipe.cartridge:
        warnings.append("Cartridge/caliber is required.")
    for role in ("BULLET", "POWDER", "PRIMER", "CASE"):
        if role not in roles:
            warnings.append(f"{role.title()} component is missing.")
    if not recipe.sources:
        warnings.append(MISSING_SOURCE_WARNING)
    return warnings


def ensure_transition(current, target, transitions, entity):
    if target not in transitions.get(current, set()):
        raise DomainError(
            "invalid_transition",
            f"{entity} cannot transition from {current} to {target}",
            {"state": target},
        )


def json_safe(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return value


def snapshot(model, fields):
    return {field: json_safe(getattr(model, field)) for field in fields}


def parse_json_object(value, field):
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        raise DomainError("invalid_json", f"{field} must be valid JSON", {field: "invalid JSON"})
    if not isinstance(parsed, dict):
        raise DomainError("invalid_json", f"{field} must be a JSON object", {field: "must be an object"})
    return parsed
