(() => {
  "use strict";

  const initialized = new WeakSet();

  function announce(root, message) {
    const local = root.querySelector("[data-rakit-widget-status]");
    if (local) local.textContent = message;
  }

  function initializeSearchableSelect(root) {
    const input = root.querySelector("[data-rakit-searchable-select-input]");
    const select = root.querySelector("select");
    if (!input || !select) return;
    input.hidden = false;
    input.addEventListener("input", () => {
      const query = input.value.trim().toLocaleLowerCase();
      for (const option of select.options) {
        const visible = !query || option.text.toLocaleLowerCase().includes(query);
        option.hidden = !visible;
      }
    });
  }

  function initializeSwitch(root) {
    const checkbox = root.querySelector('input[type="checkbox"]');
    const label = root.querySelector("[data-rakit-switch-label]");
    if (!checkbox || !label) return;
    const onLabel = root.dataset.rakitOnLabel || "On";
    const offLabel = root.dataset.rakitOffLabel || "Off";
    const sync = () => {
      label.textContent = checkbox.checked ? onLabel : offLabel;
    };
    checkbox.addEventListener("change", sync);
    sync();
  }

  function initializeFile(root) {
    const input = root.querySelector("[data-rakit-file-input]");
    const summary = root.querySelector("[data-rakit-file-summary]");
    const preview = root.querySelector("[data-rakit-image-preview]");
    const previewImage = root.querySelector("[data-rakit-image-preview-image]");
    if (!input) return;

    let objectUrl = null;
    const resetPreview = () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = null;
      if (preview) preview.hidden = true;
      if (previewImage) previewImage.removeAttribute("src");
    };

    input.addEventListener("change", () => {
      resetPreview();
      const file = input.files && input.files[0];
      if (!file) {
        if (summary) summary.textContent = "";
        return;
      }
      if (summary) {
        const kilobytes = Math.max(1, Math.round(file.size / 1024));
        summary.textContent = `${file.name} · ${kilobytes} KB · ${file.type || "unknown type"}`;
      }
      if (preview && previewImage && file.type.startsWith("image/")) {
        objectUrl = URL.createObjectURL(file);
        previewImage.src = objectUrl;
        preview.hidden = false;
      }
    });
  }

  function parseCandidateMarkup(markup) {
    const documentFragment = new DOMParser().parseFromString(markup, "text/html");
    return Array.from(documentFragment.querySelectorAll("[data-rakit-option]")).map((node) => ({
      identity: node.dataset.rakitOptionIdentity || "",
      label: node.dataset.rakitOptionLabel || node.textContent.trim(),
      description: node.dataset.rakitOptionDescription || "",
    })).filter((item) => item.identity);
  }

  function initializeAutocomplete(root) {
    const input = root.querySelector("[data-rakit-autocomplete-input]");
    const listbox = root.querySelector("[data-rakit-autocomplete-listbox]");
    const enhanced = root.querySelector("[data-rakit-autocomplete-enhanced]");
    const fallback = root.querySelector("[data-rakit-autocomplete-fallback]");
    const chips = root.querySelector("[data-rakit-autocomplete-chips]");
    const selectedLabel = root.querySelector("[data-rakit-autocomplete-selection]");
    const clearButton = root.querySelector("[data-rakit-autocomplete-clear]");
    const optionsUrl = root.dataset.rakitOptionsUrl;
    const prefix = root.dataset.rakitPrefix || "";
    const mode = root.dataset.rakitMode || "single";
    const minQueryLength = Number.parseInt(root.dataset.rakitMinQueryLength || "2", 10);
    if (!input || !listbox || !enhanced || !fallback || !optionsUrl) return;

    enhanced.hidden = false;
    fallback.hidden = true;

    const selected = new Map();
    const existing = new Set(
      Array.from(root.closest("[data-rakit-relationship-panel]")?.querySelectorAll("[data-rakit-related-identity]") || [])
        .map((node) => node.dataset.rakitRelatedIdentity)
        .filter(Boolean),
    );
    let activeIndex = -1;
    let results = [];
    let controller = null;
    let requestSequence = 0;
    let debounceTimer = null;

    function hiddenInputs() {
      return Array.from(root.querySelectorAll("input[data-rakit-autocomplete-value]"));
    }

    function closeListbox() {
      activeIndex = -1;
      listbox.hidden = true;
      listbox.innerHTML = "";
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
    }

    function syncActive() {
      const options = Array.from(listbox.querySelectorAll('[role="option"]'));
      options.forEach((option, index) => {
        const active = index === activeIndex;
        option.setAttribute("aria-selected", active ? "true" : "false");
        option.classList.toggle("is-active", active);
      });
      const active = options[activeIndex];
      if (active) {
        input.setAttribute("aria-activedescendant", active.id);
        active.scrollIntoView({ block: "nearest" });
      } else {
        input.removeAttribute("aria-activedescendant");
      }
    }

    function addSingle(identity, label) {
      const select = fallback.querySelector("select");
      if (!select) return;
      let option = Array.from(select.options).find((candidate) => candidate.value === identity);
      if (!option) {
        option = document.createElement("option");
        option.value = identity;
        option.textContent = label;
        select.append(option);
      }
      select.value = identity;
      input.value = label;
      if (selectedLabel) selectedLabel.textContent = label;
      if (clearButton) clearButton.hidden = false;
      announce(root, `${label} selected.`);
    }

    function removeMulti(identity) {
      const entry = selected.get(identity);
      if (!entry) return;
      entry.input.remove();
      entry.chip.remove();
      selected.delete(identity);
      announce(root, `${entry.label} removed.`);
    }

    function addMulti(identity, label) {
      if (selected.has(identity) || existing.has(identity)) return;
      const hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.name = `${prefix}link__${identity}`;
      hidden.value = identity;
      hidden.dataset.rakitAutocompleteValue = identity;
      root.append(hidden);

      const chip = document.createElement("span");
      chip.className = "rakit-choice-chip";
      const text = document.createElement("span");
      text.textContent = label;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "rakit-choice-chip-remove";
      remove.setAttribute("aria-label", `Remove ${label}`);
      remove.textContent = "×";
      remove.addEventListener("click", () => removeMulti(identity));
      chip.append(text, remove);
      if (chips) chips.append(chip);
      selected.set(identity, { input: hidden, chip, label });
      input.value = "";
      announce(root, `${label} selected.`);
    }

    if (mode === "single") {
      const select = fallback.querySelector("select");
      const current = select?.selectedOptions?.[0];
      if (current && current.value) {
        input.value = current.textContent.trim();
        if (selectedLabel) selectedLabel.textContent = current.textContent.trim();
      }
    }

    for (const hidden of hiddenInputs()) {
      const identity = hidden.value;
      const label = hidden.dataset.rakitAutocompleteLabel || identity;
      if (!identity || selected.has(identity)) continue;
      const chip = root.querySelector(`[data-rakit-chip-identity="${CSS.escape(identity)}"]`);
      if (chip) selected.set(identity, { input: hidden, chip, label });
    }

    function choose(index) {
      const item = results[index];
      if (!item) return;
      if (mode === "multi") addMulti(item.identity, item.label);
      else addSingle(item.identity, item.label);
      closeListbox();
      input.focus({ preventScroll: true });
    }

    function renderResults(items) {
      results = items.filter((item) => !existing.has(item.identity) && !selected.has(item.identity));
      listbox.innerHTML = "";
      activeIndex = results.length ? 0 : -1;
      if (!results.length) {
        const empty = document.createElement("li");
        empty.className = "rakit-autocomplete-empty";
        empty.textContent = "No matching candidates.";
        listbox.append(empty);
        announce(root, "No matching candidates.");
      } else {
        results.forEach((item, index) => {
          const option = document.createElement("li");
          option.id = `${listbox.id}-option-${index}`;
          option.className = "rakit-autocomplete-option";
          option.setAttribute("role", "option");
          option.setAttribute("aria-selected", index === activeIndex ? "true" : "false");
          const label = document.createElement("span");
          label.className = "rakit-autocomplete-option-label";
          label.textContent = item.label;
          option.append(label);
          if (item.description) {
            const description = document.createElement("span");
            description.className = "rakit-autocomplete-option-description";
            description.textContent = item.description;
            option.append(description);
          }
          option.addEventListener("pointerdown", (event) => {
            event.preventDefault();
            choose(index);
          });
          listbox.append(option);
        });
        announce(root, `${results.length} matching candidates loaded.`);
      }
      listbox.hidden = false;
      input.setAttribute("aria-expanded", "true");
      syncActive();
    }

    async function requestResults(query) {
      const sequence = ++requestSequence;
      if (controller) controller.abort();
      controller = new AbortController();
      announce(root, "Loading candidates...");
      root.setAttribute("aria-busy", "true");
      try {
        const url = new URL(optionsUrl, window.location.href);
        url.searchParams.set("q", query);
        url.searchParams.set("page", "1");
        const response = await fetch(url, {
          headers: { "X-Rakit-Widget": "autocomplete" },
          signal: controller.signal,
          credentials: "same-origin",
        });
        if (!response.ok) throw new Error(`candidate request failed: ${response.status}`);
        const markup = await response.text();
        if (sequence !== requestSequence) return;
        renderResults(parseCandidateMarkup(markup));
      } catch (error) {
        if (error && error.name === "AbortError") return;
        if (sequence !== requestSequence) return;
        results = [];
        closeListbox();
        announce(root, "Could not load candidates. Try again.");
      } finally {
        if (sequence === requestSequence) root.removeAttribute("aria-busy");
      }
    }

    function queueSearch() {
      const query = input.value.trim();
      window.clearTimeout(debounceTimer);
      if (query.length < minQueryLength) {
        if (controller) controller.abort();
        closeListbox();
        announce(root, `Type at least ${minQueryLength} characters.`);
        return;
      }
      debounceTimer = window.setTimeout(() => requestResults(query), 250);
    }

    input.addEventListener("input", queueSearch);
    input.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" && results.length) {
        event.preventDefault();
        activeIndex = Math.min(results.length - 1, activeIndex + 1);
        syncActive();
      } else if (event.key === "ArrowUp" && results.length) {
        event.preventDefault();
        activeIndex = Math.max(0, activeIndex - 1);
        syncActive();
      } else if (event.key === "Enter" && !listbox.hidden && activeIndex >= 0) {
        event.preventDefault();
        choose(activeIndex);
      } else if (event.key === "Escape") {
        event.preventDefault();
        closeListbox();
      } else if (event.key === "Backspace" && mode === "multi" && !input.value) {
        const last = Array.from(selected.keys()).at(-1);
        if (last) removeMulti(last);
      }
    });

    if (clearButton) {
      clearButton.addEventListener("click", () => {
        const select = fallback.querySelector("select");
        if (select) select.value = "";
        input.value = "";
        if (selectedLabel) selectedLabel.textContent = "No selection";
        clearButton.hidden = true;
        closeListbox();
        announce(root, "Selection cleared.");
      });
    }
  }

  function initializeWidget(root) {
    if (initialized.has(root)) return;
    const kind = root.dataset.rakitWidget;
    if (!kind) return;
    initialized.add(root);
    if (kind === "searchable_select") initializeSearchableSelect(root);
    else if (kind === "switch") initializeSwitch(root);
    else if (kind === "file_upload" || kind === "image_upload") initializeFile(root);
    else if (kind === "autocomplete" || kind === "multi_autocomplete") initializeAutocomplete(root);
  }

  function initializeAll(scope = document) {
    if (scope instanceof Element && scope.matches("[data-rakit-widget]")) initializeWidget(scope);
    scope.querySelectorAll?.("[data-rakit-widget]").forEach(initializeWidget);
  }

  document.addEventListener("DOMContentLoaded", () => initializeAll(document));
  document.addEventListener("htmx:afterSwap", (event) => initializeAll(event.detail.target));
})();
