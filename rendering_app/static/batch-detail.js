(() => {
  const decimalSettings = (input) => ({
    entryDecimals: Number.parseInt(input.dataset.entryDecimals || "0", 10),
    submitDecimals: Number.parseInt(input.dataset.submitDecimals || input.dataset.entryDecimals || "0", 10),
    integerDigits: Number.parseInt(input.dataset.integerDigits || "0", 10),
  });

  const digitsOnly = (value) => String(value || "").replace(/\D/g, "");

  const trimDigits = (digits, settings) => {
    if (!settings.integerDigits) return digits;
    return digits.slice(0, settings.integerDigits + settings.entryDecimals);
  };

  const trimWholeDigits = (digits, settings) => {
    if (!settings.integerDigits) return digits;
    return digits.slice(0, settings.integerDigits);
  };

  const stripLeadingZeros = (value) => {
    const stripped = String(value || "").replace(/^0+(?=\d)/, "");
    return stripped || "0";
  };

  const formatScaledDigits = (digits, settings) => {
    const cleanDigits = trimDigits(digitsOnly(digits), settings);
    if (!cleanDigits) return "";
    if (!settings.entryDecimals) return stripLeadingZeros(cleanDigits);

    const padded = cleanDigits.padStart(settings.entryDecimals + 1, "0");
    const whole = stripLeadingZeros(padded.slice(0, -settings.entryDecimals));
    const fraction = padded.slice(-settings.entryDecimals);
    return `${whole}.${fraction}`;
  };

  const setInputState = (input, state) => {
    input.dataset.autoDecimalMode = state.mode;
    input.dataset.autoDecimalDigits = state.digits || "";
    input.dataset.autoDecimalWhole = state.whole || "";
    input.dataset.autoDecimalFraction = state.fraction || "";
  };

  const currentInputState = (input) => ({
    mode: input.dataset.autoDecimalMode || "scaled",
    digits: input.dataset.autoDecimalDigits || digitsOnly(input.value),
    whole: input.dataset.autoDecimalWhole || "",
    fraction: input.dataset.autoDecimalFraction || "",
  });

  const displayExplicitState = (state, settings) => {
    const whole = stripLeadingZeros(state.whole || "0");
    if (!settings.entryDecimals) return whole;
    const fraction = (state.fraction || "").padEnd(settings.entryDecimals, "0").slice(0, settings.entryDecimals);
    return `${whole}.${fraction}`;
  };

  const renderInputState = (input, state, settings) => {
    setInputState(input, state);
    input.value = state.mode === "explicit" ? displayExplicitState(state, settings) : formatScaledDigits(state.digits, settings);
    input.setSelectionRange(input.value.length, input.value.length);
  };

  const decimalValue = (input, settings) => {
    if (!input.value.trim()) return "";
    const parts = input.value.replace(/[^\d.]/g, "").split(".");
    const whole = stripLeadingZeros(parts[0] || "0");
    const fraction = (parts[1] || "").slice(0, settings.submitDecimals).padEnd(settings.submitDecimals, "0");
    return settings.submitDecimals ? `${whole}.${fraction}` : whole;
  };

  const stateFromPastedText = (text, settings) => {
    const value = String(text || "").trim();
    if (/[.,]/.test(value)) {
      const [whole, fraction = ""] = value.replace(",", ".").split(".");
      return {
        mode: "explicit",
        whole: trimWholeDigits(digitsOnly(whole), settings) || "0",
        fraction: digitsOnly(fraction).slice(0, settings.entryDecimals),
      };
    }
    return { mode: "scaled", digits: trimDigits(digitsOnly(value), settings) };
  };

  const handleAutoDecimalBeforeInput = (event) => {
    const input = event.currentTarget;
    const settings = decimalSettings(input);
    const state = currentInputState(input);
    const selectedAll = input.selectionStart === 0 && input.selectionEnd === input.value.length;
    let nextState = state;

    if (event.inputType === "insertFromPaste") {
      const pastedText = event.clipboardData?.getData("text") || event.dataTransfer?.getData("text/plain") || "";
      if (!pastedText) return;
      nextState = stateFromPastedText(pastedText, settings);
    } else if (event.inputType === "insertText") {
      const character = event.data || "";
      if (/\d/.test(character)) {
        if (selectedAll) {
          nextState = { mode: "scaled", digits: character };
        } else if (state.mode === "explicit") {
          nextState = {
            ...state,
            fraction: (state.fraction + character).slice(0, settings.entryDecimals),
          };
        } else {
          nextState = { mode: "scaled", digits: trimDigits(state.digits + character, settings) };
        }
      } else if (/[.,]/.test(character)) {
        const wholeDigits = selectedAll ? "" : trimWholeDigits(state.digits || digitsOnly(input.value), settings);
        nextState = { mode: "explicit", whole: wholeDigits || "0", fraction: "" };
      } else {
        event.preventDefault();
        return;
      }
    } else if (event.inputType === "deleteContentBackward" || event.inputType === "deleteContentForward") {
      if (selectedAll) {
        nextState = { mode: "scaled", digits: "" };
      } else if (state.mode === "explicit" && state.fraction) {
        nextState = { ...state, fraction: state.fraction.slice(0, -1) };
      } else {
        nextState = { mode: "scaled", digits: (state.digits || digitsOnly(input.value)).slice(0, -1) };
      }
    } else {
      return;
    }

    event.preventDefault();
    input.dataset.autoDecimalTouched = "true";
    renderInputState(input, nextState, settings);
  };

  const handleAutoDecimalInputFallback = (event) => {
    const input = event.currentTarget;
    const settings = decimalSettings(input);
    const nextState = stateFromPastedText(input.value, settings);
    input.dataset.autoDecimalTouched = "true";
    renderInputState(input, nextState, settings);
  };

  const normalizeAutoDecimalInput = (input) => {
    if (input.dataset.autoDecimalTouched !== "true") return;
    input.value = decimalValue(input, decimalSettings(input));
  };

  document.querySelectorAll("[data-auto-decimal]").forEach((input) => {
    input.addEventListener("beforeinput", handleAutoDecimalBeforeInput);
    input.addEventListener("input", handleAutoDecimalInputFallback);
    input.form?.addEventListener("submit", () => normalizeAutoDecimalInput(input));
  });

  document.querySelectorAll("[data-batch-state-form]").forEach((form) => {
    const stateSelect = form.querySelector('select[name="state"]');
    const qaOverride = form.querySelector("[data-qa-override]");
    if (!stateSelect) return;

    stateSelect.addEventListener("change", () => {
      if (stateSelect.value === stateSelect.dataset.currentState) return;
      if (qaOverride) qaOverride.value = "false";
      if (stateSelect.value === "PRODUCED" && form.dataset.qaSatisfied !== "true") {
        const required = form.dataset.qaRequired || "0";
        const completed = form.dataset.qaCompleted || "0";
        const confirmed = window.confirm(
          `QA measurements are incomplete.\n\nRequired samples: ${required}\nCompleted samples: ${completed}\n\nTransition to Produced anyway?`
        );
        if (!confirmed) {
          stateSelect.value = stateSelect.dataset.currentState;
          return;
        }
        if (qaOverride) qaOverride.value = "true";
      }
      form.submit();
    });
  });

  document.querySelectorAll("[data-garmin-import-form]").forEach((form) => {
    const fileInput = form.querySelector('input[type="file"]');
    if (!fileInput) return;

    fileInput.addEventListener("change", () => {
      if (!fileInput.files.length) return;
      form.submit();
    });
  });

  document.querySelectorAll("[data-lot-filter-form]").forEach((form) => {
    const sourceSelect = form.querySelector("[data-lot-source-select]");
    const dependentSelect = form.querySelector("[data-dependent-lot-select]");
    const optionTemplate = form.querySelector("template[data-dependent-lot-options]");
    if (!sourceSelect || !dependentSelect || !optionTemplate) return;

    const defaultOption = dependentSelect.querySelector("option");
    if (!defaultOption) return;
    const lotOptions = Array.from(optionTemplate.content.querySelectorAll("option"));
    const syncDependentLots = () => {
      const selectedSource = sourceSelect.selectedOptions[0];
      const itemId = selectedSource ? selectedSource.dataset.itemId : "";
      const previousValue = dependentSelect.value;
      while (dependentSelect.firstChild) {
        dependentSelect.removeChild(dependentSelect.firstChild);
      }
      dependentSelect.appendChild(defaultOption.cloneNode(true));

      if (itemId) {
        lotOptions
          .filter((option) => option.dataset.itemId === itemId)
          .forEach((option) => dependentSelect.appendChild(option.cloneNode(true)));
      }

      const stillAvailable = Array.from(dependentSelect.options).some((option) => option.value === previousValue);
      dependentSelect.value = stillAvailable ? previousValue : "";
      dependentSelect.disabled = !itemId;
    };

    sourceSelect.addEventListener("change", syncDependentLots);
    syncDependentLots();
  });
})();
