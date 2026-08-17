const RAKIT_DESKTOP_NAVIGATION = matchMedia("(min-width: 64rem)");
let rakitMobileNavigationReturnFocus = null;

function rakitMobileNavigation() {
  const navigation = document.querySelector("[data-rakit-mobile-navigation]");
  return navigation instanceof HTMLDialogElement ? navigation : null;
}

function rakitMobileNavigationTrigger() {
  const trigger = document.querySelector("[data-rakit-mobile-navigation-trigger]");
  return trigger instanceof HTMLButtonElement ? trigger : null;
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
  const navigation = rakitMobileNavigation();
  if (!navigation) return;
  navigation.addEventListener("close", rakitResetMobileNavigation);
});

RAKIT_DESKTOP_NAVIGATION.addEventListener("change", (event) => {
  if (event.matches) rakitCloseMobileNavigation();
});
