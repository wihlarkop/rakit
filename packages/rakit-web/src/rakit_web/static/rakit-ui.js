/* Small progressive enhancement for server-rendered Rakit interactions. */
let rakitDialogReturnFocus = null;
const rakitGenericDialogReturnFocus = new WeakMap();

function rakitReturnFocus() {
  const target = rakitDialogReturnFocus;
  rakitDialogReturnFocus = null;
  if (target instanceof HTMLElement && document.contains(target)) target.focus();
}

function rakitFocusTarget(root = document) {
  const direct = root instanceof HTMLElement && root.hasAttribute("data-rakit-focus-target")
    ? root
    : null;
  const target = direct || root.querySelector?.("[data-rakit-focus-target]");
  if (!(target instanceof HTMLElement)) return;
  const targetId = target.dataset.rakitFocusTarget;
  const focusTarget = targetId && target.id !== targetId
    ? document.getElementById(targetId) || target
    : target;
  if (!(focusTarget instanceof HTMLElement)) return;
  if (!focusTarget.matches("a, button, input, select, textarea, summary, [tabindex]")) {
    focusTarget.tabIndex = -1;
  }
  focusTarget.focus({ preventScroll: true });
  focusTarget.scrollIntoView({ block: "nearest" });
}

function rakitAnnounce(message) {
  const announcer = document.getElementById("rakit-announcer");
  if (!(announcer instanceof HTMLElement) || !message) return;
  announcer.textContent = "";
  requestAnimationFrame(() => { announcer.textContent = String(message); });
}

function rakitEnhanceGenericDialog(dialog) {
  if (!(dialog instanceof HTMLDialogElement) || dialog.dataset.rakitDialogEnhanced === "true") {
    return;
  }
  dialog.dataset.rakitDialogEnhanced = "true";
  dialog.addEventListener("close", () => {
    const returnFocus = rakitGenericDialogReturnFocus.get(dialog);
    rakitGenericDialogReturnFocus.delete(dialog);
    if (returnFocus instanceof HTMLElement && document.contains(returnFocus)) returnFocus.focus();
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog && dialog.hasAttribute("data-rakit-dialog-backdrop-close")) {
      dialog.close("cancel");
    }
  });
}

function rakitEnhanceGenericDialogs(root = document) {
  const direct = root instanceof HTMLDialogElement && root.hasAttribute("data-rakit-dialog")
    ? [root]
    : [];
  const nested = root.querySelectorAll?.("dialog[data-rakit-dialog]") || [];
  [...direct, ...nested].forEach((dialog) => rakitEnhanceGenericDialog(dialog));
}

function rakitOpenGenericDialog(trigger) {
  if (!(trigger instanceof HTMLElement)) return;
  const dialogId = trigger.getAttribute("aria-controls") || trigger.dataset.rakitDialogTrigger;
  if (!dialogId) return;
  const dialog = document.getElementById(dialogId);
  if (!(dialog instanceof HTMLDialogElement) || dialog.open) return;
  rakitEnhanceGenericDialog(dialog);
  rakitGenericDialogReturnFocus.set(dialog, trigger);
  dialog.showModal();
  const initialFocus = dialog.querySelector(
    "[data-rakit-dialog-initial-focus], [autofocus], button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled)",
  );
  if (initialFocus instanceof HTMLElement) initialFocus.focus();
}

function rakitCloseGenericDialog(control) {
  if (!(control instanceof HTMLElement)) return;
  const dialog = control.closest("dialog[data-rakit-dialog]");
  if (!(dialog instanceof HTMLDialogElement)) return;
  dialog.close(control.dataset.rakitDialogClose || "cancel");
}

function rakitOpenDetailPopovers() {
  return [...document.querySelectorAll("details[open]")].filter(
    (details) => details.querySelector(":scope > .rakit-popover"),
  );
}

function rakitCloseDetailPopover(details, { restoreFocus = false } = {}) {
  if (!(details instanceof HTMLDetailsElement)) return;
  details.removeAttribute("open");
  if (!restoreFocus) return;
  const summary = details.querySelector(":scope > summary");
  if (summary instanceof HTMLElement) summary.focus();
}

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
    if (pending) {
      control.removeAttribute("data-rakit-preview-unlink");
    } else if (control.hasAttribute("data-rakit-unlink-destructive")) {
      control.setAttribute("data-rakit-preview-unlink", "");
    }
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
  rakitDialogReturnFocus = document.activeElement instanceof HTMLElement
    ? document.activeElement
    : null;
  document.querySelectorAll("[data-rakit-preview-dialog]").forEach((node) => {
    if (node !== dialog) node.remove();
  });
  document.body.append(dialog);
  dialog.showModal();
  dialog.querySelector("[data-rakit-confirm-preview]")?.focus();
  dialog.addEventListener("close", () => {
    dialog.remove();
    rakitReturnFocus();
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
  if (intent instanceof HTMLInputElement) intent.checked = false;
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

function rakitStorageGet(key) {
  try {
    return window.sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function rakitStorageSet(key, value) {
  try {
    window.sessionStorage.setItem(key, value);
  } catch {
    // Presentation persistence is optional; filtering never depends on storage.
  }
}

function rakitFilterStorageKey(resourceId, suffix) {
  return `rakit.filter-ui.${resourceId}.${suffix}`;
}

function rakitSetFilterRailVisible(root, visible, { persist = false } = {}) {
  if (!(root instanceof HTMLElement)) return;
  const resourceId = root.dataset.rakitFilterUi;
  const rail = root.querySelector("[data-rakit-filter-rail]");
  const show = root.querySelector("[data-rakit-filter-rail-show]");
  const hide = root.querySelector("[data-rakit-filter-rail-hide]");
  if (rail instanceof HTMLElement) rail.hidden = !visible;
  if (show instanceof HTMLElement) show.hidden = visible;
  if (hide instanceof HTMLElement) hide.hidden = !visible;
  if (persist && resourceId) {
    rakitStorageSet(rakitFilterStorageKey(resourceId, "rail-visible"), String(visible));
  }
}

function rakitEnhanceChoiceOverflow(details) {
  if (!(details instanceof HTMLDetailsElement) || details.dataset.rakitChoiceEnhanced === "true") {
    return;
  }
  details.dataset.rakitChoiceEnhanced = "true";
  const label = details.querySelector("[data-rakit-choice-overflow-label]");
  if (!(label instanceof HTMLElement)) return;
  const moreLabel = details.dataset.rakitChoiceMoreLabel || label.textContent || "Show more";
  const update = () => {
    label.textContent = details.open ? "Show less" : moreLabel;
  };
  details.addEventListener("toggle", update);
  update();
}

function rakitEnhanceFilterGroup(root, details) {
  if (!(root instanceof HTMLElement) || !(details instanceof HTMLDetailsElement)) return;
  if (details.dataset.rakitFilterGroupEnhanced === "true") return;
  details.dataset.rakitFilterGroupEnhanced = "true";
  const resourceId = root.dataset.rakitFilterUi;
  const filterId = details.dataset.rakitFilterGroup;
  if (!resourceId || !filterId) return;
  const key = rakitFilterStorageKey(resourceId, `group.${filterId}`);
  const stored = rakitStorageGet(key);
  if (stored === "true") details.open = true;
  if (stored === "false") details.open = false;
  details.addEventListener("toggle", () => {
    rakitStorageSet(key, String(details.open));
  });
}

function rakitEnhanceFilterUi(root) {
  if (!(root instanceof HTMLElement) || root.dataset.rakitFilterEnhanced === "true") return;
  root.dataset.rakitFilterEnhanced = "true";
  const resourceId = root.dataset.rakitFilterUi;

  const mobileFallback = root.querySelector("[data-rakit-filter-mobile-fallback]");
  const drawerTrigger = root.querySelector("[data-rakit-filter-drawer-trigger]");
  const drawer = root.querySelector("[data-rakit-filter-drawer]");
  if (mobileFallback instanceof HTMLElement) mobileFallback.hidden = true;
  if (drawerTrigger instanceof HTMLElement) drawerTrigger.hidden = false;
  if (drawer instanceof HTMLDialogElement) drawer.hidden = false;

  let visible = root.dataset.rakitFilterDefaultVisible !== "false";
  if (resourceId) {
    const stored = rakitStorageGet(rakitFilterStorageKey(resourceId, "rail-visible"));
    if (stored === "true") visible = true;
    if (stored === "false") visible = false;
  }
  rakitSetFilterRailVisible(root, visible);

  root.querySelectorAll("details[data-rakit-filter-group]").forEach((details) => {
    rakitEnhanceFilterGroup(root, details);
  });
  root.querySelectorAll("details[data-rakit-choice-overflow]").forEach((details) => {
    rakitEnhanceChoiceOverflow(details);
  });
}

function rakitEnhanceFilterUis(root = document) {
  const direct = root instanceof HTMLElement && root.hasAttribute("data-rakit-filter-ui")
    ? [root]
    : [];
  const nested = root.querySelectorAll?.("[data-rakit-filter-ui]") || [];
  [...direct, ...nested].forEach((filterUi) => rakitEnhanceFilterUi(filterUi));
}

function rakitBulkRows(form) {
  return [...form.querySelectorAll("[data-rakit-select-row]")].filter(
    (row) => row instanceof HTMLInputElement && !row.disabled,
  );
}

function rakitSyncBulkSelection(form) {
  if (!(form instanceof HTMLFormElement)) return;
  const rows = rakitBulkRows(form);
  const selected = rows.filter((row) => row.checked);
  const page = form.querySelector("[data-rakit-select-page]");
  if (page instanceof HTMLInputElement) {
    page.checked = rows.length > 0 && selected.length === rows.length;
    page.indeterminate = selected.length > 0 && selected.length < rows.length;
  }
  const count = form.querySelector("[data-rakit-selected-count]");
  if (count instanceof HTMLElement) count.textContent = `${selected.length} selected`;
}

function rakitEnhanceBulkSelections(root = document) {
  const direct = root instanceof HTMLFormElement && root.hasAttribute("data-rakit-bulk-selection")
    ? [root]
    : [];
  const nested = root.querySelectorAll?.("form[data-rakit-bulk-selection]") || [];
  [...direct, ...nested].forEach((form) => rakitSyncBulkSelection(form));
}

function rakitBulkDialog(form) {
  const resourceId = form.dataset.rakitBulkActions;
  if (!resourceId) return null;
  const dialog = document.getElementById(`rakit-bulk-dialog-${resourceId}`);
  return dialog instanceof HTMLDialogElement ? dialog : null;
}

function rakitShowBulkDialog(form, trigger, content) {
  const dialog = rakitBulkDialog(form);
  if (!(dialog instanceof HTMLDialogElement)) return false;
  const target = dialog.querySelector("[data-rakit-bulk-dialog-content]");
  if (!(target instanceof HTMLElement)) return false;
  target.innerHTML = content;
  rakitEnhanceGenericDialog(dialog);
  rakitGenericDialogReturnFocus.set(dialog, trigger);
  if (!dialog.open) dialog.showModal();
  const initialFocus = dialog.querySelector(
    "[data-rakit-dialog-initial-focus], button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled)",
  );
  if (initialFocus instanceof HTMLElement) initialFocus.focus({ preventScroll: true });
  return true;
}

async function rakitOpenBulkReview(form, submitter) {
  const selected = rakitBulkRows(form).filter((row) => row.checked);
  if (!selected.length) {
    const content = `
      <section class="space-y-5" data-rakit-bulk-feedback>
        <header><h1 class="text-xl font-semibold tracking-tight text-rakit-text">Bulk action needs attention</h1></header>
        <div class="rakit-alert rakit-alert-danger" role="alert">Select at least one resource before running a bulk action.</div>
        <footer class="flex justify-end"><button class="rakit-button rakit-button-secondary" type="button" data-rakit-dialog-close>Close</button></footer>
      </section>`;
    rakitShowBulkDialog(form, submitter, content);
    return;
  }

  const url = new URL(submitter.formAction || form.action || window.location.href, window.location.href);
  url.search = "";
  selected.forEach((row) => url.searchParams.append("selected", row.value));
  try {
    const response = await fetch(url, {
      credentials: "same-origin",
      headers: { Accept: "text/html", "X-Rakit-Dialog": "bulk" },
    });
    const content = await response.text();
    if (!rakitShowBulkDialog(form, submitter, content)) window.location.assign(url);
  } catch {
    window.location.assign(url);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  rakitShowPreview(document);
  rakitFocusTarget(document);
  rakitEnhanceFilterUis(document);
  rakitEnhanceGenericDialogs(document);
  rakitEnhanceBulkSelections(document);
});

document.addEventListener("submit", (event) => {
  const form = event.target;
  const submitter = event.submitter;
  if (
    !(form instanceof HTMLFormElement) ||
    !form.hasAttribute("data-rakit-bulk-actions") ||
    !(submitter instanceof HTMLButtonElement) ||
    !submitter.hasAttribute("data-rakit-bulk-review-trigger") ||
    !("HTMLDialogElement" in window)
  ) return;
  event.preventDefault();
  rakitOpenBulkReview(form, submitter);
});

document.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof Element)) return;

  const filterRailHide = target.closest("[data-rakit-filter-rail-hide]");
  if (filterRailHide instanceof HTMLElement) {
    const root = filterRailHide.closest("[data-rakit-filter-ui]");
    if (root instanceof HTMLElement) {
      event.preventDefault();
      rakitSetFilterRailVisible(root, false, { persist: true });
      root.querySelector("[data-rakit-filter-rail-show]")?.focus();
    }
    return;
  }

  const filterRailShow = target.closest("[data-rakit-filter-rail-show]");
  if (filterRailShow instanceof HTMLElement) {
    const root = filterRailShow.closest("[data-rakit-filter-ui]");
    if (root instanceof HTMLElement) {
      event.preventDefault();
      rakitSetFilterRailVisible(root, true, { persist: true });
      root.querySelector("[data-rakit-filter-rail-hide]")?.focus();
    }
    return;
  }

  const dialogTrigger = target.closest("[data-rakit-dialog-trigger]");
  if (dialogTrigger instanceof HTMLElement) {
    event.preventDefault();
    rakitOpenGenericDialog(dialogTrigger);
    return;
  }

  const dialogClose = target.closest("[data-rakit-dialog-close]");
  if (dialogClose instanceof HTMLElement) {
    event.preventDefault();
    rakitCloseGenericDialog(dialogClose);
    return;
  }

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
    if (previewPath) {
      if (!window.htmx) return;
      event.preventDefault();
      const values = window.htmx.values(form, "post");
      values[`${prefix}clear`] = "true";
      window.htmx.ajax("POST", previewPath, {
        source: clear,
        values,
        target: "#rakit-dialog-root",
        swap: "innerHTML",
      });
    } else {
      event.preventDefault();
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

document.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof Node)) return;
  rakitOpenDetailPopovers().forEach((details) => {
    if (!details.contains(target)) rakitCloseDetailPopover(details);
  });
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  const openPopovers = rakitOpenDetailPopovers();
  const details = openPopovers.at(-1);
  if (!(details instanceof HTMLDetailsElement)) return;
  event.preventDefault();
  rakitCloseDetailPopover(details, { restoreFocus: true });
});

document.addEventListener("change", (event) => {
  const control = event.target;
  if (control instanceof HTMLInputElement && control.matches("[data-rakit-select-page]")) {
    const form = control.closest("form[data-rakit-bulk-selection]");
    if (form instanceof HTMLFormElement) {
      rakitBulkRows(form).forEach((row) => { row.checked = control.checked; });
      rakitSyncBulkSelection(form);
    }
    return;
  }
  if (control instanceof HTMLInputElement && control.matches("[data-rakit-select-row]")) {
    const form = control.closest("form[data-rakit-bulk-selection]");
    if (form instanceof HTMLFormElement) rakitSyncBulkSelection(form);
    return;
  }

  const select = control;
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

document.addEventListener("htmx:afterSwap", (event) => {
  const root = event.target instanceof HTMLElement ? event.target : document;
  rakitShowPreview(root);
  rakitFocusTarget(root);
  rakitEnhanceFilterUis(root);
  rakitEnhanceGenericDialogs(root);
  rakitEnhanceBulkSelections(root);
});

document.addEventListener("rakit:announce", (event) => {
  rakitAnnounce(event.detail?.message);
});