const RAKIT_THEME_KEY = "rakit.theme";
const RAKIT_THEMES = new Set(["light", "dark", "system"]);
const RAKIT_THEME_LABELS = { system: "System", light: "Light", dark: "Dark" };
const RAKIT_DARK_MEDIA = matchMedia("(prefers-color-scheme: dark)");

function rakitStoredTheme() {
  try {
    const value = localStorage.getItem(RAKIT_THEME_KEY);
    return RAKIT_THEMES.has(value) ? value : "system";
  } catch {
    return "system";
  }
}

function rakitResolvedTheme(preference) {
  if (preference === "system") return RAKIT_DARK_MEDIA.matches ? "dark" : "light";
  return preference;
}

function rakitThemeControls() {
  return document.querySelectorAll("[data-rakit-theme-control]");
}

function rakitSyncThemeControl(control, preference) {
  const trigger = control.querySelector("[data-rakit-theme-trigger]");
  const label = control.querySelector("[data-rakit-theme-label]");
  if (trigger instanceof HTMLButtonElement) {
    trigger.setAttribute("aria-label", `Theme: ${RAKIT_THEME_LABELS[preference]}`);
  }
  if (label instanceof HTMLElement) label.textContent = RAKIT_THEME_LABELS[preference];

  control.querySelectorAll("[data-rakit-theme-trigger-icon]").forEach((icon) => {
    if (!(icon instanceof HTMLElement)) return;
    icon.hidden = icon.dataset.rakitThemeTriggerIcon !== preference;
  });

  control.querySelectorAll("[data-rakit-theme-option]").forEach((option) => {
    if (!(option instanceof HTMLButtonElement)) return;
    const selected = option.dataset.rakitThemeOption === preference;
    option.setAttribute("aria-checked", selected ? "true" : "false");
    const check = option.querySelector("[data-rakit-theme-check]");
    if (check instanceof HTMLElement) check.hidden = !selected;
  });
}

function rakitApplyTheme(preference) {
  const safePreference = RAKIT_THEMES.has(preference) ? preference : "system";
  document.documentElement.dataset.themePreference = safePreference;
  document.documentElement.dataset.theme = rakitResolvedTheme(safePreference);
  rakitThemeControls().forEach((control) => rakitSyncThemeControl(control, safePreference));
}

function rakitCloseThemeMenu(control, { focusTrigger = false } = {}) {
  const menu = control.querySelector("[data-rakit-theme-menu]");
  const trigger = control.querySelector("[data-rakit-theme-trigger]");
  if (menu instanceof HTMLElement) menu.hidden = true;
  if (trigger instanceof HTMLButtonElement) {
    trigger.setAttribute("aria-expanded", "false");
    if (focusTrigger) trigger.focus({ preventScroll: true });
  }
}

function rakitCloseOtherThemeMenus(activeControl) {
  rakitThemeControls().forEach((control) => {
    if (control !== activeControl) rakitCloseThemeMenu(control);
  });
}

function rakitThemeOptions(control) {
  return Array.from(control.querySelectorAll("[data-rakit-theme-option]")).filter(
    (option) => option instanceof HTMLButtonElement,
  );
}

function rakitOpenThemeMenu(control, { focusCurrent = false } = {}) {
  const menu = control.querySelector("[data-rakit-theme-menu]");
  const trigger = control.querySelector("[data-rakit-theme-trigger]");
  if (!(menu instanceof HTMLElement) || !(trigger instanceof HTMLButtonElement)) return;

  rakitCloseOtherThemeMenus(control);
  menu.hidden = false;
  trigger.setAttribute("aria-expanded", "true");
  if (!focusCurrent) return;

  const options = rakitThemeOptions(control);
  const selected = options.find((option) => option.getAttribute("aria-checked") === "true");
  (selected || options[0])?.focus({ preventScroll: true });
}

function rakitPersistTheme(preference) {
  try {
    localStorage.setItem(RAKIT_THEME_KEY, preference);
  } catch {
    // A blocked storage API must not prevent the theme from working for this page.
  }
}

let rakitThemePreference = rakitStoredTheme();
rakitApplyTheme(rakitThemePreference);

RAKIT_DARK_MEDIA.addEventListener("change", () => {
  if (rakitThemePreference === "system") rakitApplyTheme(rakitThemePreference);
});

document.addEventListener("DOMContentLoaded", () => {
  rakitApplyTheme(rakitThemePreference);

  document.querySelectorAll("[data-rakit-theme-control]").forEach((control) => {
    const trigger = control.querySelector("[data-rakit-theme-trigger]");
    if (!(trigger instanceof HTMLButtonElement)) return;

    trigger.addEventListener("click", () => {
      const menu = control.querySelector("[data-rakit-theme-menu]");
      if (!(menu instanceof HTMLElement)) return;
      if (menu.hidden) rakitOpenThemeMenu(control);
      else rakitCloseThemeMenu(control);
    });

    trigger.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        rakitOpenThemeMenu(control, { focusCurrent: true });
      }
      if (event.key === "Escape") {
        event.preventDefault();
        rakitCloseThemeMenu(control, { focusTrigger: true });
      }
    });

    const options = rakitThemeOptions(control);
    options.forEach((option, index) => {
      option.addEventListener("click", () => {
        const preference = option.dataset.rakitThemeOption;
        if (!RAKIT_THEMES.has(preference)) return;
        rakitThemePreference = preference;
        rakitPersistTheme(preference);
        rakitApplyTheme(preference);
        rakitCloseThemeMenu(control, { focusTrigger: true });
      });

      option.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          rakitCloseThemeMenu(control, { focusTrigger: true });
          return;
        }
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          const delta = event.key === "ArrowDown" ? 1 : -1;
          options[(index + delta + options.length) % options.length]?.focus({ preventScroll: true });
          return;
        }
        if (event.key === "Home" || event.key === "End") {
          event.preventDefault();
          options[event.key === "Home" ? 0 : options.length - 1]?.focus({ preventScroll: true });
        }
      });
    });
  });

  document.addEventListener("click", (event) => {
    if (!(event.target instanceof Node)) return;
    rakitThemeControls().forEach((control) => {
      if (!control.contains(event.target)) rakitCloseThemeMenu(control);
    });
  });
});
