from pathlib import Path


def replace_exact(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, found {count}")
    target.write_text(text.replace(old, new, 1))


replace_exact(
    "packages/rakit-web/src/rakit_web/templates/components/admin_navigation.html",
    '    <nav class="min-h-0 flex-1 overflow-y-auto px-3 py-5" aria-label="Primary navigation">\n',
    '    <nav\n'
    '      data-rakit-desktop-navigation-scroll\n'
    '      data-rakit-navigation-scroll-key="{{ navigation.dashboard.path }}"\n'
    '      class="min-h-0 flex-1 overflow-y-auto px-3 py-5"\n'
    '      aria-label="Primary navigation"\n'
    '    >\n',
)

replace_exact(
    "packages/rakit-web/src/rakit_web/static/rakit-shell.js",
    'const RAKIT_SIDEBAR_COLLAPSED_KEY = "rakit.sidebar.collapsed";\n',
    'const RAKIT_SIDEBAR_COLLAPSED_KEY = "rakit.sidebar.collapsed";\n'
    'const RAKIT_SIDEBAR_SCROLL_KEY_PREFIX = "rakit.sidebar.scroll";\n',
)

replace_exact(
    "packages/rakit-web/src/rakit_web/static/rakit-shell.js",
    '''function rakitDesktopNavigationToggle() {
  const toggle = document.querySelector("[data-rakit-desktop-navigation-toggle]");
  return toggle instanceof HTMLButtonElement ? toggle : null;
}

''',
    '''function rakitDesktopNavigationToggle() {
  const toggle = document.querySelector("[data-rakit-desktop-navigation-toggle]");
  return toggle instanceof HTMLButtonElement ? toggle : null;
}

function rakitDesktopNavigationScrollContainer() {
  const navigation = document.querySelector("[data-rakit-desktop-navigation-scroll]");
  return navigation instanceof HTMLElement ? navigation : null;
}

function rakitSidebarScrollStorageKey(navigation) {
  const scope = navigation.dataset.rakitNavigationScrollKey || "/";
  return `${RAKIT_SIDEBAR_SCROLL_KEY_PREFIX}:${scope}`;
}

function rakitStoreDesktopNavigationScroll() {
  const navigation = rakitDesktopNavigationScrollContainer();
  if (!navigation) return;
  try {
    sessionStorage.setItem(
      rakitSidebarScrollStorageKey(navigation),
      String(navigation.scrollTop),
    );
  } catch {
    // Presentation persistence is optional; navigation remains usable without storage.
  }
}

function rakitRestoreDesktopNavigationScroll() {
  const navigation = rakitDesktopNavigationScrollContainer();
  if (!navigation) return;

  let stored = null;
  try {
    stored = sessionStorage.getItem(rakitSidebarScrollStorageKey(navigation));
  } catch {
    return;
  }
  if (stored === null) return;

  const offset = Number(stored);
  if (!Number.isFinite(offset) || offset < 0) return;
  const maximum = Math.max(0, navigation.scrollHeight - navigation.clientHeight);
  navigation.scrollTop = Math.min(offset, maximum);
}

''',
)

replace_exact(
    "packages/rakit-web/src/rakit_web/static/rakit-shell.js",
    '''document.addEventListener("DOMContentLoaded", () => {
  rakitApplyDesktopNavigationCollapsed(rakitStoredSidebarCollapsed());

  const navigation = rakitMobileNavigation();
  if (!navigation) return;
  navigation.addEventListener("close", rakitResetMobileNavigation);
});

RAKIT_DESKTOP_NAVIGATION.addEventListener("change", (event) => {
''',
    '''document.addEventListener("DOMContentLoaded", () => {
  rakitApplyDesktopNavigationCollapsed(rakitStoredSidebarCollapsed());
  rakitRestoreDesktopNavigationScroll();

  const desktopScroll = rakitDesktopNavigationScrollContainer();
  if (desktopScroll) {
    desktopScroll.addEventListener("scroll", rakitStoreDesktopNavigationScroll, {
      passive: true,
    });
    requestAnimationFrame(rakitRestoreDesktopNavigationScroll);
  }

  const navigation = rakitMobileNavigation();
  if (navigation) navigation.addEventListener("close", rakitResetMobileNavigation);
});

window.addEventListener("pagehide", rakitStoreDesktopNavigationScroll);

RAKIT_DESKTOP_NAVIGATION.addEventListener("change", (event) => {
''',
)

replace_exact(
    "packages/rakit-web/src/rakit_web/assets/rakit.css",
    '''    position: fixed;
    inset: 0;
    margin: auto;
    max-height: calc(100vh - 2rem);
    overflow-y: auto;
''',
    '''    position: fixed;
    top: 50%;
    left: 50%;
    right: auto;
    bottom: auto;
    margin: 0;
    transform: translate(-50%, -50%);
    max-height: calc(100vh - 2rem);
    overflow-y: auto;
''',
)

print("Applied UI-06 final scroll/dialog polish source changes")
