(() => {
  const form = document.querySelector("[data-ballistics-form]");
  const dataNode = document.getElementById("ballistics-data");
  if (!form || !dataNode) return;

  const data = JSON.parse(dataNode.textContent || "{}");
  const bullets = data.bullets || [];
  const allFirearms = data.firearms || [];
  let context = null;

  const byName = (name) => form.querySelector(`[name="${name}"]`);
  const loadSource = form.querySelector("[data-load-source]");
  const bulletSelect = form.querySelector("[data-bullet-select]");
  const firearmSelect = form.querySelector("[data-firearm-select]");
  const velocitySelect = form.querySelector("[data-velocity-source]");
  const status = form.querySelector("[data-weather-status]");
  const contextNote = form.querySelector("[data-context-note]");

  const setValue = (name, value, { overwrite = true } = {}) => {
    const control = byName(name);
    if (!control || value === undefined || value === null) return;
    if (!overwrite && control.value) return;
    control.value = value;
  };

  const bulletLabel = (bullet) => `${bullet.manufacturer || ""} ${bullet.name || ""}`.trim() || `Bullet ${bullet.id}`;
  const firearmLabel = (firearm) => `${firearm.name}${firearm.caliber ? ` / ${firearm.caliber}` : ""}`;

  const fillSelect = (select, placeholder, rows, valueKey, labelFn) => {
    const previous = select.value;
    select.innerHTML = "";
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = placeholder;
    select.appendChild(empty);
    rows.forEach((row) => {
      const option = document.createElement("option");
      option.value = String(row[valueKey]);
      option.textContent = labelFn(row);
      select.appendChild(option);
    });
    select.value = Array.from(select.options).some((option) => option.value === previous) ? previous : "";
  };

  const applyBullet = (bullet, overwrite = true) => {
    if (!bullet) return;
    setValue("bullet_weight", bullet.bullet_weight, { overwrite });
    const ballistics = bullet.ballistics || {};
    setValue("drag_model", ballistics.drag_model, { overwrite });
    setValue("ballistic_coefficient", ballistics.ballistic_coefficient, { overwrite });
    setValue("diameter", ballistics.diameter, { overwrite });
    setValue("bullet_length", ballistics.bullet_length, { overwrite });
  };

  const applyFirearm = (firearm, overwrite = true) => {
    if (!firearm) return;
    setValue("sight_height", firearm.sight_height, { overwrite });
    setValue("zero_distance", firearm.default_zero_distance, { overwrite });
    setValue("barrel_length", firearm.barrel_length, { overwrite });
    setValue("twist_rate", firearm.twist_rate, { overwrite });
    setValue("twist_direction", firearm.twist_direction, { overwrite });
  };

  const matchingFirearms = () => {
    if (!context || !context.load) return allFirearms;
    return context.firearms || [];
  };

  const renderFirearms = () => {
    const rows = matchingFirearms();
    const placeholder = context?.load ? "Select matching firearm" : "Select saved firearm";
    fillSelect(firearmSelect, placeholder, rows, "id", firearmLabel);
    if (context?.load && !rows.length) {
      contextNote.textContent = "No firearm profiles have matching performance records for this load yet. Use manual firearm fields or record performance with a firearm.";
    } else {
      contextNote.textContent = "Performance velocity sources appear after a load source and matching firearm are selected.";
    }
  };

  const renderVelocitySources = () => {
    const selectedFirearm = firearmSelect.value;
    const rows = [];
    if (context?.velocity_sources) {
      context.velocity_sources.forEach((source) => {
        if (source.source_type === "recipe_expected") rows.push(source);
        if (selectedFirearm && String(source.firearm_profile_id || "") === selectedFirearm) rows.push(source);
      });
    }
    fillSelect(velocitySelect, "Manual velocity", rows, "id", (row) => row.label);
  };

  const applyContext = (nextContext) => {
    context = nextContext;
    renderFirearms();
    renderVelocitySources();
    const component = context?.bullet;
    if (component?.item) {
      bulletSelect.value = String(component.item_id);
      applyBullet(component.item, false);
    }
    if (context?.load?.expected_velocity) {
      setValue("muzzle_velocity", context.load.expected_velocity, { overwrite: false });
    }
  };

  const fetchContext = async () => {
    const value = loadSource.value || "";
    if (!value) {
      applyContext(null);
      return;
    }
    const [kind, id] = value.split(":");
    const params = new URLSearchParams(kind === "batch" ? { batch_id: id } : { recipe_id: id });
    const response = await fetch(`/ballistics/context?${params.toString()}`);
    if (!response.ok) throw new Error("Unable to load ballistic context");
    const payload = await response.json();
    applyContext(payload.context);
  };

  const applyWeather = (environment) => {
    setValue("temperature_f", environment.temperature_f);
    setValue("pressure_inhg", environment.pressure_inhg);
    setValue("humidity_percent", environment.humidity_percent);
    setValue("altitude_ft", environment.elevation_ft);
    setValue("wind_speed", environment.wind_speed_mph, { overwrite: false });
    setValue("environment_source", environment.source || "weather");
    status.textContent = `${environment.source || "Weather"} loaded${environment.observed_at ? ` for ${environment.observed_at}` : ""}. Manual edits still override these values.`;
  };

  const fetchWeather = async (lat, lon) => {
    status.textContent = "Loading weather...";
    const response = await fetch(`/weather/current?${new URLSearchParams({ lat, lon })}`);
    if (!response.ok) throw new Error("Weather lookup failed");
    const payload = await response.json();
    applyWeather(payload.environment);
  };

  loadSource.addEventListener("change", () => {
    firearmSelect.value = "";
    fetchContext().catch((error) => {
      contextNote.textContent = error.message;
      applyContext(null);
    });
  });

  bulletSelect.addEventListener("change", () => {
    const bullet = bullets.find((row) => String(row.id) === bulletSelect.value);
    applyBullet(bullet);
  });

  firearmSelect.addEventListener("change", () => {
    const firearm = matchingFirearms().find((row) => String(row.id) === firearmSelect.value);
    applyFirearm(firearm);
    renderVelocitySources();
  });

  velocitySelect.addEventListener("change", () => {
    const source = (context?.velocity_sources || []).find((row) => row.id === velocitySelect.value);
    if (source) setValue("muzzle_velocity", source.velocity_average);
  });

  form.querySelector("[data-location-search]")?.addEventListener("click", async () => {
    const query = form.querySelector("[data-location-query]")?.value || "";
    const label = form.querySelector("[data-location-results-label]");
    const results = form.querySelector("[data-location-results]");
    if (!query.trim() || !results || !label) return;
    status.textContent = "Searching locations...";
    const response = await fetch(`/weather/geocode?${new URLSearchParams({ q: query })}`);
    if (!response.ok) {
      status.textContent = "Location lookup failed. Manual environment values are still available.";
      return;
    }
    const payload = await response.json();
    results.innerHTML = "";
    (payload.locations || []).forEach((location) => {
      const option = document.createElement("option");
      option.value = `${location.latitude},${location.longitude}`;
      option.textContent = [location.name, location.admin1, location.country].filter(Boolean).join(", ");
      results.appendChild(option);
    });
    label.hidden = !results.options.length;
    status.textContent = results.options.length ? "Choose a matched location." : "No matching locations found.";
  });

  form.querySelector("[data-location-results]")?.addEventListener("change", (event) => {
    const [lat, lon] = event.currentTarget.value.split(",");
    if (lat && lon) fetchWeather(lat, lon).catch(() => {
      status.textContent = "Weather lookup failed. Manual environment values are still available.";
    });
  });

  form.querySelector("[data-use-current-location]")?.addEventListener("click", () => {
    if (!navigator.geolocation) {
      status.textContent = "This browser does not provide location access.";
      return;
    }
    status.textContent = "Requesting current location...";
    navigator.geolocation.getCurrentPosition(
      (position) => fetchWeather(position.coords.latitude, position.coords.longitude).catch(() => {
        status.textContent = "Weather lookup failed. Manual environment values are still available.";
      }),
      () => {
        status.textContent = "Location permission was not granted. Manual environment values are still available.";
      },
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 }
    );
  });

  renderFirearms();
  renderVelocitySources();
  if (loadSource.value) fetchContext().catch(() => {});
})();
