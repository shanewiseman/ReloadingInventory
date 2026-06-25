from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pytest

pytest.importorskip("selenium", reason="selenium package is not installed")

from selenium.common.exceptions import NoAlertPresentException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.ui import WebDriverWait


pytestmark = pytest.mark.selenium


DEFAULT_GARMIN_FIT_FILE = Path(__file__).resolve().parents[1] / "fixtures" / "garmin" / "session_3.fit"
GARMIN_FIT_FILE = Path(os.getenv("GARMIN_E2E_FIT_FILE", str(DEFAULT_GARMIN_FIT_FILE)))
GARMIN_IMPORTED_FIELDS = {
    "recorded_on": "2024-07-27",
    "shot_count": "16",
    "velocity_average": "1717.551",
    "velocity_minimum": "1612.428",
    "velocity_maximum": "1791.969",
    "standard_deviation": "47.828",
    "extreme_spread": "179.541",
}


ITEMS = [
    {
        "category": "BULLET",
        "manufacturer": "Hornady",
        "product_line": "XTP",
        "name": "125 gr JHP",
        "characteristics": ".357 jacketed hollow point",
        "caliber": ".357",
        "bullet_weight": "125",
        "bullet_type": "JHP",
        "attributes": '{"diameter": ".357", "sku": "35710"}',
        "notes": "Lightweight magnum test bullet.",
        "lots": [
            {"lot": "HDY-125-ACT", "quantity": "500", "unit": "count", "active": True},
            {"lot": "HDY-125-RES", "quantity": "250", "unit": "count", "active": False},
        ],
    },
    {
        "category": "BULLET",
        "manufacturer": "Hornady",
        "product_line": "XTP",
        "name": "158 gr JHP",
        "characteristics": ".357 jacketed hollow point",
        "caliber": ".357",
        "bullet_weight": "158",
        "bullet_type": "JHP",
        "attributes": '{"diameter": ".357", "sku": "35750"}',
        "notes": "Primary recipe bullet.",
        "lots": [
            {"lot": "HDY-158-ACT", "quantity": "800", "unit": "count", "cost": "80.00", "active": True},
            {"lot": "HDY-158-RES", "quantity": "300", "unit": "count", "cost": "30.00", "active": False},
        ],
    },
    {
        "category": "BULLET",
        "manufacturer": "Speer",
        "product_line": "DeepCurl",
        "name": "180 gr JSP",
        "characteristics": ".357 jacketed soft point",
        "caliber": ".357",
        "bullet_weight": "180",
        "bullet_type": "JSP",
        "attributes": '{"diameter": ".357", "sku": "4228"}',
        "notes": "Heavy bullet recipe option.",
        "lots": [
            {"lot": "SPR-180-ACT", "quantity": "600", "unit": "count", "cost": "90.00", "active": True},
            {"lot": "SPR-180-RES", "quantity": "200", "unit": "count", "active": False},
        ],
    },
    {
        "category": "POWDER",
        "manufacturer": "Hodgdon",
        "product_line": "H110",
        "name": "H110",
        "characteristics": "Spherical magnum pistol powder",
        "powder_type": "Spherical",
        "attributes": '{"canister": "1 lb", "sku": "H1101"}',
        "notes": "Magnum revolver powder.",
        "lots": [
            {"lot": "H110-ACT", "quantity": "1", "unit": "pounds", "cost": "70.00", "active": True},
            {"lot": "H110-RES", "quantity": "8", "unit": "ounces", "cost": "40.00", "active": False},
        ],
    },
    {
        "category": "POWDER",
        "manufacturer": "Alliant",
        "product_line": "2400",
        "name": "2400",
        "characteristics": "Magnum handgun powder",
        "powder_type": "Flake",
        "attributes": '{"canister": "1 lb", "sku": "24001"}',
        "notes": "Second recipe powder.",
        "lots": [
            {"lot": "2400-ACT", "quantity": "1", "unit": "pounds", "active": True},
            {"lot": "2400-RES", "quantity": "8", "unit": "ounces", "active": False},
        ],
    },
    {
        "category": "PRIMER",
        "manufacturer": "CCI",
        "product_line": "No. 550",
        "name": "Small Pistol Magnum Primers",
        "characteristics": "Small pistol magnum primer",
        "primer_type": "Small pistol magnum",
        "attributes": '{"brick": "1000", "sku": "550"}',
        "notes": "Magnum primer option.",
        "lots": [
            {"lot": "CCI550-ACT", "quantity": "1000", "unit": "count", "cost": "100.00", "active": True, "weight_grains": "3.500"},
            {"lot": "CCI550-RES", "quantity": "1000", "unit": "count", "cost": "95.00", "active": False, "weight_grains": "3.500"},
        ],
    },
    {
        "category": "PRIMER",
        "manufacturer": "Federal",
        "product_line": "No. 100",
        "name": "Small Pistol Primers",
        "characteristics": "Small pistol standard primer",
        "primer_type": "Small pistol standard",
        "attributes": '{"brick": "1000", "sku": "100"}',
        "notes": "Standard primer option.",
        "lots": [
            {"lot": "FED100-ACT", "quantity": "1000", "unit": "count", "cost": "90.00", "active": True, "weight_grains": "3.400"},
            {"lot": "FED100-RES", "quantity": "1000", "unit": "count", "active": False, "weight_grains": "3.400"},
        ],
    },
    {
        "category": "CASE",
        "manufacturer": "Starline",
        "product_line": "Nickel",
        "name": ".357 Magnum Nickel Brass",
        "characteristics": "Nickel plated straight wall revolver case",
        "caliber": ".357 Magnum",
        "attributes": '{"finish": "nickel", "sku": "357MEU"}',
        "notes": "Nickel plated brass.",
        "lots": [
            {"lot": "STAR-NI-ACT", "quantity": "1000", "unit": "count", "cost": "200.00", "active": True, "weight_grains": "75.000"},
            {"lot": "STAR-NI-RES", "quantity": "500", "unit": "count", "cost": "100.00", "active": False, "weight_grains": "75.000"},
        ],
    },
    {
        "category": "CASE",
        "manufacturer": "Starline",
        "product_line": "Brass",
        "name": ".357 Magnum Plain Brass",
        "characteristics": "Plain brass straight wall revolver case",
        "caliber": ".357 Magnum",
        "attributes": '{"finish": "brass", "sku": "357MAG"}',
        "notes": "Plain brass cases.",
        "lots": [
            {"lot": "STAR-BR-ACT", "quantity": "1000", "unit": "count", "cost": "180.00", "active": True, "weight_grains": "74.500"},
            {"lot": "STAR-BR-RES", "quantity": "500", "unit": "count", "active": False, "weight_grains": "74.500"},
        ],
    },
    {
        "category": "OTHER",
        "manufacturer": "MTM",
        "product_line": "Load Labels",
        "name": "Adhesive Cartridge Labels",
        "characteristics": "Traceability label stock",
        "attributes": '{"color": "white", "sheets": 25}',
        "notes": "Workflow support item.",
        "lots": [
            {"lot": "MTM-LBL-ACT", "quantity": "25", "unit": "count", "active": True, "weight_grains": "1.000"},
            {"lot": "MTM-LBL-RES", "quantity": "10", "unit": "count", "active": False, "weight_grains": "1.000"},
        ],
    },
]


RECIPES = [
    {
        "title": "357 Magnum 158 XTP H110",
        "cartridge": ".357 Magnum",
        "overall_length": "1.5900",
        "case_length": "1.2800",
        "crimp_type": "Roll crimp",
        "seating_depth": "0.3000",
        "source_notes": "Cross-checked against published manufacturer data.",
        "notes": "Selenium workflow recipe A.",
        "public_notes": "Browser workflow test recipe.",
        "components": {
            "BULLET": ("Hornady", "158 gr JHP", "1", "count", "HDY-158-ACT"),
            "POWDER": ("Hodgdon", "H110", "15.0", "grains", "H110-ACT"),
            "PRIMER": ("CCI", "Small Pistol Magnum Primers", "1", "count", "CCI550-ACT"),
            "CASE": ("Starline", ".357 Magnum Nickel Brass", "1", "count", "STAR-NI-ACT"),
        },
        "source": "Hodgdon Annual Manual .357 Magnum H110 data",
    },
    {
        "title": "357 Magnum 180 DeepCurl 2400",
        "cartridge": ".357 Magnum",
        "overall_length": "1.5850",
        "case_length": "1.2800",
        "crimp_type": "Firm roll crimp",
        "seating_depth": "0.3200",
        "source_notes": "Published manual data reference entered by user.",
        "notes": "Selenium workflow recipe B.",
        "public_notes": "Second browser workflow test recipe.",
        "components": {
            "BULLET": ("Speer", "180 gr JSP", "1", "count", "SPR-180-ACT"),
            "POWDER": ("Alliant", "2400", "13.5", "grains", "2400-ACT"),
            "PRIMER": ("Federal", "Small Pistol Primers", "1", "count", "FED100-ACT"),
            "CASE": ("Starline", ".357 Magnum Plain Brass", "1", "count", "STAR-BR-ACT"),
        },
        "source": "Alliant published .357 Magnum 2400 data",
    },
]


SUCCESSOR_PROMOTION_RECIPE = {
    "title": "357 Magnum 125 XTP Successor Promotion",
    "cartridge": ".357 Magnum",
    "overall_length": "1.5750",
    "case_length": "1.2800",
    "crimp_type": "Roll crimp",
    "seating_depth": "0.2900",
    "source_notes": "Published source reference entered for successor lot workflow.",
    "notes": "Selenium successor lot promotion recipe.",
    "public_notes": "Successor lot promotion workflow test recipe.",
    "components": {
        "BULLET": ("Hornady", "125 gr JHP", "1", "count", "HDY-125-ACT"),
        "POWDER": ("Hodgdon", "H110", "1", "grains", "H110-ACT"),
        "PRIMER": ("CCI", "Small Pistol Magnum Primers", "1", "count", "CCI550-ACT"),
        "CASE": ("Starline", ".357 Magnum Nickel Brass", "1", "count", "STAR-NI-ACT"),
    },
    "source": "Published .357 Magnum 125 XTP data",
}


@pytest.mark.usefixtures("driver")
def test_357_magnum_browser_workflow(driver, app_base_url, e2e_user, selenium_slow_seconds):
    app = BrowserApp(driver, app_base_url, selenium_slow_seconds)
    app.reset_browser_session()
    run_suffix = e2e_user["email"].split("@", 1)[0].rsplit("-", 1)[-1][:6].upper()
    container_a = f"357-A-{run_suffix}"
    container_b = f"357-MIX-{run_suffix}"

    app.register(e2e_user)
    app.login(e2e_user["email"], "wrong-password")
    app.assert_flash("Email or password is incorrect", category="error")
    app.login(e2e_user["email"], e2e_user["password"])
    app.logout()
    app.login(e2e_user["email"], e2e_user["password"])

    for item in ITEMS:
        app.create_item(item)
    app.assert_dashboard_metric("Items", len(ITEMS))

    for item in ITEMS:
        for lot in item["lots"]:
            app.create_inventory_lot(item, lot)
    app.assert_dashboard_metric("Current lots", len(ITEMS) * 2)
    app.assert_inventory_lot_cost("H110-ACT", "$70.00", "$0.010000 / grains")
    app.assert_inventory_lot_cost("2400-ACT", "Not set")

    recipes = [app.create_approved_recipe(recipe) for recipe in RECIPES]
    app.exercise_related_recipe_flows(recipes[0])
    promotion_recipe = app.create_approved_recipe(SUCCESSOR_PROMOTION_RECIPE)
    app.exercise_successor_lot_promotion(promotion_recipe)

    qa_priced_batch = app.create_batch(recipes[0], 10, "QA and pricing sample: fully costed batch.")
    app.assert_transition_requires_qa(qa_priced_batch, required=3, completed=0)
    app.assert_batch_cost(qa_priced_batch, "$0.5500", "$5.50 reserved")
    app.assert_batch_list_cost(qa_priced_batch, "$0.5500")
    app.save_qa_measurements(qa_priced_batch, completed_weight="252.000", overall_length="1.5920", required=3)
    app.transition_batch(qa_priced_batch, "PRODUCED")
    app.assert_batch_cost(qa_priced_batch, "$0.5500", "$5.50 consumed")
    app.assert_qa_measurement_results(qa_priced_batch, "0.500 gr", "0.0020 in", "+0.500 gr", "+0.0020 in")

    batches = [
        app.create_batch(recipes[0], 8, "Quality sample: full single-container batch."),
        app.create_batch(recipes[0], 5, "Mixed container contribution."),
        app.create_batch(recipes[1], 7, "Leaves one round outside containers."),
    ]
    for batch in batches:
        app.transition_batch(batch, "PRODUCED")
    app.assert_batch_cost(batches[0], "$0.5500", "$4.40 consumed")
    app.assert_batch_cost_unavailable(batches[2])
    app.assert_batch_list_cost(batches[0], "$0.5500")
    app.assert_batch_list_cost(batches[2], "Unavailable")
    app.assert_recipe_card_cost(recipes[0], "$0.5500")
    app.assert_recipe_card_cost_unavailable(recipes[1])

    app.save_performance_record(batches[0])

    app.create_container(container_a, "Eight round hinged box", 8)
    app.create_container(container_b, "Eleven round mixed test box", 11)

    app.assign_container(container_a, batches[0], 8)
    app.assign_container(container_b, batches[1], 5)
    app.assign_container_expect_overfill_error(container_b, batches[2], 7)
    app.assign_container(container_b, batches[2], 6, acknowledge_mixed=True)

    app.assert_batch_state(batches[0], "IN STORAGE", "8 / 8 cartridges assigned")
    app.assert_batch_state(batches[1], "IN STORAGE", "5 / 5 cartridges assigned")
    app.assert_batch_state(batches[2], "PARTIALLY IN STORAGE", "1 not in containers")

    for container_id in (container_a, container_b):
        app.transition_container(container_id, "PARTIALLY USED")
        app.transition_container(container_id, "USED")
        app.transition_container(container_id, "EMPTY")
        app.assert_container_empty(container_id)

    app.assert_batch_state(batches[0], "DEPLETED", "No containers assigned.")
    app.assert_batch_state(batches[1], "DEPLETED", "No containers assigned.")
    app.assert_batch_state(batches[2], "PARTIALLY DEPLETED", "1 not in containers")
    app.assert_audit_contains("STATE_CHANGED")


class BrowserApp:
    def __init__(self, driver, base_url, slow_seconds=0):
        self.driver = driver
        self.base_url = base_url
        self.slow_seconds = slow_seconds
        self.wait = WebDriverWait(driver, 12)

    def open(self, path):
        self.driver.get(f"{self.base_url}{path}")
        self.pause()

    def reset_browser_session(self):
        self.open("/login")
        self.driver.delete_all_cookies()
        self.open("/login")

    def register(self, user):
        self.open("/register")
        self.fill("display_name", user["display_name"])
        self.fill("email", user["email"])
        self.fill("password", user["password"])
        self.click_button("Create account")
        self.assert_flash("Account created", category="success")

    def login(self, email, password):
        self.open("/login")
        self.fill("email", email)
        self.fill("password", password)
        self.click_button("Sign in")
        self.wait_for_page()

    def logout(self):
        self.click_button("Sign out")
        self.wait.until(EC.url_contains("/login"))

    def create_item(self, item):
        self.open("/items")
        self.open_details("Add item")
        form = self.driver.find_element(By.ID, "item-form")
        Select(form.find_element(By.NAME, "category")).select_by_value(item["category"])
        self.pause()
        self.fill("manufacturer", item["manufacturer"], form)
        self.fill("name", item["name"], form)
        self.fill("product_line", item["product_line"], form)
        self.fill("characteristics", item["characteristics"], form)
        for field in ("caliber", "bullet_weight", "bullet_type", "primer_type", "powder_type"):
            if item.get(field):
                self.wait.until(lambda _driver: form.find_element(By.NAME, field).is_enabled())
                self.fill(field, item[field], form)
        self.open_details("Advanced item attributes")
        self.fill("attributes", item["attributes"], form)
        self.fill("notes", item["notes"], form)
        form.find_element(By.CSS_SELECTOR, "button").click()
        self.pause()
        self.assert_flash("Item created.", category="success")
        self.assert_text(item["name"])

    def create_inventory_lot(self, item, lot):
        self.open("/inventory")
        self.open_details("Add lot")
        form = self.driver.find_element(By.ID, "inventory-lot-form")
        Select(form.find_element(By.ID, "inventory-item-type")).select_by_value(item["category"])
        self.pause()
        radio = self.wait.until(EC.element_to_be_clickable((
            By.XPATH,
            "//label[contains(@class,'item-choice') and "
            f"@data-item-category='{item['category']}' and "
            f".//b[contains(., '{item['manufacturer']}') and contains(., '{item['name']}')]]"
            "//input[@name='item_id']",
        )))
        self.driver.execute_script("arguments[0].click();", radio)
        self.pause()
        self.fill("manufacturer_lot", lot["lot"], form)
        self.fill("quantity", lot["quantity"], form)
        Select(form.find_element(By.NAME, "unit")).select_by_visible_text(lot["unit"])
        if lot.get("cost"):
            self.fill("cost", lot["cost"], form)
        if lot.get("weight_grains"):
            self.fill("weight_grains", lot["weight_grains"], form)
        self.pause()
        self.fill("acquired_on", "2026-01-15", form)
        if lot["active"]:
            checkbox = form.find_element(By.NAME, "active")
            if not checkbox.is_selected():
                checkbox.click()
                self.pause()
        self.fill("notes", f"{lot['lot']} Selenium workflow inventory lot.", form)
        form.find_element(By.CSS_SELECTOR, "button").click()
        self.pause()
        self.assert_flash("Inventory lot created.", category="success")
        self.assert_text(lot["lot"])

    def create_approved_recipe(self, recipe):
        self.open("/recipes")
        form = self.open_details("Create recipe").find_element(By.TAG_NAME, "form")
        self.fill("title", recipe["title"], form)
        self.fill("cartridge", recipe["cartridge"], form)
        self.fill("overall_length", recipe["overall_length"], form)
        self.fill("case_length", recipe["case_length"], form)
        self.fill("crimp_type", recipe["crimp_type"], form)
        self.fill("seating_depth", recipe["seating_depth"], form)
        self.fill("source_notes", recipe["source_notes"], form)
        self.fill("notes", recipe["notes"], form)
        self.fill("public_notes", recipe["public_notes"], form)
        form.find_element(By.NAME, "acknowledge_responsibility").click()
        self.pause()
        form.find_element(By.CSS_SELECTOR, "button").click()
        self.pause()
        self.wait_for_page()
        self.assert_flash("Recipe created", category="success")
        recipe_id = self.driver.current_url.rstrip("/").split("/")[-1]

        for role, component in recipe["components"].items():
            manufacturer, name, quantity, unit, lot = component
            self.add_recipe_component(manufacturer, name, quantity, unit)
        self.add_recipe_source(recipe["source"])
        self.transition_recipe("UNDER TEST")
        self.transition_recipe("APPROVED")
        self.assert_text("APPROVED")
        return {"id": recipe_id, "title": recipe["title"], "components": recipe["components"]}

    def add_recipe_component(self, manufacturer, name, quantity, unit):
        form = self.open_details("Add exact component").find_element(By.TAG_NAME, "form")
        select = Select(form.find_element(By.NAME, "item_id"))
        self.select_option_containing(select, manufacturer, name)
        self.pause()
        if unit == "grains":
            self.fill("powder_quantity", quantity, form)
        else:
            other_inputs = form.find_elements(By.NAME, "other_quantity")
            if other_inputs and other_inputs[0].is_displayed() and other_inputs[0].is_enabled():
                self.fill("other_quantity", quantity, form)
        form.find_element(By.CSS_SELECTOR, "button").click()
        self.pause()
        self.wait_for_page()
        self.assert_flash("Recipe component added.", category="success")

    def add_recipe_source(self, citation):
        form = self.open_details("Add source").find_element(By.CSS_SELECTOR, "[data-source-form]")
        Select(form.find_element(By.NAME, "kind")).select_by_visible_text("Manual")
        self.pause()
        self.fill("citation", citation, form)
        self.fill("page", "42", form)
        self.fill("notes", "Entered by Selenium from a user-supplied source citation.", form)
        form.find_element(By.CSS_SELECTOR, "button").click()
        self.pause()
        self.wait_for_page()
        self.assert_flash("Source material added.", category="success")

    def transition_recipe(self, state):
        form = self.driver.find_element(By.CSS_SELECTOR, "form[action$='/state']")
        Select(form.find_element(By.NAME, "state")).select_by_visible_text(state)
        self.pause()
        form.find_element(By.CSS_SELECTOR, "button").click()
        self.pause()
        self.assert_flash("Recipe state changed.", category="success")

    def exercise_related_recipe_flows(self, recipe):
        self.open(f"/recipes/{recipe['id']}")
        form = self.open_details("Add exact component").find_element(By.TAG_NAME, "form")
        select = Select(form.find_element(By.NAME, "item_id"))
        options = [option.text for option in select.options]
        assert any(option.startswith("OTHER") for option in options), options
        assert not any("BULLET" in option for option in options), options
        assert not any("Hornady" in option and "125 gr JHP" in option for option in options), options

        self.click_button("Create public link")
        self.assert_flash("Recipe sharing updated.", category="success")
        self.driver.find_element(By.LINK_TEXT, "Open public view").click()
        self.pause()
        self.assert_text(recipe["title"])
        self.assert_text("Browser workflow test recipe.")
        self.open(f"/recipes/{recipe['id']}")

    def create_batch(self, recipe, iterations, notes):
        self.open(f"/batches/new?recipe_id={recipe['id']}")
        form = self.driver.find_element(By.CSS_SELECTOR, "form[method='post'].stack")
        self.fill("iterations", str(iterations), form)
        for role, component in recipe["components"].items():
            lot = component[4]
            allocation = self.driver.find_element(
                By.XPATH,
                f"//div[contains(@class,'allocation') and .//b[contains(., '{role}')]]",
            )
            self.select_option_containing(Select(allocation.find_element(By.NAME, f"component_{self.component_id(allocation)}_lot")), lot)
        self.fill("characteristics", notes, form)
        self.fill("notes", notes, form)
        form.find_element(By.CSS_SELECTOR, "button").click()
        self.pause()
        self.wait_for_page()
        self.assert_flash("Batch created and inventory reserved.", category="success")
        batch_id = self.driver.current_url.rstrip("/").split("/")[-1]
        slug = self.driver.find_element(By.CSS_SELECTOR, "h1").text
        self.assert_text("UNDER PRODUCTION")
        return {"id": batch_id, "slug": slug, "iterations": iterations}

    def create_batch_with_replacement_lots(self, recipe, iterations, replacements, notes):
        self.open(f"/batches/new?recipe_id={recipe['id']}")
        form = self.driver.find_element(By.CSS_SELECTOR, "form[method='post'].stack")
        self.fill("iterations", str(iterations), form)
        for role, component in recipe["components"].items():
            default_lot = component[4]
            allocation = self.driver.find_element(
                By.XPATH,
                f"//div[contains(@class,'allocation') and .//b[contains(., '{role}')]]",
            )
            component_id = self.component_id(allocation)
            select = Select(allocation.find_element(By.NAME, f"component_{component_id}_lot"))
            self.select_option_containing(select, default_lot)
            replacement_lot = replacements.get(role)
            if replacement_lot:
                replacement_select = allocation.find_element(By.CSS_SELECTOR, "[data-replacement-select]")
                self.wait.until(lambda _driver: enabled_or_false(replacement_select))
                self.select_option_containing(Select(replacement_select), replacement_lot)
        self.fill("notes", notes, form)
        form.find_element(By.CSS_SELECTOR, "button").click()
        self.pause()
        self.wait_for_page()
        self.assert_flash("Batch created and inventory reserved.", category="success")
        batch_id = self.driver.current_url.rstrip("/").split("/")[-1]
        slug = self.driver.find_element(By.CSS_SELECTOR, "h1").text
        self.assert_text("UNDER PRODUCTION")
        return {"id": batch_id, "slug": slug, "iterations": iterations}

    def exercise_successor_lot_promotion(self, recipe):
        batch = self.create_batch_with_replacement_lots(
            recipe,
            505,
            {"BULLET": "HDY-125-RES"},
            "Consumes the active 125 gr bullet lot and continues into one successor lot.",
        )
        self.assert_inventory_lot_status("HDY-125-ACT", "Active", "0.0 count", "500.0")
        self.assert_inventory_lot_status("HDY-125-RES", "Activate", "Not opened", "5.0")

        self.transition_batch(batch, "PRODUCED")

        self.assert_inventory_lot_status("HDY-125-ACT", "Depleted", "500.0")
        self.assert_inventory_lot_active_and_opened("HDY-125-RES")
        self.assert_audit_contains("PROMOTED")

    def transition_batch(self, batch, state):
        self.open(f"/batches/{batch['id']}")
        select = Select(self.driver.find_element(By.CSS_SELECTOR, "[data-batch-state-form] select[name='state']"))
        select.select_by_visible_text(state)
        try:
            self.driver.switch_to.alert.accept()
        except NoAlertPresentException:
            pass
        self.pause()
        self.assert_flash("Batch state changed.", category="success")
        self.assert_text(state)

    def assert_transition_requires_qa(self, batch, required, completed):
        self.open(f"/batches/{batch['id']}")
        section = self.driver.find_element(By.ID, "qa-measurements")
        assert f"Required sample: {required} of {batch['iterations']} cartridges." in section.text
        assert f"Complete: {completed} / {required}." in section.text
        form = self.driver.find_element(By.CSS_SELECTOR, "[data-batch-state-form]")
        self.driver.execute_script(
            "arguments[0].querySelector('select[name=\"state\"]').value = 'PRODUCED';"
            "arguments[0].submit();",
            form,
        )
        self.pause()
        self.wait_for_page()
        self.assert_flash("QA measurements are incomplete", category="error")
        self.assert_batch_badge("UNDER PRODUCTION")

    def save_qa_measurements(self, batch, completed_weight, overall_length, required):
        self.open(f"/batches/{batch['id']}")
        section = self.driver.find_element(By.ID, "qa-measurements")
        form = section.find_element(By.CSS_SELECTOR, "form[action$='/qa']")
        weight_inputs = form.find_elements(By.NAME, "completed_weight")
        length_inputs = form.find_elements(By.NAME, "overall_length")
        for index in range(required):
            weight_inputs[index].clear()
            weight_inputs[index].send_keys(completed_weight)
            length_inputs[index].clear()
            length_inputs[index].send_keys(overall_length)
        form.find_element(By.CSS_SELECTOR, "button").click()
        self.pause()
        self.wait_for_page()
        self.assert_flash("QA measurements saved.", category="success")
        section = self.driver.find_element(By.ID, "qa-measurements")
        assert f"Complete: {required} / {required}." in section.text

    def assert_qa_measurement_results(self, batch, expected_weight_abs, expected_length_abs, expected_weight_variance, expected_length_variance):
        self.open(f"/batches/{batch['id']}")
        section = self.driver.find_element(By.ID, "qa-measurements")
        assert "Complete: 3 / 3." in section.text
        assert "STD: weight 0.000 gr; length 0.0000 in." in section.text
        assert (
            f"AVE ABS: weight {expected_weight_abs}; "
            f"length {expected_length_abs}."
        ) in section.text
        submissions = section.find_element(By.CSS_SELECTOR, "details.qa-submissions")
        submissions.find_element(By.TAG_NAME, "summary").click()
        assert expected_weight_variance in submissions.text
        assert expected_length_variance in submissions.text

    def assert_batch_badge(self, state):
        badge = self.driver.find_element(By.CSS_SELECTOR, ".heading .badge")
        assert badge.text == state

    def assert_batch_cost(self, batch, cost_per_cartridge, material_cost_text):
        self.open(f"/batches/{batch['id']}")
        self.assert_text("Cost per cartridge:")
        self.assert_text(cost_per_cartridge)
        self.assert_text(material_cost_text)

    def assert_batch_cost_unavailable(self, batch):
        self.open(f"/batches/{batch['id']}")
        self.assert_text("Cost per cartridge unavailable until all traced lots have costs.")

    def assert_batch_list_cost(self, batch, expected_text):
        self.open("/batches?depleted=true")
        row = self.wait.until(EC.presence_of_element_located((
            By.XPATH,
            f"//tr[.//a/b[normalize-space()='{batch['slug']}']]",
        )))
        assert expected_text in row.text

    def assert_recipe_card_cost(self, recipe, expected_text):
        self.open("/recipes?retired=true")
        card = self.recipe_card(recipe["title"])
        assert expected_text in card.text
        assert "cost / round" in card.text.lower()

    def assert_recipe_card_cost_unavailable(self, recipe):
        self.open("/recipes?retired=true")
        card = self.recipe_card(recipe["title"])
        assert "cost / round" not in card.text.lower()

    def save_performance_record(self, batch):
        self.open(f"/batches/{batch['id']}")
        form = self.open_details("Performance / quality").find_element(By.CSS_SELECTOR, "form[action$='/performance']")
        self.fill("recorded_on", "2026-02-10", form)
        self.fill("firearm", "Ruger GP100", form)
        self.fill("barrel_length", "4.2", form)
        self.fill("distance", "25", form)
        self.fill("group_size", "2.1", form)
        self.fill("shot_count", "8", form)
        self.fill("velocity_average", "1210", form)
        self.fill("velocity_minimum", "1198", form)
        self.fill("velocity_maximum", "1224", form)
        self.fill("standard_deviation", "8.4", form)
        self.fill("extreme_spread", "26", form)
        self.fill("temperature", "62", form)
        self.fill("recoil_perception", "3", form)
        self.fill("accuracy_perception", "4", form)
        self.fill("cleanliness_perception", "4", form)
        self.fill("subjective_rating", "4", form)
        self.open_details("Advanced performance data")
        self.fill("raw_data", "1210,1198,1224,1208", form)
        self.fill("processed_data", '{"chronograph": "Garmin Xero C1"}', form)
        self.fill("notes", "Performance record entered through Selenium.", form)
        form.find_element(By.CSS_SELECTOR, "button").click()
        self.pause()
        self.wait_for_page()
        self.assert_flash("Performance record saved.", category="success")
        self.upload_garmin_performance(batch)
        self.assert_garmin_performance_fields()

    def upload_garmin_performance(self, batch):
        if not GARMIN_FIT_FILE.exists():
            pytest.skip(f"Garmin e2e FIT file is not available: {GARMIN_FIT_FILE}")
        self.open(f"/batches/{batch['id']}")
        file_input = self.wait.until(EC.presence_of_element_located((
            By.CSS_SELECTOR,
            "[data-garmin-import-form] input[name='files']",
        )))
        self.driver.execute_script("arguments[0].removeAttribute('hidden');", file_input)
        file_input.send_keys(str(GARMIN_FIT_FILE))
        self.assert_flash("Imported Garmin data from 1 file(s); 16 shots.", category="success")

    def assert_garmin_performance_fields(self):
        form = self.driver.find_element(By.CSS_SELECTOR, "form[action$='/performance']")
        self.assert_field_value("recorded_on", GARMIN_IMPORTED_FIELDS["recorded_on"], form)
        for name in (
            "shot_count",
            "velocity_average",
            "velocity_minimum",
            "velocity_maximum",
            "standard_deviation",
            "extreme_spread",
        ):
            self.assert_numeric_field_value(name, GARMIN_IMPORTED_FIELDS[name], form)
            self.assert_field_readonly(name, form)
        self.assert_field_readonly("recorded_on", form)
        self.assert_field_readonly("raw_data", form)
        self.assert_field_readonly("processed_data", form)

        for name, expected in {
            "firearm": "Ruger GP100",
            "barrel_length": "4.2",
            "distance": "25",
            "group_size": "2.1",
            "temperature": "62",
            "recoil_perception": "3",
            "accuracy_perception": "4",
            "cleanliness_perception": "4",
            "subjective_rating": "4",
        }.items():
            if name == "firearm":
                self.assert_field_value(name, expected, form)
            else:
                self.assert_numeric_field_value(name, expected, form)
            self.assert_field_not_readonly(name, form)
        self.assert_field_value("notes", "Performance record entered through Selenium.", form)

        raw_data = self.field_value("raw_data", form)
        assert "Garmin Xero C1 Pro import" in raw_data
        assert "Source file" in raw_data
        assert "session_3.fit (16 shots)" in raw_data
        assert "1. 1620.112 fps" in raw_data
        assert "16. 1728.448 fps" in raw_data

        processed = json.loads(self.field_value("processed_data", form))
        assert processed["chronograph"] == "Garmin Xero C1 Pro"
        assert processed["velocity_unit"] == "fps"
        assert processed["recorded_on_source"] == "2024-07-27T04:57:09+00:00"
        assert processed["projectile_weight_gr"] == pytest.approx(140.0)
        assert processed["summary"]["shot_count"] == 16
        assert processed["summary"]["velocity_average_fps"] == pytest.approx(1717.551)
        assert len(processed["shots"]) == 16
        assert processed["shots"][0]["sequence"] == 1
        assert processed["shots"][0]["source_filename"] == "session_3.fit"
        assert processed["shots"][0]["velocity_fps"] == pytest.approx(1620.112)
        assert processed["shots"][-1]["sequence"] == 16
        assert processed["shots"][-1]["velocity_fps"] == pytest.approx(1728.448)

    def create_container(self, identifier, name, limit):
        self.open("/containers")
        form = self.open_details("Create container").find_element(By.TAG_NAME, "form")
        self.fill("identifier", identifier, form)
        self.fill("name", name, form)
        self.fill("cartridge_limit", str(limit), form)
        self.fill("description", f"{limit} round workflow test container.", form)
        self.fill("notes", "Container created through Selenium.", form)
        form.find_element(By.CSS_SELECTOR, "button").click()
        self.pause()
        self.wait_for_page()
        self.assert_flash("Container created.", category="success")
        self.assert_text(identifier)

    def assign_container(self, identifier, batch, quantity, acknowledge_mixed=False):
        self.open("/containers")
        article = self.container_article(identifier)
        form = self.container_assignment_form(article)
        self.select_option_containing(Select(form.find_element(By.NAME, "batch_id")), batch["slug"])
        if acknowledge_mixed:
            checkbox = self.wait.until(
                lambda _driver: enabled_or_false(form.find_element(By.NAME, "acknowledge_mixed_batch"))
            )
            self.driver.execute_script("arguments[0].click();", checkbox)
            self.pause()
        quantity_input = form.find_element(By.NAME, "quantity")
        quantity_input.clear()
        quantity_input.send_keys(str(quantity))
        self.pause()
        form.find_element(By.CSS_SELECTOR, "button").click()
        self.pause()
        self.assert_flash("Batch assigned to container.", category="success")
        self.assert_text(identifier)

    def assign_container_expect_overfill_error(self, identifier, batch, quantity):
        self.open("/containers")
        article = self.container_article(identifier)
        form = self.container_assignment_form(article)
        self.select_option_containing(Select(form.find_element(By.NAME, "batch_id")), batch["slug"])
        checkbox = self.wait.until(
            lambda _driver: enabled_or_false(form.find_element(By.NAME, "acknowledge_mixed_batch"))
        )
        self.driver.execute_script("arguments[0].click();", checkbox)
        self.pause()
        quantity_input = form.find_element(By.NAME, "quantity")
        self.driver.execute_script("arguments[0].removeAttribute('max');", quantity_input)
        quantity_input.clear()
        quantity_input.send_keys(str(quantity))
        self.pause()
        form.find_element(By.CSS_SELECTOR, "button").click()
        self.pause()
        self.assert_flash("Assignment exceeds the container cartridge limit", category="error")

    def transition_container(self, identifier, state):
        self.open("/containers")
        article = self.container_article(identifier)
        select = Select(article.find_element(By.CSS_SELECTOR, "[data-container-state-form] select[name='state']"))
        select.select_by_visible_text(state)
        self.pause()
        self.assert_flash("Container state changed.", category="success")
        self.assert_text(state)

    def assert_container_empty(self, identifier):
        self.open("/containers")
        article = self.container_article(identifier)
        assert "EMPTY" in article.text
        assert "Empty." in article.text
        assert f"{identifier} · 0 /" in article.text

    def assert_batch_state(self, batch, state, expected_text):
        self.open(f"/batches/{batch['id']}")
        self.assert_text(state)
        self.assert_text(expected_text)

    def assert_dashboard_metric(self, label, expected):
        self.open("/")
        metric = self.driver.find_element(By.XPATH, f"//article[span[normalize-space()='{label}']]/strong")
        assert metric.text == str(expected)

    def assert_audit_contains(self, action):
        self.open("/audit")
        self.assert_text(action)

    def assert_inventory_lot_status(self, manufacturer_lot, *expected_text):
        self.open("/inventory?historical=true")
        row = self.inventory_lot_row(manufacturer_lot)
        for text in expected_text:
            assert text in row.text

    def assert_inventory_lot_cost(self, manufacturer_lot, *expected_text):
        self.open("/inventory?historical=true")
        row = self.inventory_lot_row(manufacturer_lot)
        for text in expected_text:
            assert text in row.text

    def assert_inventory_lot_active_and_opened(self, manufacturer_lot):
        self.open("/inventory?historical=true")
        row = self.inventory_lot_row(manufacturer_lot)
        assert "Active" in row.text
        assert "Not opened" not in row.text
        assert re.search(r"\d{4}-\d{2}-\d{2}", row.text), row.text

    def fill(self, name, value, scope=None):
        scope = scope or self.driver
        field = scope.find_element(By.NAME, name)
        if field.get_attribute("type") == "date":
            self.driver.execute_script(
                "arguments[0].value = arguments[1];"
                "arguments[0].dispatchEvent(new Event('input', {bubbles: true}));"
                "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
                field,
                str(value),
            )
            self.pause()
            return
        field.clear()
        field.send_keys(str(value))
        self.pause()

    def field_value(self, name, scope=None):
        scope = scope or self.driver
        return scope.find_element(By.NAME, name).get_attribute("value")

    def assert_field_value(self, name, expected, scope=None):
        actual = self.field_value(name, scope)
        assert actual == str(expected), f"Expected {name}={expected!r}, found {actual!r}"

    def assert_numeric_field_value(self, name, expected, scope=None):
        actual = self.field_value(name, scope)
        assert float(actual) == pytest.approx(float(expected)), (
            f"Expected {name}={expected!r}, found {actual!r}"
        )

    def assert_field_readonly(self, name, scope=None):
        scope = scope or self.driver
        field = scope.find_element(By.NAME, name)
        assert field.get_attribute("readonly") is not None or field.get_attribute("aria-readonly") == "true"

    def assert_field_not_readonly(self, name, scope=None):
        scope = scope or self.driver
        field = scope.find_element(By.NAME, name)
        assert field.get_attribute("readonly") is None and field.get_attribute("aria-readonly") != "true"

    def click_button(self, text):
        self.driver.find_element(By.XPATH, f"//button[normalize-space()='{text}']").click()
        self.pause()
        self.wait_for_page()

    def assert_text(self, text):
        self.wait.until(lambda driver: text in driver.find_element(By.TAG_NAME, "body").text)

    def assert_flash(self, text, category=None):
        selector = ".alert" if category is None else f".alert.{category}"
        try:
            self.wait.until(
                lambda driver: driver.execute_script(
                    "return Array.from(document.querySelectorAll(arguments[0]))"
                    ".some((element) => element.textContent.includes(arguments[1]));",
                    selector,
                    text,
                )
            )
        except TimeoutException as exc:
            body = self.driver.find_element(By.TAG_NAME, "body").text
            raise AssertionError(
                f"Expected flash containing {text!r} with selector {selector!r}.\n"
                f"Current URL: {self.driver.current_url}\n"
                f"Page text:\n{body[:4000]}"
            ) from exc

    def wait_for_page(self):
        self.wait.until(lambda driver: driver.execute_script("return document.readyState") == "complete")

    def open_details(self, summary_text):
        summary = self.driver.find_element(By.XPATH, f"//summary[normalize-space()='{summary_text}']")
        details = summary.find_element(By.XPATH, "./ancestor::details[1]")
        if details.get_attribute("open") is None:
            summary.click()
            self.pause()
        return details

    def select_option_containing(self, select, *needles):
        for option in select.options:
            if all(needle in option.text for needle in needles):
                select.select_by_visible_text(option.text)
                self.pause()
                return option.text
        options = [option.text for option in select.options]
        body = self.driver.find_element(By.TAG_NAME, "body").text
        raise AssertionError(
            f"No select option contains: {needles}.\n"
            f"Options: {options}\n"
            f"Current URL: {self.driver.current_url}\n"
            f"Page text:\n{body[:3000]}"
        )

    def component_id(self, allocation):
        select = allocation.find_element(By.CSS_SELECTOR, "select[name^='component_'][name$='_lot']")
        match = re.match(r"component_(\d+)_lot", select.get_attribute("name"))
        assert match
        return match.group(1)

    def container_article(self, identifier):
        return self.wait.until(EC.presence_of_element_located((
            By.XPATH,
            f"//article[contains(@class,'card') and .//p[contains(., '{identifier}')]]",
        )))

    def recipe_card(self, title):
        return self.wait.until(EC.presence_of_element_located((
            By.XPATH,
            f"//a[contains(@class,'card') and .//h2[normalize-space()='{title}']]",
        )))

    def container_assignment_form(self, article):
        details = article.find_element(
            By.XPATH,
            ".//summary[normalize-space()='Assign batch']/ancestor::details",
        )
        if details.get_attribute("open") is None:
            details.find_element(By.TAG_NAME, "summary").click()
            self.pause()
        return details.find_element(By.CSS_SELECTOR, "[data-container-assignment-form]")

    def inventory_lot_row(self, manufacturer_lot):
        return self.wait.until(EC.presence_of_element_located((
            By.XPATH,
            f"//tr[.//span[contains(normalize-space(), '{manufacturer_lot}')]]",
        )))

    def pause(self):
        if self.slow_seconds:
            time.sleep(self.slow_seconds)


def enabled_or_false(element):
    return element if element.is_enabled() else False
