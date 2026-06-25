(() => {
  document.querySelectorAll("[data-component-form]").forEach((form) => {
    const select = form.querySelector("[data-component-item-select]");
    if (!select) return;

    const fields = {
      powder: form.querySelector('[data-component-quantity-field="POWDER"]'),
      other: form.querySelector('[data-component-quantity-field="OTHER"]'),
    };

    const setField = (field, visible) => {
      if (!field) return;
      field.hidden = !visible;
      field.querySelectorAll("input").forEach((input) => {
        input.disabled = !visible;
        input.required = visible;
        if (!visible) input.value = "";
      });
    };

    const update = () => {
      const category = select.selectedOptions[0]?.dataset.category || "";
      setField(fields.powder, category === "POWDER");
      setField(fields.other, category === "OTHER");
    };

    select.addEventListener("change", update);
    update();
  });

  document.querySelectorAll("[data-source-form]").forEach((form) => {
    const kind = form.querySelector("[data-source-kind]");
    if (!kind) return;

    const fields = {
      sourceLabel: form.querySelector('[data-source-field="source-label"]'),
      url: form.querySelector('[data-source-field="url"]'),
      page: form.querySelector('[data-source-field="page"]'),
      upload: form.querySelector('[data-source-field="upload"]'),
    };
    const uploadInput = fields.upload?.querySelector('input[type="file"]');

    const setVisible = (field, visible) => {
      if (!field) return;
      field.hidden = !visible;
      field.querySelectorAll("input,textarea,select").forEach((input) => {
        if (!visible) input.value = "";
      });
    };

    const update = () => {
      const value = kind.value.toLowerCase();
      setVisible(fields.sourceLabel, ["manual", "url", "image", "uploaded document"].includes(value));
      setVisible(fields.url, value === "url");
      setVisible(fields.page, ["manual", "image", "uploaded document"].includes(value));
      setVisible(fields.upload, ["image", "uploaded document"].includes(value));
      if (uploadInput) {
        uploadInput.accept = value === "image" ? "image/*" : ".pdf,.txt,.csv,.doc,.docx,.jpg,.jpeg,.png,image/*,application/pdf,text/*";
      }
    };

    kind.addEventListener("change", update);
    update();
  });
})();
