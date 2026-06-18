(() => {
  const categorySelect = document.querySelector("#item-category");
  if (!categorySelect) return;

  const conditionalFields = document.querySelectorAll("[data-item-categories]");

  function updateCategoryFields() {
    const selectedCategory = categorySelect.value.toUpperCase();

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
