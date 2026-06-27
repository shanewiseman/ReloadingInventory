(() => {
  document.querySelectorAll(".alert.print-error").forEach((alert) => {
    const message = alert.textContent.trim();
    if (message) window.alert(message);
  });
})();
