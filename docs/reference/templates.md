# Templates

Rakit's built-in web package ships framework-owned Jinja templates and content-addressed static
assets. `Admin(template_dirs=(...))` can add application template directories when an application
needs an explicit override/extension surface.

Built-in templates participate in Rakit's security/accessibility contracts: local assets under the
CSP, mount-aware URLs, server-rendered progressive enhancement, skip/focus semantics, theme-aware
styles, and safe form/query state.

Template compatibility is **provisional** in the alpha. Framework-owned context keys and blocks that
are explicitly documented are treated more carefully than arbitrary internal markup/class names.
Applications that copy an entire internal template instead of overriding a documented seam accept a
higher upgrade burden.

Custom application templates/widgets remain responsible for their own escaping, accessibility,
responsive behavior, and security-sensitive links/forms.
