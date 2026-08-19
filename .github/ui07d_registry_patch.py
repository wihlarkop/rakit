from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one match in {path}, got {count}: {old[:120]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# Give every Admin/write binding an isolated default registry while keeping the module default available.
replace_once(
    "packages/rakit-web/src/rakit_web/field_presentation.py",
    '''DEFAULT_PRESENTATION_REGISTRY = PresentationRegistry()\nDEFAULT_PRESENTATION_REGISTRY.register(Presentation, _default_renderer)\n\n\ndef render_presentation(\n''',
    '''def default_presentation_registry() -> PresentationRegistry:\n    registry = PresentationRegistry()\n    registry.register(Presentation, _default_renderer)\n    return registry\n\n\nDEFAULT_PRESENTATION_REGISTRY = default_presentation_registry()\n\n\ndef render_presentation(\n''',
)
replace_once(
    "packages/rakit-web/src/rakit_web/field_presentation.py",
    '    "inferred_presentation",\n',
    '    "default_presentation_registry",\n    "inferred_presentation",\n',
)

# Freeze low-level override mappings and render through the binding-owned registry.
replace_once(
    "packages/rakit-web/src/rakit_web/form_routes.py",
    "from dataclasses import dataclass, field\n",
    "from dataclasses import dataclass, field\nfrom types import MappingProxyType\n",
)
replace_once(
    "packages/rakit-web/src/rakit_web/form_routes.py",
    '''from .field_presentation import (\n    Presentation,\n    render_presentation,\n    resolve_field_presentation,\n)\n''',
    '''from .field_presentation import (\n    Presentation,\n    PresentationRegistry,\n    default_presentation_registry,\n    render_presentation,\n    resolve_field_presentation,\n)\n''',
)
replace_once(
    "packages/rakit-web/src/rakit_web/form_routes.py",
    '''    relationship_editor_authorizer: RelationshipEditorAuthorizer | None = None\n    field_presentations: Mapping[str, Presentation] = field(default_factory=dict)\n    codec: IdentityCodec = field(default_factory=IdentityCodec)\n''',
    '''    relationship_editor_authorizer: RelationshipEditorAuthorizer | None = None\n    field_presentations: Mapping[str, Presentation] = field(default_factory=dict)\n    presentation_registry: PresentationRegistry = field(\n        default_factory=default_presentation_registry\n    )\n    codec: IdentityCodec = field(default_factory=IdentityCodec)\n''',
)
replace_once(
    "packages/rakit-web/src/rakit_web/form_routes.py",
    '''        if any(not isinstance(value, Presentation) for value in self.field_presentations.values()):\n            raise TypeError("Field presentation overrides must contain Presentation values")\n        editors = (\n''',
    '''        if any(not isinstance(value, Presentation) for value in self.field_presentations.values()):\n            raise TypeError("Field presentation overrides must contain Presentation values")\n        object.__setattr__(\n            self, "field_presentations", MappingProxyType(dict(self.field_presentations))\n        )\n        if not isinstance(self.presentation_registry, PresentationRegistry):\n            raise TypeError("presentation_registry must be a PresentationRegistry")\n        editors = (\n''',
)
replace_once(
    "packages/rakit-web/src/rakit_web/form_routes.py",
    '''        controls[schema_field.field_id] = dict(\n            render_presentation(presentation, base_control)\n        )\n''',
    '''        controls[schema_field.field_id] = dict(\n            render_presentation(\n                presentation, base_control, registry=binding.presentation_registry\n            )\n        )\n''',
)

# Public Admin-owned registry. It is lazy so inherited initialization remains untouched.
replace_once(
    "packages/rakit-web/src/rakit_web/dashboard_admin.py",
    "from .field_presentation import resolve_relationship_presentation\n",
    '''from .field_presentation import (\n    PresentationRegistry,\n    default_presentation_registry,\n    resolve_relationship_presentation,\n)\n''',
)
replace_once(
    "packages/rakit-web/src/rakit_web/dashboard_admin.py",
    '''class Admin(_EndpointAdmin):\n    """Public Admin facade with an automatic, permission-aware dashboard."""\n\n    def register(\n''',
    '''class Admin(_EndpointAdmin):\n    """Public Admin facade with an automatic, permission-aware dashboard."""\n\n    @property\n    def presentations(self) -> PresentationRegistry:\n        registry = getattr(self, "_rakit_presentation_registry", None)\n        if registry is None:\n            registry = default_presentation_registry()\n            self._rakit_presentation_registry = registry\n        return registry\n\n    def register(\n''',
)
replace_once(
    "packages/rakit-web/src/rakit_web/dashboard_admin.py",
    '''        return replace(\n            binding,\n            field_presentations=web.fields,\n            relationship_form=relationship_form,\n        )\n''',
    '''        return replace(\n            binding,\n            field_presentations=web.fields,\n            presentation_registry=self.presentations,\n            relationship_form=relationship_form,\n        )\n''',
)

# Document the now-concrete Admin extension surface.
replace_once(
    "docs/guides/presentations.md",
    '''`PresentationRegistry` is the Web rendering extension boundary. A custom presentation is an immutable\npresentation object with a registered renderer. The renderer receives already-resolved form/view state\nand returns rendering data; it must not fetch directly from a database or execute mutations.\n\nFull distributable presentation-plugin packaging is intentionally deferred. UI-07D establishes the\ntyped registry boundary without turning custom widgets into a parallel application framework.\n''',
    '''`PresentationRegistry` is the Web rendering extension boundary. Each `Admin` owns an isolated registry\nat `admin.presentations`, so custom rendering does not mutate process-global widget behavior:\n\n```python\nadmin.presentations.register(RatingStars, renderer=render_rating_stars)\n```\n\nA custom presentation is an immutable `Presentation` subclass. The renderer receives already-resolved\nform/view state and may return a `custom_template` plus safe view-model values consumed by that\ntemplate. It must not fetch directly from a database, authorize a request, or execute mutations.\n\nFull distributable presentation-plugin packaging is intentionally deferred. UI-07D establishes the\ntyped registry boundary without turning custom widgets into a parallel application framework.\n''',
)
