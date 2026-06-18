(() => {
  const message = [
    "This recipe has no attached or referenced source material.",
    "",
    "Proceeding may rely on unverified load data. Do you acknowledge this risk and want to continue?",
  ].join("\n");

  document.querySelectorAll("form[data-missing-source-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const acknowledgement = form.querySelector(
        'input[name="acknowledge_missing_source"]'
      );
      if (acknowledgement?.value === "true") return;
      if (!window.confirm(message)) {
        event.preventDefault();
        return;
      }
      acknowledgement.value = "true";
    });
  });
})();
