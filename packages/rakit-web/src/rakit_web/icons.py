"""Small, server-rendered icon primitive for the built-in Rakit UI.

Rakit vendors only the geometry for a deliberately small Lucide subset.  Icons
are rendered on the server so the admin shell does not need a browser icon
runtime or CDN access, and names are allowlisted so templates cannot inject
arbitrary SVG markup.
"""

from html import escape

from markupsafe import Markup

_ICON_BODY: dict[str, str] = {
    "check": '<path d="M20 6 9 17l-5-5" />',
    "chevron-down": '<path d="m6 9 6 6 6-6" />',
    "chevron-right": '<path d="m9 18 6-6-6-6" />',
    "database": (
        '<ellipse cx="12" cy="5" rx="9" ry="3" />'
        '<path d="M3 5V19A9 3 0 0 0 21 19V5" />'
        '<path d="M3 12A9 3 0 0 0 21 12" />'
    ),
    "file-text": (
        '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 '
        '1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z" />'
        '<path d="M14 2v5a1 1 0 0 0 1 1h5" />'
        '<path d="M10 9H8" /><path d="M16 13H8" /><path d="M16 17H8" />'
    ),
    "layout-dashboard": (
        '<rect width="7" height="9" x="3" y="3" rx="1" />'
        '<rect width="7" height="5" x="14" y="3" rx="1" />'
        '<rect width="7" height="9" x="14" y="12" rx="1" />'
        '<rect width="7" height="5" x="3" y="16" rx="1" />'
    ),
    "menu": '<path d="M4 5h16" /><path d="M4 12h16" /><path d="M4 19h16" />',
    "monitor": (
        '<rect width="20" height="14" x="2" y="3" rx="2" />'
        '<line x1="8" x2="16" y1="21" y2="21" />'
        '<line x1="12" x2="12" y1="17" y2="21" />'
    ),
    "moon": (
        '<path d="M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803'
        'a6 6 0 0 0 8.268 8.268c.344-.215.825-.004.803.401" />'
    ),
    "panel-left-close": (
        '<rect width="18" height="18" x="3" y="3" rx="2" />'
        '<path d="M9 3v18" />'
        '<path d="m16 15-3-3 3-3" />'
    ),
    "panel-left-open": (
        '<rect width="18" height="18" x="3" y="3" rx="2" />'
        '<path d="M9 3v18" />'
        '<path d="m14 9 3 3-3 3" />'
    ),
    "sun": (
        '<circle cx="12" cy="12" r="4" />'
        '<path d="M12 2v2" /><path d="M12 20v2" />'
        '<path d="m4.93 4.93 1.41 1.41" />'
        '<path d="m17.66 17.66 1.41 1.41" />'
        '<path d="M2 12h2" /><path d="M20 12h2" />'
        '<path d="m6.34 17.66-1.41 1.41" />'
        '<path d="m19.07 4.93-1.41 1.41" />'
    ),
    "x": '<path d="M18 6 6 18" /><path d="m6 6 12 12" />',
}


def render_icon(
    name: str,
    *,
    class_name: str = "size-4",
    label: str | None = None,
) -> Markup:
    """Render one allowlisted Lucide icon as safe inline SVG markup."""

    try:
        body = _ICON_BODY[name]
    except KeyError:
        raise ValueError(f"Unknown Rakit icon: {name!r}") from None

    safe_class = escape(class_name, quote=True)
    if label is None:
        accessibility = 'aria-hidden="true" focusable="false"'
    else:
        safe_label = escape(label, quote=True)
        accessibility = f'role="img" aria-label="{safe_label}" focusable="false"'

    return Markup(
        "<svg "
        f"{accessibility} "
        'xmlns="http://www.w3.org/2000/svg" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        f'class="{safe_class}">{body}</svg>'
    )


__all__ = ["render_icon"]
