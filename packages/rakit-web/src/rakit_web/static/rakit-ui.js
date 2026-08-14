/* Small progressive enhancement for server-rendered destructive preview dialogs. */
function rakitInput(form, name, value) {
  form.querySelectorAll(`input[name="${CSS.escape(name)}"]`).forEach((node) => node.remove());
  const input = document.createElement("input");
  input.type = "hidden";
  input.name = name;
  input.value = value;
  form.append(input);
}

function rakitRemoveInputs(form, name) {
  form.querySelectorAll(`input[name="${CSS.escape(name)}"]`).forEach((node) => node.remove());
}

function rakitRestoreClear(form, prefix) {
  rakitRemoveInputs(form, `${prefix}clear`);
  const select = form.querySelector(`[name="${CSS.escape(`${prefix}set`)}"]`);
  if (select instanceof HTMLSelectElement) select.value = form.dataset.rakitClearPrevious || "";
  delete form.dataset.rakitClearPrevious;
  delete form.dataset.rakitClearPrefix;
}

function rakitShowPreview(root) {
  const dialog = root.querySelector("[data-rakit-preview-dialog]");
  if (!dialog || dialog.open) return;
  document.querySelectorAll("[data-rakit-preview-dialog]").forEach((node) => {
    if (node !== dialog) node.remove();
  });
  document.body.append(dialog);
  dialog.showModal();
  dialog.querySelector("[data-rakit-confirm-preview]")?.focus();
  dialog.addEventListener("close", () => {
    const form = document.querySelector("form[action]");
    const clearPrefix = dialog.dataset.rakitClearPrefix;
    if (form instanceof HTMLFormElement && clearPrefix && dialog.returnValue !== "confirm") {
      rakitRestoreClear(form, clearPrefix);
    }
    if (form instanceof HTMLFormElement) {
      delete form.dataset.rakitClearPrevious;
      delete form.dataset.rakitClearPrefix;
    }
    dialog.remove();
  }, { once: true });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close("cancel");
  });
  dialog.querySelector("[data-rakit-confirm-preview]")?.addEventListener("click", () => {
    const form = document.querySelector("form[action]");
    if (!form) return;
    const prefix = dialog.dataset.rakitPrefix;
    const identity = dialog.dataset.rakitDeleteIdentity;
    if (!prefix) return;
    if (identity) {
      const intent = form.querySelector(`[name="${CSS.escape(`${prefix}delete_intent__${identity}`)}"]`);
      if (intent instanceof HTMLInputElement) intent.checked = true;
      rakitInput(form, `${prefix}delete__${identity}`, dialog.dataset.rakitConfirmation || "");
      rakitInput(form, `${prefix}delete_impact__${identity}`, dialog.dataset.rakitImpact || "");
      const row = form.querySelector(`[data-rakit-row="${CSS.escape(identity)}"]`);
      row?.setAttribute("data-rakit-pending-delete", "true");
      row?.querySelector("[data-rakit-delete-status]")?.classList.remove("hidden");
      row?.querySelector("[data-rakit-preview-delete]")?.classList.add("hidden");
      row?.querySelector("[data-rakit-delete-undo]")?.classList.remove("hidden");
    } else {
      rakitInput(form, `${prefix}destructive_confirmation`, dialog.dataset.rakitConfirmation || "");
      rakitInput(form, `${prefix}confirmation_intent`, dialog.dataset.rakitConfirmationIntent || "");
      rakitInput(form, `${prefix}confirmation_impact`, dialog.dataset.rakitImpact || "");
      delete form.dataset.rakitClearPrevious;
    }
    dialog.close("confirm");
  });
}

function rakitRemoveDeleteState(form, identity, prefix) {
  const intent = form.querySelector(`[name="${CSS.escape(`${prefix}delete_intent__${identity}`)}"]`);
  intent?.remove();
  form.querySelectorAll(
    `[name="${CSS.escape(`${prefix}delete__${identity}`)}"],` +
      ` [name="${CSS.escape(`${prefix}delete_impact__${identity}`)}"]`,
  ).forEach((node) => node.remove());
  const row = form.querySelector(`[data-rakit-row="${CSS.escape(identity)}"]`);
  row?.removeAttribute("data-rakit-pending-delete");
  row?.querySelector("[data-rakit-delete-status]")?.classList.add("hidden");
  row?.querySelector("[data-rakit-preview-delete]")?.classList.remove("hidden");
  row?.querySelector("[data-rakit-delete-undo]")?.classList.add("hidden");
}

function rakitAddDraft(control) {
  const template = control.parentElement?.querySelector("[data-rakit-draft-template]");
  const list = control.parentElement?.querySelector("[data-rakit-draft-list]");
  if (!(template instanceof HTMLTemplateElement) || !(list instanceof HTMLElement)) return;
  const row = template.content.firstElementChild?.cloneNode(true);
  if (!(row instanceof HTMLElement)) return;
  const key = `new-${crypto.randomUUID()}`;
  const prefix = template.dataset.rakitPrefix || "";
  row.querySelectorAll("[data-rakit-draft-field]").forEach((input) => {
    if (input instanceof HTMLInputElement) {
      input.name = `${prefix}create__${key}__${input.dataset.rakitDraftField}`;
      input.removeAttribute("data-rakit-draft-field");
    }
  });
  list.append(row);
  row.querySelector("input")?.focus();
}

document.addEventListener("DOMContentLoaded", () => rakitShowPreview(document));
document.addEventListener("click", (event) => {
  const target = event.target;
  const addDraft = target.closest("[data-rakit-add-draft]");
  if (addDraft instanceof HTMLElement) {
    rakitAddDraft(addDraft);
    return;
  }
  const removeDraft = target.closest("[data-rakit-remove-draft]");
  if (removeDraft instanceof HTMLElement) {
    removeDraft.closest("[data-rakit-draft-row]")?.remove();
    return;
  }
  const clear = target.closest("[data-rakit-clear-selection]");
  if (clear instanceof HTMLElement) {
    const form = clear.closest("form");
    const prefix = clear.dataset.rakitPrefix;
    if (!(form instanceof HTMLFormElement) || !prefix) return;
    const select = form.querySelector(`[name="${CSS.escape(`${prefix}set`)}"]`);
    form.dataset.rakitClearPrevious = select instanceof HTMLSelectElement ? select.value : "";
    if (select instanceof HTMLSelectElement) select.value = "";
    rakitInput(form, `${prefix}clear`, "true");
    const previewPath = clear.dataset.rakitPreviewPath;
    if (previewPath && window.htmx) {
      form.dataset.rakitClearPrefix = prefix;
      const values = window.htmx.values(form, "post");
      values[`${prefix}clear`] = "true";
      window.htmx.ajax("POST", previewPath, {
        source: clear,
        values,
        target: "#rakit-dialog-root",
        swap: "innerHTML",
      });
    }
    return;
  }
  const undo = target.closest("[data-rakit-delete-undo]");
  if (undo instanceof HTMLElement) {
    const form = undo.closest("form");
    const prefix = undo.closest("[data-rakit-relationship-panel]")?.dataset.rakitPrefix || "";
    const identity = undo.dataset.rakitIdentity;
    if (form instanceof HTMLFormElement && prefix && identity) {
      rakitRemoveDeleteState(form, identity, prefix);
    }
  }
});

document.addEventListener("htmx:afterSwap", (event) => {
  rakitShowPreview(event.target);
  const form = document.querySelector("form[action]");
  if (form instanceof HTMLFormElement && !document.querySelector("[data-rakit-preview-dialog]")) {
    const prefix = form.dataset.rakitClearPrefix;
    if (prefix) rakitRestoreClear(form, prefix);
  }
});

document.addEventListener("htmx:afterRequest", (event) => {
  const form = document.querySelector("form[action]");
  if (form instanceof HTMLFormElement && event.detail?.successful === false) {
    const prefix = form.dataset.rakitClearPrefix;
    if (prefix) rakitRestoreClear(form, prefix);
  }
});
