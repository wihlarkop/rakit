const RAKIT_DESKTOP_NAVIGATION = matchMedia("(min-width: 64rem)");
const RAKIT_SIDEBAR_COLLAPSED_KEY = "rakit.sidebar.collapsed";
let rakitMobileNavigationReturnFocus = null;

function rakitMobileNavigation() {
  const navigation = document.querySelector("[data-rakit-mobile-navigation]");
  return navigation instanceof HTMLDialogElement ? navigation : null;
}

function rakitMobileNavigationTrigger() {
  const trigger = document.querySelector("[data-rakit-mobile-navigation-trigger]");
  return trigger instanceof HTMLButtonElement ? trigger : null;
}

function rakitDesktopNavigation() {
  return document.querySelector("[data-rakit-desktop-navigation]");
}

function rakitDesktopNavigationToggle() {
  const toggle = document.querySelector("[data-rakit-desktop-navigation-toggle]");
  return toggle instanceof HTMLButtonElement ? toggle : null;
}

function rakitStoredSidebarCollapsed() {
  try {
    return localStorage.getItem(RAKIT_SIDEBAR_COLLAPSED_KEY) === "true";
  } catch {
    return false;
  }
}

function rakitApplyDesktopNavigationCollapsed(collapsed) {
  const navigation = rakitDesktopNavigation();
  const toggle = rakitDesktopNavigationToggle();
  if (!(navigation instanceof HTMLElement) || !toggle) return;

  navigation.toggleAttribute("data-rakit-desktop-navigation-collapsed", collapsed);
  toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
  toggle.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");

  const expandedIcon = toggle.querySelector("[data-rakit-sidebar-expanded-icon]");
  const collapsedIcon = toggle.querySelector("[data-rakit-sidebar-collapsed-icon]");
  if (expandedIcon instanceof HTMLElement) expandedIcon.hidden = collapsed;
  if (collapsedIcon instanceof HTMLElement) collapsedIcon.hidden = !collapsed;
}

function rakitSetDesktopNavigationCollapsed(collapsed) {
  rakitApplyDesktopNavigationCollapsed(collapsed);
  try {
    localStorage.setItem(RAKIT_SIDEBAR_COLLAPSED_KEY, collapsed ? "true" : "false");
  } catch {
    // Persistence is optional; the sidebar remains fully usable without storage access.
  }
}

function rakitOpenMobileNavigation(trigger) {
  const navigation = rakitMobileNavigation();
  if (!navigation || navigation.open) return;
  rakitMobileNavigationReturnFocus = trigger;
  trigger.setAttribute("aria-expanded", "true");
  document.body.setAttribute("data-rakit-mobile-navigation-open", "");
  navigation.showModal();
  navigation.querySelector("[data-rakit-mobile-navigation-close]")?.focus();
}

function rakitCloseMobileNavigation() {
  const navigation = rakitMobileNavigation();
  if (navigation?.open) navigation.close();
}

function rakitResetMobileNavigation() {
  const trigger = rakitMobileNavigationTrigger();
  trigger?.setAttribute("aria-expanded", "false");
  document.body.removeAttribute("data-rakit-mobile-navigation-open");
  const returnFocus = rakitMobileNavigationReturnFocus;
  rakitMobileNavigationReturnFocus = null;
  if (
    returnFocus instanceof HTMLElement &&
    document.contains(returnFocus) &&
    !RAKIT_DESKTOP_NAVIGATION.matches
  ) {
    returnFocus.focus();
  }
}

document.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof Element)) return;

  const desktopToggle = target.closest("[data-rakit-desktop-navigation-toggle]");
  if (desktopToggle instanceof HTMLButtonElement) {
    const navigation = rakitDesktopNavigation();
    const collapsed = navigation?.hasAttribute("data-rakit-desktop-navigation-collapsed") ?? false;
    rakitSetDesktopNavigationCollapsed(!collapsed);
    return;
  }

  const trigger = target.closest("[data-rakit-mobile-navigation-trigger]");
  if (trigger instanceof HTMLButtonElement) {
    rakitOpenMobileNavigation(trigger);
    return;
  }

  const close = target.closest("[data-rakit-mobile-navigation-close]");
  if (close) {
    rakitCloseMobileNavigation();
    return;
  }

  const navigation = rakitMobileNavigation();
  if (!navigation?.open) return;
  if (target === navigation || target.closest("[data-rakit-mobile-navigation] a[href]")) {
    rakitCloseMobileNavigation();
  }
});

document.addEventListener("DOMContentLoaded", () => {
  rakitApplyDesktopNavigationCollapsed(rakitStoredSidebarCollapsed());

  const navigation = rakitMobileNavigation();
  if (!navigation) return;
  navigation.addEventListener("close", rakitResetMobileNavigation);
});

RAKIT_DESKTOP_NAVIGATION.addEventListener("change", (event) => {
  if (event.matches) rakitCloseMobileNavigation();
});
