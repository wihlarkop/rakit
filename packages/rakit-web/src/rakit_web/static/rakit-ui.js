/* Small progressive enhancement for server-rendered destructive preview dialogs. */
function rakitInput(form, name, value) {
  form.querySelectorAll(`input[name="${CSS.escape(name)}"]`).forEach((node) => node.remove());
  const input = document.createElement("input");
  input.type = "hidden";
  input.name = name;
  input.value = value;
  form.append(input);
}

function rakitRemoveRelationshipConfirmation(form, prefix) {
  form.querySelectorAll("input").forEach((node) => {
    if (
      node instanceof HTMLInputElement &&
      [
        `${prefix}destructive_confirmation`,
        `${prefix}confirmation_intent`,
        `${prefix}confirmation_impact`,
      ].includes(node.name)
    ) node.remove();
  });
}

function rakitApplyUnlinkState(form, prefix, identity, pending) {
  if (pending) rakitRemoveDeleteState(form, identity, prefix);
  const input = form.querySelector(
    `[name="${CSS.escape(`${prefix}unlink__${identity}`)}"]`,
  );
  if (input instanceof HTMLInputElement) input.checked = pending;
  form.querySelectorAll("[data-rakit-unlink-action]").forEach((control) => {
    if (
      !(control instanceof HTMLElement) ||
      control.dataset.rakitUnlinkPrefix !== prefix ||
      control.dataset.rakitUnlinkIdentity !== identity
    ) return;
    control.setAttribute("aria-pressed", String(pending));
    control.removeAttribute("data-rakit-preview-unlink");
    control.querySelector("[data-rakit-unlink-label]")?.replaceChildren(
      document.createTextNode(pending ? "Undo removal" : "Remove from relationship"),
    );
  });
  const chip = form.querySelector(
    `[data-rakit-unlink-identity="${CSS.escape(identity)}"][data-rakit-unlink-prefix="${CSS.escape(prefix)}"]`,
  )?.closest(".rakit-chip");
  chip?.classList.toggle("opacity-55", pending);
  chip?.classList.toggle("line-through", pending);
  const row = form.querySelector(`[data-rakit-row="${CSS.escape(identity)}"]`);
  row?.toggleAttribute("data-rakit-pending-unlink", pending);
  row?.querySelector("[data-rakit-unlink-status]")?.classList.toggle("hidden", !pending);
  if (!pending) {
    const hasPendingDelete = [...form.querySelectorAll("input")].some(
      (node) =>
        node instanceof HTMLInputElement &&
        node.name.startsWith(`${prefix}delete_intent__`) &&
        node.checked,
    );
    const hasPendingUnlink = [...form.querySelectorAll("input")].some(
      (node) =>
        node instanceof HTMLInputElement &&
        node.name.startsWith(`${prefix}unlink__`) &&
        node.checked,
    );
    const clear = form.querySelector(`[name="${CSS.escape(`${prefix}clear`)}"]`);
    if (!hasPendingDelete && !hasPendingUnlink && !clear) {
      rakitRemoveRelationshipConfirmation(form, prefix);
    }
  }
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
    const unlinkIdentity = dialog.dataset.rakitUnlinkIdentity;
    const clearPrefix = dialog.dataset.rakitClearPrefix;
    if (!prefix) return;
    if (identity) {
      rakitApplyUnlinkState(form, prefix, identity, false);
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
      if (unlinkIdentity) {
        rakitApplyUnlinkState(form, prefix, unlinkIdentity, true);
      }
      if (clearPrefix) {
        const select = form.querySelector(`[name="${CSS.escape(`${clearPrefix}set`)}"]`);
        if (select instanceof HTMLSelectElement) select.value = "";
        rakitInput(form, `${clearPrefix}clear`, "true");
      }
      rakitInput(form, `${prefix}destructive_confirmation`, dialog.dataset.rakitConfirmation || "");
      rakitInput(form, `${prefix}confirmation_intent`, dialog.dataset.rakitConfirmationIntent || "");
      rakitInput(form, `${prefix}confirmation_impact`, dialog.dataset.rakitImpact || "");
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
  const unlink = target.closest("[data-rakit-unlink-action]");
  if (unlink instanceof HTMLElement && !unlink.hasAttribute("data-rakit-preview-unlink")) {
    const form = unlink.closest("form");
    const prefix = unlink.dataset.rakitUnlinkPrefix;
    const identity = unlink.dataset.rakitUnlinkIdentity;
    if (form instanceof HTMLFormElement && prefix && identity) {
      const input = form.querySelector(
        `[name="${CSS.escape(`${prefix}unlink__${identity}`)}"]`,
      );
      rakitApplyUnlinkState(form, prefix, identity, !(input instanceof HTMLInputElement && input.checked));
    }
    return;
  }
  const clear = target.closest("[data-rakit-clear-selection]");
  if (clear instanceof HTMLElement) {
    const form = clear.closest("form");
    const prefix = clear.dataset.rakitPrefix;
    if (!(form instanceof HTMLFormElement) || !prefix) return;
    const previewPath = clear.dataset.rakitPreviewPath;
    if (previewPath && window.htmx) {
      const values = window.htmx.values(form, "post");
      values[`${prefix}clear`] = "true";
      window.htmx.ajax("POST", previewPath, {
        source: clear,
        values,
        target: "#rakit-dialog-root",
        swap: "innerHTML",
      });
    } else {
      const select = form.querySelector(`[name="${CSS.escape(`${prefix}set`)}"]`);
      if (select instanceof HTMLSelectElement) select.value = "";
      rakitInput(form, `${prefix}clear`, "true");
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

document.addEventListener("change", (event) => {
  const select = event.target;
  if (!(select instanceof HTMLSelectElement) || !select.matches("[data-rakit-relationship-set]")) {
    return;
  }
  if (!select.value) return;
  const form = select.closest("form");
  const prefix = select.dataset.rakitPrefix;
  if (!(form instanceof HTMLFormElement) || !prefix) return;
  form.querySelector(`[name="${CSS.escape(`${prefix}clear`)}"]`)?.remove();
  rakitRemoveRelationshipConfirmation(form, prefix);
});

document.addEventListener("htmx:afterSwap", (event) => rakitShowPreview(event.target));
