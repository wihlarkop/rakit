/* Small progressive enhancement for server-rendered destructive preview dialogs. */
function rakitInput(form, name, value) {
  form.querySelectorAll(`input[name="${CSS.escape(name)}"]`).forEach((node) => node.remove());
  const input = document.createElement("input");
  input.type = "hidden";
  input.name = name;
  input.value = value;
  form.append(input);
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
  dialog.addEventListener("close", () => dialog.remove(), { once: true });
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
    }
    dialog.close("confirm");
  });
}

document.addEventListener("htmx:afterSwap", (event) => rakitShowPreview(event.target));
document.addEventListener("DOMContentLoaded", () => rakitShowPreview(document));
document.addEventListener("click", (event) => {
  const control = event.target.closest("[data-rakit-remove-draft]");
  if (control instanceof HTMLElement) control.closest("[data-rakit-draft-row]")?.remove();
});
