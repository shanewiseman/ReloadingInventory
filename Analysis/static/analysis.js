(function () {
  const form = document.getElementById("analysis-form");
  if (!form) return;

  const fileInput = document.getElementById("target-photo");
  const preview = document.getElementById("analysis-preview");
  const emptyState = document.getElementById("analysis-empty");
  const status = document.getElementById("analysis-status");
  const progress = document.getElementById("analysis-progress");
  const output = document.getElementById("analysis-output");
  const resultPanel = document.getElementById("analysis-results-panel");
  const resultActions = document.getElementById("analysis-result-actions");
  const resetButton = document.getElementById("analysis-reset");
  const submitButton = form.querySelector('button[type="submit"]');
  let previewUrl = null;

  fileInput.addEventListener("change", function () {
    clearResult();
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    const file = fileInput.files && fileInput.files[0];
    if (!file) {
      hidePreview();
      return;
    }
    previewUrl = URL.createObjectURL(file);
    preview.src = previewUrl;
    preview.hidden = false;
    emptyState.hidden = true;
    resultPanel.hidden = true;
    resultActions.hidden = true;
    setStatus("");
  });

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    const formData = new FormData(form);
    clearResult();
    setBusy(true);
    setStatus("Image processing");

    try {
      const processData = await postJson("/analysis/process", { body: formData });
      preview.src = processData.target_image_url + "?v=" + Date.now();
      preview.alt = "Processed target analysis image";
      preview.hidden = false;
      emptyState.hidden = true;
      resultActions.hidden = false;
      resultPanel.hidden = false;
      progress.textContent = "Analysis in progress";
      setStatus("Image processed", "success");

      const analysisData = await postJson(`/analysis/jobs/${processData.analysis_id}/analyze`, {
        method: "POST",
      });
      progress.textContent = "";
      renderAnalysis(analysisData.analysis);
      setStatus("Analysis complete", "success");
    } catch (error) {
      progress.textContent = "";
      setStatus(error.message || "Analysis failed", "error");
    } finally {
      setBusy(false);
    }
  });

  resetButton.addEventListener("click", function () {
    form.reset();
    clearResult();
    hidePreview();
    resultPanel.hidden = true;
    resultActions.hidden = true;
    setStatus("");
  });

  async function postJson(url, options) {
    const response = await fetch(url, Object.assign({
      method: "POST",
      headers: { Accept: "application/json" },
    }, options));
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
      ? await response.json().catch(() => ({}))
      : {};
    if (!response.ok) {
      const message = (payload.error && payload.error.message) || payload.message || fallbackError(response.status);
      throw new Error(message);
    }
    return payload;
  }

  function fallbackError(statusCode) {
    if (statusCode === 413) return "Image is too large for upload.";
    if (statusCode === 502 || statusCode === 504) return "Analysis timed out while waiting for the model.";
    if (statusCode >= 500) return "Analysis failed before the server returned details. Try again with a smaller image.";
    return "Analysis request failed.";
  }

  function renderAnalysis(analysis) {
    output.replaceChildren();
    const group = analysis.group || {};
    const metrics = document.createElement("div");
    metrics.className = "analysis-results-grid";
    metrics.append(
      metric("Included shots", group.shot_count),
      metric("Group size", inches(group.extreme_spread_inches_center_to_center)),
      metric("MOA", number(group.moa)),
      metric("Group center", coordinate(group.center_x_inches, group.center_y_inches)),
      metric("Bullseye offset", inches(group.distance_from_bullseye_inches)),
      metric("Offset MOA", number(group.distance_from_bullseye_moa)),
      metric("Confidence", percent(analysis.confidence)),
      metric("Distance", distanceLabel(analysis.distance))
    );
    output.append(metrics);

    if (analysis.warnings && analysis.warnings.length) {
      const warnings = document.createElement("ul");
      warnings.className = "analysis-warning-list";
      analysis.warnings.forEach((warning) => {
        const item = document.createElement("li");
        item.textContent = warning;
        warnings.append(item);
      });
      output.append(warnings);
    }

    output.append(shotTable("Included shots", analysis.shots || []));
    if (analysis.excluded_shots && analysis.excluded_shots.length) {
      output.append(shotTable("Excluded shots", analysis.excluded_shots));
    }

    if (analysis.model_review && analysis.model_review.summary) {
      const review = document.createElement("div");
      review.className = "analysis-review";
      const heading = document.createElement("h3");
      heading.textContent = "Model review";
      const summary = document.createElement("p");
      summary.textContent = analysis.model_review.summary;
      review.append(heading, summary);
      output.append(review);
    }
  }

  function metric(label, value) {
    const element = document.createElement("div");
    element.className = "analysis-metric";
    const labelElement = document.createElement("span");
    labelElement.textContent = label;
    const valueElement = document.createElement("strong");
    valueElement.textContent = value === undefined || value === null ? "n/a" : value;
    element.append(labelElement, valueElement);
    return element;
  }

  function shotTable(title, shots) {
    const wrapper = document.createElement("div");
    wrapper.className = "analysis-table";
    const heading = document.createElement("h3");
    heading.textContent = title;
    const tableWrap = document.createElement("div");
    tableWrap.className = "table-wrap";
    const table = document.createElement("table");
    table.innerHTML = "<thead><tr><th>Shot</th><th>X</th><th>Y</th><th>Radius</th><th>Confidence</th><th>Status</th></tr></thead>";
    const body = document.createElement("tbody");
    shots.forEach((shot) => {
      const row = document.createElement("tr");
      [
        shot.shot_id,
        inches(shot.x_inches),
        inches(shot.y_inches),
        inches(shot.distance_from_center_inches),
        percent(shot.confidence),
        shot.included ? "Included" : (shot.reason || "Excluded"),
      ].forEach((value) => {
        const cell = document.createElement("td");
        cell.textContent = value;
        row.append(cell);
      });
      body.append(row);
    });
    if (!shots.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 6;
      cell.textContent = "No shots detected.";
      row.append(cell);
      body.append(row);
    }
    table.append(body);
    tableWrap.append(table);
    wrapper.append(heading, tableWrap);
    return wrapper;
  }

  function setBusy(isBusy) {
    submitButton.disabled = isBusy;
    fileInput.disabled = isBusy;
  }

  function setStatus(message, kind) {
    status.textContent = message;
    status.className = "analysis-status";
    if (kind) status.classList.add(kind);
  }

  function clearResult() {
    output.replaceChildren();
    progress.textContent = "";
  }

  function hidePreview() {
    preview.hidden = true;
    preview.removeAttribute("src");
    preview.alt = "Submitted target preview";
    emptyState.hidden = false;
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      previewUrl = null;
    }
  }

  function inches(value) {
    return value === undefined || value === null ? "n/a" : `${Number(value).toFixed(2)} in`;
  }

  function number(value) {
    return value === undefined || value === null ? "n/a" : Number(value).toFixed(2);
  }

  function percent(value) {
    return value === undefined || value === null ? "n/a" : `${Math.round(Number(value) * 100)}%`;
  }

  function coordinate(x, y) {
    if (x === undefined || y === undefined || x === null || y === null) return "n/a";
    return `${Number(x).toFixed(2)}, ${Number(y).toFixed(2)} in`;
  }

  function distanceLabel(distance) {
    if (!distance) return "n/a";
    return `${distance.value} ${distance.unit}`;
  }
})();
