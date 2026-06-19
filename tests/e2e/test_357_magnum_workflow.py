from __future__ import annotations

import re
import time

import pytest

pytest.importorskip("selenium", reason="selenium package is not installed")

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.ui import WebDriverWait


pytestmark = pytest.mark.selenium


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
            {"lot": "HDY-158-ACT", "quantity": "800", "unit": "count", "active": True},
            {"lot": "HDY-158-RES", "quantity": "300", "unit": "count", "active": False},
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
            {"lot": "SPR-180-ACT", "quantity": "600", "unit": "count", "active": True},
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
            {"lot": "H110-ACT", "quantity": "1", "unit": "pounds", "active": True},
            {"lot": "H110-RES", "quantity": "8", "unit": "ounces", "active": False},
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
            {"lot": "CCI550-ACT", "quantity": "1000", "unit": "count", "active": True},
            {"lot": "CCI550-RES", "quantity": "1000", "unit": "count", "active": False},
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
            {"lot": "FED100-ACT", "quantity": "1000", "unit": "count", "active": True},
            {"lot": "FED100-RES", "quantity": "1000", "unit": "count", "active": False},
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
            {"lot": "STAR-NI-ACT", "quantity": "1000", "unit": "count", "active": True},
            {"lot": "STAR-NI-RES", "quantity": "500", "unit": "count", "active": False},
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
            {"lot": "STAR-BR-ACT", "quantity": "1000", "unit": "count", "active": True},
            {"lot": "STAR-BR-RES", "quantity": "500", "unit": "count", "active": False},
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
            {"lot": "MTM-LBL-ACT", "quantity": "25", "unit": "count", "active": True},
            {"lot": "MTM-LBL-RES", "quantity": "10", "unit": "count", "active": False},
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

    recipes = [app.create_approved_recipe(recipe) for recipe in RECIPES]
    app.exercise_related_recipe_flows(recipes[0])

    batches = [
        app.create_batch(recipes[0], 8, "Quality sample: full single-container batch."),
        app.create_batch(recipes[0], 5, "Mixed container contribution."),
        app.create_batch(recipes[1], 7, "Leaves one round outside containers."),
    ]
    for batch in batches:
        app.transition_batch(batch, "PRODUCED")

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
        self.fill("title", recipe["title"])
        self.fill("cartridge", recipe["cartridge"])
        self.fill("overall_length", recipe["overall_length"])
        self.fill("case_length", recipe["case_length"])
        self.fill("crimp_type", recipe["crimp_type"])
        self.fill("seating_depth", recipe["seating_depth"])
        self.fill("source_notes", recipe["source_notes"])
        self.fill("notes", recipe["notes"])
        self.fill("public_notes", recipe["public_notes"])
        self.driver.find_element(By.NAME, "acknowledge_responsibility").click()
        self.pause()
        self.click_button("Create recipe")
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
        self.open_details("Add exact component")
        select = Select(self.driver.find_element(By.NAME, "item_id"))
        self.select_option_containing(select, manufacturer, name)
        self.fill("quantity", quantity)
        Select(self.driver.find_element(By.NAME, "unit")).select_by_visible_text(unit)
        self.pause()
        self.click_button("Add component")
        self.assert_flash("Recipe component added.", category="success")

    def add_recipe_source(self, citation):
        self.open_details("Add source")
        Select(self.driver.find_element(By.NAME, "kind")).select_by_visible_text("Manual")
        self.pause()
        self.fill("citation", citation)
        self.fill("page", "42")
        self.fill("notes", "Entered by Selenium from a user-supplied source citation.")
        self.click_button("Add source")
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
        self.open_details("Add exact component")
        select = Select(self.driver.find_element(By.NAME, "item_id"))
        self.select_option_containing(select, "Hornady", "125 gr JHP")
        self.fill("quantity", "1")
        Select(self.driver.find_element(By.NAME, "unit")).select_by_visible_text("count")
        self.pause()
        self.click_button("Add component")
        self.assert_flash("This recipe already has a Bullet component", category="error")

        self.click_button("Create public link")
        self.assert_flash("Recipe sharing updated.", category="success")
        self.driver.find_element(By.LINK_TEXT, "Open public view").click()
        self.pause()
        self.assert_text(recipe["title"])
        self.assert_text("Browser workflow test recipe.")
        self.open(f"/recipes/{recipe['id']}")

    def create_batch(self, recipe, iterations, notes):
        self.open(f"/batches/new?recipe_id={recipe['id']}")
        self.fill("iterations", str(iterations))
        for role, component in recipe["components"].items():
            lot = component[4]
            allocation = self.driver.find_element(
                By.XPATH,
                f"//div[contains(@class,'allocation') and .//b[contains(., '{role}')]]",
            )
            self.select_option_containing(Select(allocation.find_element(By.NAME, f"component_{self.component_id(allocation)}_lot")), lot)
        self.fill("notes", notes)
        self.click_button("Create batch and reserve inventory")
        self.assert_flash("Batch created and inventory reserved.", category="success")
        batch_id = self.driver.current_url.rstrip("/").split("/")[-1]
        slug = self.driver.find_element(By.CSS_SELECTOR, "h1").text
        self.assert_text("UNDER PRODUCTION")
        return {"id": batch_id, "slug": slug, "iterations": iterations}

    def transition_batch(self, batch, state):
        self.open(f"/batches/{batch['id']}")
        select = Select(self.driver.find_element(By.CSS_SELECTOR, "[data-batch-state-form] select[name='state']"))
        select.select_by_visible_text(state)
        self.pause()
        self.assert_flash("Batch state changed.", category="success")
        self.assert_text(state)

    def save_performance_record(self, batch):
        self.open(f"/batches/{batch['id']}")
        self.fill("recorded_on", "2026-02-10")
        self.fill("firearm", "Ruger GP100")
        self.fill("barrel_length", "4.2")
        self.fill("distance", "25")
        self.fill("group_size", "2.1")
        self.fill("shot_count", "8")
        self.fill("velocity_average", "1210")
        self.fill("velocity_minimum", "1198")
        self.fill("velocity_maximum", "1224")
        self.fill("standard_deviation", "8.4")
        self.fill("extreme_spread", "26")
        self.fill("temperature", "62")
        self.fill("recoil_perception", "3")
        self.fill("accuracy_perception", "4")
        self.fill("cleanliness_perception", "4")
        self.fill("subjective_rating", "4")
        self.open_details("Advanced performance data")
        self.fill("raw_data", "1210,1198,1224,1208")
        self.fill("processed_data", '{"chronograph": "Garmin Xero C1"}')
        self.fill("reliability_notes", "No failures.")
        self.fill("pressure_sign_notes", "No abnormal pressure signs recorded.")
        self.fill("weather_notes", "Indoor range.")
        self.fill("notes", "Performance record entered through Selenium.")
        self.click_button("Save performance record")
        self.assert_flash("Performance record saved.", category="success")

    def create_container(self, identifier, name, limit):
        self.open("/containers")
        self.fill("identifier", identifier)
        self.fill("name", name)
        self.fill("cartridge_limit", str(limit))
        self.fill("description", f"{limit} round workflow test container.")
        self.fill("notes", "Container created through Selenium.")
        self.click_button("Create container")
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
        details = summary.find_element(By.XPATH, "./ancestor::details")
        if details.get_attribute("open") is None:
            summary.click()
            self.pause()

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

    def container_assignment_form(self, article):
        details = article.find_element(
            By.XPATH,
            ".//summary[normalize-space()='Assign batch']/ancestor::details",
        )
        if details.get_attribute("open") is None:
            details.find_element(By.TAG_NAME, "summary").click()
            self.pause()
        return details.find_element(By.CSS_SELECTOR, "[data-container-assignment-form]")

    def pause(self):
        if self.slow_seconds:
            time.sleep(self.slow_seconds)


def enabled_or_false(element):
    return element if element.is_enabled() else False
