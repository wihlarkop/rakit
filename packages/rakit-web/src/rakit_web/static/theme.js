const RAKIT_THEME_KEY = "rakit.theme";
const RAKIT_THEMES = new Set(["light", "dark", "system"]);
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

function rakitApplyTheme(preference) {
  const safePreference = RAKIT_THEMES.has(preference) ? preference : "system";
  document.documentElement.dataset.themePreference = safePreference;
  document.documentElement.dataset.theme = rakitResolvedTheme(safePreference);
  document.querySelectorAll("[data-rakit-theme-select]").forEach((control) => {
    if (control instanceof HTMLSelectElement) control.value = safePreference;
  });
}

let rakitThemePreference = rakitStoredTheme();
rakitApplyTheme(rakitThemePreference);

RAKIT_DARK_MEDIA.addEventListener("change", () => {
  if (rakitThemePreference === "system") rakitApplyTheme(rakitThemePreference);
});

document.addEventListener("DOMContentLoaded", () => {
  rakitApplyTheme(rakitThemePreference);
  document.querySelectorAll("[data-rakit-theme-select]").forEach((control) => {
    if (!(control instanceof HTMLSelectElement)) return;
    control.addEventListener("change", () => {
      const preference = RAKIT_THEMES.has(control.value) ? control.value : "system";
      rakitThemePreference = preference;
      try {
        localStorage.setItem(RAKIT_THEME_KEY, preference);
      } catch {
        // A blocked storage API must not prevent the theme from working for this page.
      }
      rakitApplyTheme(preference);
    });
  });
});
