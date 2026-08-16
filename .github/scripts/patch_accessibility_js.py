from pathlib import Path

path = Path("packages/rakit-web/src/rakit_web/static/rakit-ui.js")
text = path.read_text()

anchor = "/* Small progressive enhancement for server-rendered destructive preview dialogs. */\n"
addition = '''/* Small progressive enhancement for server-rendered destructive preview dialogs. */
let rakitDialogReturnFocus = null;

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
'''
if anchor not in text:
    raise RuntimeError("missing script header")
text = text.replace(anchor, addition, 1)

old = '''function rakitShowPreview(root) {
  const dialog = root.querySelector("[data-rakit-preview-dialog]");
  if (!dialog || dialog.open) return;
'''
new = '''function rakitShowPreview(root) {
  const dialog = root.querySelector("[data-rakit-preview-dialog]");
  if (!dialog || dialog.open) return;
  rakitDialogReturnFocus = document.activeElement instanceof HTMLElement
    ? document.activeElement
    : null;
'''
if old not in text:
    raise RuntimeError("missing preview opener anchor")
text = text.replace(old, new, 1)

old = '''  dialog.addEventListener("close", () => {
    const form = document.querySelector("form[action]");
    dialog.remove();
  }, { once: true });
'''
new = '''  dialog.addEventListener("close", () => {
    dialog.remove();
    rakitReturnFocus();
  }, { once: true });
'''
if old not in text:
    raise RuntimeError("missing dialog close anchor")
text = text.replace(old, new, 1)

old = 'document.addEventListener("DOMContentLoaded", () => rakitShowPreview(document));\n'
new = '''document.addEventListener("DOMContentLoaded", () => {
  rakitShowPreview(document);
  rakitFocusTarget(document);
});
'''
if old not in text:
    raise RuntimeError("missing DOMContentLoaded anchor")
text = text.replace(old, new, 1)

old = 'document.addEventListener("htmx:afterSwap", (event) => rakitShowPreview(event.target));\n'
new = '''document.addEventListener("htmx:afterSwap", (event) => {
  const root = event.target instanceof HTMLElement ? event.target : document;
  rakitShowPreview(root);
  rakitFocusTarget(root);
});

document.addEventListener("rakit:announce", (event) => {
  rakitAnnounce(event.detail?.message);
});
'''
if old not in text:
    raise RuntimeError("missing HTMX anchor")
text = text.replace(old, new, 1)
path.write_text(text)
