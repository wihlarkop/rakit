from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one match in {path}, got {count}: {old[:120]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "packages/rakit-web/src/rakit_web/field_presentation.py",
    "from typing import ClassVar, Literal\n",
    "from typing import ClassVar, Literal, cast\n",
)
replace_once(
    "packages/rakit-web/src/rakit_web/field_presentation.py",
    '''    def resolve(self, presentation: Presentation) -> FieldRenderer:\n        for candidate in type(presentation).__mro__:\n            if candidate in self._renderers:\n                return self._renderers[candidate]\n        raise KeyError(f"No renderer registered for {type(presentation).__name__}")\n''',
    '''    def resolve(self, presentation: Presentation) -> FieldRenderer:\n        for candidate in type(presentation).__mro__:\n            candidate_type = cast(type[Presentation], candidate)\n            renderer = self._renderers.get(candidate_type)\n            if renderer is not None:\n                return renderer\n        raise KeyError(f"No renderer registered for {type(presentation).__name__}")\n''',
)

replace_once(
    "packages/rakit-web/src/rakit_web/form_routes.py",
    "from dataclasses import dataclass, field\n",
    "from dataclasses import dataclass, field\nfrom datetime import date, datetime, time\n",
)
replace_once(
    "packages/rakit-web/src/rakit_web/form_routes.py",
    '''        raw_value = (submitted or {}).get(schema_field.field_id, "")\n        if not isinstance(raw_value, str) and hasattr(raw_value, "isoformat"):\n            raw_value = raw_value.isoformat(timespec="minutes") if schema_field.python_type.__name__ == "datetime" else raw_value.isoformat()\n''',
    '''        raw_value = (submitted or {}).get(schema_field.field_id, "")\n        if isinstance(raw_value, datetime):\n            raw_value = raw_value.isoformat(timespec="minutes")\n        elif isinstance(raw_value, date | time):\n            raw_value = raw_value.isoformat()\n''',
)

replace_once(
    "packages/rakit-web/src/rakit_web/relationship_routes.py",
    '''        if isinstance(resolved, Autocomplete) and resolved.search_fields:\n            if not set(resolved.search_fields).issubset(self.target_search_fields):\n                raise ValueError("Autocomplete search_fields exceed relationship search policy")\n''',
    '''        if (\n            isinstance(resolved, Autocomplete)\n            and resolved.search_fields\n            and not set(resolved.search_fields).issubset(self.target_search_fields)\n        ):\n            raise ValueError("Autocomplete search_fields exceed relationship search policy")\n''',
)
replace_once(
    "packages/rakit-web/src/rakit_web/relationship_routes.py",
    '''    result = await editor.target_service.list(\n        ResourceQuery.from_params(\n            page=max(1, page),\n            per_page=editor.effective_candidate_page_size,\n            allowed_sort_fields=(),\n            identity_fields=source.identity_fields,\n            search=query if editor.target_search_fields else None,\n        )\n    )\n    return RelationshipCandidatePage(\n''',
    '''    result = await editor.target_service.list(\n        ResourceQuery.from_params(\n            page=max(1, page),\n            per_page=editor.effective_candidate_page_size,\n            allowed_sort_fields=(),\n            identity_fields=source.identity_fields,\n            search=query if editor.target_search_fields else None,\n        )\n    )\n    if not isinstance(result, PageResult):\n        raise RakitError(\n            code=ErrorCode.CONFIG_INVALID,\n            message="Relationship candidate lookup requires page-result semantics.",\n            status_code=500,\n        )\n    return RelationshipCandidatePage(\n''',
)

# Keep the missing-scale contract without intentionally making a statically invalid call.
replace_once(
    "packages/rakit-web/tests/test_field_presentation.py",
    '''    with pytest.raises(TypeError):\n        Percentage()  # type: ignore[call-arg]\n''',
    '''    assert inspect.signature(Percentage).parameters["scale"].default is inspect.Parameter.empty\n''',
)
replace_once(
    "packages/rakit-web/tests/test_field_presentation.py",
    '''    def renderer(\n        presentation: Presentation, context: dict[str, object]\n    ) -> dict[str, object]:\n''',
    '''    def renderer(\n        presentation: Presentation, context: Mapping[str, object]\n    ) -> Mapping[str, object]:\n''',
)
replace_once(
    "packages/rakit-web/tests/test_field_presentation.py",
    "import inspect\n",
    "import inspect\nfrom collections.abc import Mapping\nfrom datetime import date, datetime\n",
)
replace_once(
    "packages/rakit-web/tests/test_field_presentation.py",
    '''        inferred_presentation(FieldDefinition(field_id="on", python_type=__import__("datetime").date)),\n''',
    '''        inferred_presentation(FieldDefinition(field_id="on", python_type=date)),\n''',
)
replace_once(
    "packages/rakit-web/tests/test_field_presentation.py",
    '''            FieldDefinition(field_id="at", python_type=__import__("datetime").datetime)\n''',
    '''            FieldDefinition(field_id="at", python_type=datetime)\n''',
)
