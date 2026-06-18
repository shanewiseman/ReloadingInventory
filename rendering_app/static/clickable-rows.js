(() => {
  document.querySelectorAll(".clickable-row[data-href]").forEach((row) => {
    row.querySelectorAll("a").forEach((link) => {
      link.addEventListener("mouseenter", () => {
        row.classList.add("link-hover");
      });
      link.addEventListener("mouseleave", () => {
        row.classList.remove("link-hover");
      });
      link.addEventListener("focus", () => {
        row.classList.add("link-hover");
      });
      link.addEventListener("blur", () => {
        row.classList.remove("link-hover");
      });
    });

    const open = () => {
      window.location.href = row.dataset.href;
    };
    row.addEventListener("click", (event) => {
      if (event.target.closest("a, button, input, select, textarea, summary")) return;
      open();
    });
    row.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      open();
    });
  });
})();
