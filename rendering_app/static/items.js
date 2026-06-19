(() => {
  const categorySelect = document.querySelector("#item-category");
  if (!categorySelect) return;

  const conditionalFields = document.querySelectorAll("[data-item-categories]");
  const placeholders = {
    BULLET: {
      manufacturer: "Hornady",
      name: "158 gr JHP",
      product_line: "XTP",
      characteristics: ".357 jacketed hollow point",
      caliber: ".357",
      bullet_weight: "158",
      bullet_type: "JHP",
      primer_type: "",
      powder_type: "",
      attributes: '{"diameter": ".357", "sku": "35750"}',
      notes: "Primary recipe bullet.",
    },
    POWDER: {
      manufacturer: "Hodgdon",
      name: "H110",
      product_line: "H110",
      characteristics: "Spherical magnum pistol powder",
      caliber: "",
      bullet_weight: "",
      bullet_type: "",
      primer_type: "",
      powder_type: "Spherical",
      attributes: '{"canister": "1 lb", "sku": "H1101"}',
      notes: "Magnum revolver powder.",
    },
    PRIMER: {
      manufacturer: "CCI",
      name: "Small Pistol Magnum Primers",
      product_line: "No. 550",
      characteristics: "Small pistol magnum primer",
      caliber: "",
      bullet_weight: "",
      bullet_type: "",
      primer_type: "Small pistol magnum",
      powder_type: "",
      attributes: '{"brick": "1000", "sku": "550"}',
      notes: "Magnum primer option.",
    },
    CASE: {
      manufacturer: "Starline",
      name: ".357 Magnum Nickel Brass",
      product_line: "Nickel",
      characteristics: "Nickel plated straight wall revolver case",
      caliber: ".357 Magnum",
      bullet_weight: "",
      bullet_type: "",
      primer_type: "",
      powder_type: "",
      attributes: '{"finish": "nickel", "sku": "357MEU"}',
      notes: "Nickel plated brass.",
    },
    OTHER: {
      manufacturer: "MTM",
      name: "Adhesive Cartridge Labels",
      product_line: "Load Labels",
      characteristics: "Traceability label stock",
      caliber: "",
      bullet_weight: "",
      bullet_type: "",
      primer_type: "",
      powder_type: "",
      attributes: '{"color": "white", "sheets": 25}',
      notes: "Workflow support item.",
    },
  };

  function updatePlaceholders(selectedCategory) {
    const categoryPlaceholders = placeholders[selectedCategory] || placeholders.BULLET;
    Object.entries(categoryPlaceholders).forEach(([name, placeholder]) => {
      const control = document.querySelector(`#item-form [name="${name}"]`);
      if (control) control.placeholder = placeholder;
    });
  }

  function updateCategoryFields() {
    const selectedCategory = categorySelect.value.toUpperCase();
    updatePlaceholders(selectedCategory);

    conditionalFields.forEach((field) => {
      const allowedCategories = field.dataset.itemCategories.split(",");
      const visible = allowedCategories.includes(selectedCategory);
      field.hidden = !visible;

      field.querySelectorAll("input, select, textarea").forEach((control) => {
        control.disabled = !visible;
        if (!visible) control.value = "";
      });
    });
  }

  categorySelect.addEventListener("change", updateCategoryFields);
  updateCategoryFields();
})();
