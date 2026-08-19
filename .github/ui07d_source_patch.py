from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one match in {path}, got {count}: {old[:100]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# Central default presentation renderer/registry.
replace_once(
    "packages/rakit-web/src/rakit_web/field_presentation.py",
    "    @property\n    def renderers(self) -> Mapping[type[Presentation], FieldRenderer]:\n        return MappingProxyType(self._renderers)\n\n\ndef enum_choices",
    "    @property\n    def renderers(self) -> Mapping[type[Presentation], FieldRenderer]:\n        return MappingProxyType(self._renderers)\n\n\ndef _default_renderer(\n    presentation: Presentation, context: Mapping[str, object]\n) -> Mapping[str, object]:\n    return {**context, \"presentation\": presentation, \"presentation_key\": presentation.key}\n\n\nDEFAULT_PRESENTATION_REGISTRY = PresentationRegistry()\nDEFAULT_PRESENTATION_REGISTRY.register(Presentation, _default_renderer)\n\n\ndef render_presentation(\n    presentation: Presentation,\n    context: Mapping[str, object],\n    *,\n    registry: PresentationRegistry = DEFAULT_PRESENTATION_REGISTRY,\n) -> Mapping[str, object]:\n    return registry.resolve(presentation)(presentation, context)\n\n\ndef enum_choices",
)
replace_once(
    "packages/rakit-web/src/rakit_web/field_presentation.py",
    '    "DateTimePicker",\n    "FieldPresentation",',
    '    "DateTimePicker",\n    "DEFAULT_PRESENTATION_REGISTRY",\n    "FieldPresentation",',
)
replace_once(
    "packages/rakit-web/src/rakit_web/field_presentation.py",
    '    "resolve_field_presentation",\n    "resolve_relationship_presentation",',
    '    "render_presentation",\n    "resolve_field_presentation",\n    "resolve_relationship_presentation",',
)

# Public dashboard write registration binds ResourceWebPresentation overrides.
replace_once(
    "packages/rakit-web/src/rakit_web/dashboard_admin.py",
    "from contextlib import asynccontextmanager\n",
    "from contextlib import asynccontextmanager\nfrom dataclasses import replace\n",
)
replace_once(
    "packages/rakit-web/src/rakit_web/dashboard_admin.py",
    "from .dashboard_routes import DashboardBinding, build_dashboard_routes, widget_path\n",
    "from .dashboard_routes import DashboardBinding, build_dashboard_routes, widget_path\nfrom .field_presentation import resolve_relationship_presentation\nfrom .form_routes import WriteResourceBinding\n",
)
replace_once(
    "packages/rakit-web/src/rakit_web/dashboard_admin.py",
    "from .resource_presentation import ResourceWebPresentation, bind_resource_web_presentation\n",
    "from .resource_presentation import (\n    ResourceWebPresentation,\n    bind_resource_web_presentation,\n    resource_web_presentation,\n)\n",
)
replace_once(
    "packages/rakit-web/src/rakit_web/dashboard_admin.py",
    "    def register_page(\n",
    '''    def register_write_resource(self, resource_id: str, binding: WriteResourceBinding) -> None:\n        definition = self._resource_definitions.get(resource_id)\n        if definition is None:\n            super().register_write_resource(resource_id, binding)\n            return\n        web = resource_web_presentation(definition)\n        known_fields = {field.field_id for field in binding.form_schema.fields}\n        unknown_fields = sorted(set(web.fields).difference(known_fields))\n        relationship_form = binding.relationship_form\n        known_relationships = (\n            {editor.relationship_id for editor in relationship_form.editors}\n            if relationship_form is not None\n            else set()\n        )\n        unknown_relationships = sorted(set(web.relationships).difference(known_relationships))\n        if unknown_fields or unknown_relationships:\n            raise RakitError(\n                code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,\n                message=\"Invalid resource Web presentation declaration\",\n                status_code=500,\n                details={\n                    \"resource_id\": resource_id,\n                    \"reason\": \"unknown_web_widget_presentation\",\n                    \"field_ids\": unknown_fields,\n                    \"relationship_ids\": unknown_relationships,\n                },\n            )\n        if relationship_form is not None:\n            try:\n                relationship_form = replace(\n                    relationship_form,\n                    editors=tuple(\n                        replace(\n                            editor,\n                            presentation=resolve_relationship_presentation(\n                                editor.relationship.definition.presentation,\n                                web.relationships.get(editor.relationship_id),\n                            ),\n                        )\n                        for editor in relationship_form.editors\n                    ),\n                )\n            except (TypeError, ValueError):\n                raise RakitError(\n                    code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,\n                    message=\"Invalid resource Web presentation declaration\",\n                    status_code=500,\n                    details={\n                        \"resource_id\": resource_id,\n                        \"reason\": \"invalid_relationship_widget_presentation\",\n                    },\n                ) from None\n        configured = replace(\n            binding,\n            field_presentations=web.fields,\n            relationship_form=relationship_form,\n        )\n        super().register_write_resource(resource_id, configured)\n\n    def register_page(\n''',
)

# Scalar form resolution, safe boolean transport, and staged relationship picker return.
replace_once(
    "packages/rakit-web/src/rakit_web/form_routes.py",
    "from .file_presentation import file_field_presentation\n",
    "from .field_presentation import (\n    Presentation,\n    render_presentation,\n    resolve_field_presentation,\n)\nfrom .file_presentation import file_field_presentation\n",
)
replace_once(
    "packages/rakit-web/src/rakit_web/form_routes.py",
    "    relationship_editor_authorizer: RelationshipEditorAuthorizer | None = None\n    codec: IdentityCodec = field(default_factory=IdentityCodec)\n",
    "    relationship_editor_authorizer: RelationshipEditorAuthorizer | None = None\n    field_presentations: Mapping[str, Presentation] = field(default_factory=dict)\n    codec: IdentityCodec = field(default_factory=IdentityCodec)\n",
)
replace_once(
    "packages/rakit-web/src/rakit_web/form_routes.py",
    "    def __post_init__(self) -> None:\n        editors = (\n",
    "    def __post_init__(self) -> None:\n        field_ids = {field.field_id for field in self.form_schema.fields}\n        unknown_presentations = set(self.field_presentations).difference(field_ids)\n        if unknown_presentations:\n            raise ValueError(\n                \"Field presentation references unknown fields: \"\n                + \", \".join(sorted(unknown_presentations))\n            )\n        if any(not isinstance(value, Presentation) for value in self.field_presentations.values()):\n            raise TypeError(\"Field presentation overrides must contain Presentation values\")\n        editors = (\n",
)
replace_once(
    "packages/rakit-web/src/rakit_web/form_routes.py",
    "    items = form.multi_items()\n    names = [name for name, _ in items]\n    if len(names) != len(set(names)):\n        return None\n",
    '''    items = form.multi_items()\n    names = [name for name, _ in items]\n    duplicate_names = {name for name in names if names.count(name) > 1}\n    if duplicate_names:\n        boolean_ids = {\n            field.field_id for field in binding.form_schema.fields if field.python_type is bool\n        }\n        for duplicate in duplicate_names:\n            if duplicate not in boolean_ids:\n                return None\n            values_for_name = [value for name, value in items if name == duplicate]\n            if values_for_name != [\"false\", \"true\"]:\n                return None\n''',
)
replace_once(
    "packages/rakit-web/src/rakit_web/form_routes.py",
    "        controls[schema_field.field_id] = {\n            \"id\": _field_dom_id(binding, schema_field.field_id),\n",
    '''        presentation = resolve_field_presentation(\n            schema_field, binding.field_presentations.get(schema_field.field_id)\n        )\n        raw_value = (submitted or {}).get(schema_field.field_id, \"\")\n        if not isinstance(raw_value, str) and hasattr(raw_value, \"isoformat\"):\n            raw_value = raw_value.isoformat(timespec=\"minutes\") if schema_field.python_type.__name__ == \"datetime\" else raw_value.isoformat()\n        base_control = {\n            \"id\": _field_dom_id(binding, schema_field.field_id),\n''',
)
replace_once(
    "packages/rakit-web/src/rakit_web/form_routes.py",
    "            \"value\": (submitted or {}).get(schema_field.field_id, \"\"),\n            \"issues\": issue_map.get(schema_field.field_id, ()),\n",
    "            \"value\": raw_value,\n            \"checked\": raw_value is True or str(raw_value).casefold() in {\"true\", \"1\", \"on\", \"yes\"},\n            \"issues\": issue_map.get(schema_field.field_id, ()),\n",
)
replace_once(
    "packages/rakit-web/src/rakit_web/form_routes.py",
    "            \"required\": schema_field.required\n            and not (file_view is not None and file_view.current is not None),\n        }\n",
    '''            \"required\": schema_field.required\n            and not (file_view is not None and file_view.current is not None),\n            \"custom_template\": None,\n        }\n        controls[schema_field.field_id] = dict(\n            render_presentation(presentation, base_control)\n        )\n''',
)
replace_once(
    "packages/rakit-web/src/rakit_web/form_routes.py",
    '''        return await _form_response(\n            binding,\n            request,\n            title=f"Edit {binding.label}",\n            action_path=f"{binding.path}/{request.path_params['identity']}/edit",\n            submitted=_record_values(binding, record),\n''',
    '''        submitted = _record_values(binding, record)\n        staged_relationship = {\n            name: value\n            for name, value in request.query_params.multi_items()\n            if name.startswith("__rakit_rel__")\n        }\n        if staged_relationship:\n            if len(staged_relationship) != len(\n                [name for name, _ in request.query_params.multi_items() if name.startswith("__rakit_rel__")]\n            ):\n                return _error(400, "Invalid relationship selection")\n            try:\n                scalar, relationship = split_relationship_submission(\n                    binding.relationship_form, staged_relationship\n                )\n            except ValueError:\n                return _error(400, "Invalid relationship selection")\n            if scalar:\n                return _error(400, "Invalid relationship selection")\n            submitted.update(relationship)\n        return await _form_response(\n            binding,\n            request,\n            title=f"Edit {binding.label}",\n            action_path=f"{binding.path}/{request.path_params['identity']}/edit",\n            submitted=submitted,\n''',
)

# Relationship presentation and candidate pagination.
replace_once(
    "packages/rakit-web/src/rakit_web/relationship_routes.py",
    "from ._paths import mounted_path\n",
    "from ._paths import mounted_path\nfrom .field_presentation import (\n    Autocomplete,\n    MultiAutocomplete,\n    Presentation,\n    SearchableSelect,\n    Select,\n    resolve_relationship_presentation,\n)\n",
)
replace_once(
    "packages/rakit-web/src/rakit_web/relationship_routes.py",
    "    target_search_fields: tuple[str, ...] = ()\n    candidate_page_size: int = 25\n",
    "    target_search_fields: tuple[str, ...] = ()\n    presentation: Presentation | None = None\n    candidate_page_size: int = 25\n",
)
replace_once(
    "packages/rakit-web/src/rakit_web/relationship_routes.py",
    "        definition = self.relationship.definition\n        if self.candidate_page_size < 1 or self.candidate_page_size > 200:\n",
    '''        definition = self.relationship.definition\n        resolved = resolve_relationship_presentation(definition.presentation, self.presentation)\n        object.__setattr__(self, "presentation", resolved)\n        if isinstance(resolved, MultiAutocomplete):\n            if definition.cardinality is not RelationshipCardinality.TO_MANY:\n                raise ValueError("MultiAutocomplete requires a to-many relationship")\n        elif isinstance(resolved, Autocomplete | SearchableSelect | Select):\n            if definition.cardinality is not RelationshipCardinality.TO_ONE:\n                raise ValueError("Single-choice presentation requires a to-one relationship")\n        elif resolved is not None:\n            raise ValueError("Unsupported relationship presentation")\n        if isinstance(resolved, Autocomplete) and resolved.search_fields:\n            if not set(resolved.search_fields).issubset(self.target_search_fields):\n                raise ValueError("Autocomplete search_fields exceed relationship search policy")\n        if self.candidate_page_size < 1 or self.candidate_page_size > 200:\n''',
)
replace_once(
    "packages/rakit-web/src/rakit_web/relationship_routes.py",
    "    @property\n    def relationship_id(self) -> str:\n",
    '''    @property\n    def effective_candidate_page_size(self) -> int:\n        if isinstance(self.presentation, Autocomplete):\n            return min(self.presentation.page_size, 200)\n        return self.candidate_page_size\n\n    @property\n    def relationship_id(self) -> str:\n''',
)
replace_once(
    "packages/rakit-web/src/rakit_web/relationship_routes.py",
    '''async def _candidate_options(\n    editor: RelationshipEditorBinding, *, query: str | None, page: int = 1\n) -> tuple[RelationshipCandidate, ...]:\n    source = editor.target_service.data_source\n    identity_for = getattr(source, "identity_for", None)\n    if not callable(identity_for):\n        raise RakitError(\n            code=ErrorCode.CONFIG_INVALID,\n            message="Relationship target data source cannot provide canonical identities.",\n            status_code=500,\n        )\n    result = await editor.target_service.list(\n        ResourceQuery.from_params(\n            page=page,\n            per_page=editor.candidate_page_size,\n            allowed_sort_fields=(),\n            identity_fields=source.identity_fields,\n            search=query if editor.target_search_fields else None,\n        )\n    )\n    return tuple(\n        RelationshipCandidate(\n            identity=identity_for(record),\n            label=resolve_record_label(editor.relationship.definition, record),\n        )\n        for record in result.items\n    )\n''',
    '''@dataclass(frozen=True)\nclass RelationshipCandidatePage:\n    items: tuple[RelationshipCandidate, ...]\n    page: int\n    has_previous: bool\n    has_next: bool\n    total_count: int | None = None\n\n\nasync def _candidate_options(\n    editor: RelationshipEditorBinding, *, query: str | None, page: int = 1\n) -> RelationshipCandidatePage:\n    source = editor.target_service.data_source\n    identity_for = getattr(source, "identity_for", None)\n    if not callable(identity_for):\n        raise RakitError(\n            code=ErrorCode.CONFIG_INVALID,\n            message="Relationship target data source cannot provide canonical identities.",\n            status_code=500,\n        )\n    result = await editor.target_service.list(\n        ResourceQuery.from_params(\n            page=max(1, page),\n            per_page=editor.effective_candidate_page_size,\n            allowed_sort_fields=(),\n            identity_fields=source.identity_fields,\n            search=query if editor.target_search_fields else None,\n        )\n    )\n    return RelationshipCandidatePage(\n        items=tuple(\n            RelationshipCandidate(\n                identity=identity_for(record),\n                label=resolve_record_label(editor.relationship.definition, record),\n            )\n            for record in result.items\n        ),\n        page=result.page,\n        has_previous=result.has_previous,\n        has_next=result.has_next,\n        total_count=result.total_count,\n    )\n''',
)
replace_once(
    "packages/rakit-web/src/rakit_web/relationship_routes.py",
    '''    options_by_identity = {\n        IdentityCodec().encode(option.identity): option\n        for option in await _candidate_options(editor, query=None, page=page)\n    }\n''',
    '''    candidate_page = await _candidate_options(editor, query=None, page=page)\n    options_by_identity = {\n        IdentityCodec().encode(option.identity): option for option in candidate_page.items\n    }\n''',
)
replace_once(
    "packages/rakit-web/src/rakit_web/relationship_routes.py",
    '        "presentation_mode": presentation_mode,\n',
    '''        "presentation_mode": presentation_mode,\n        "presentation": editor.presentation,\n        "presentation_key": editor.presentation.key if editor.presentation is not None else None,\n        "advanced_presentation": editor.presentation is not None,\n        "autocomplete_min_query_length": (\n            editor.presentation.min_query_length\n            if isinstance(editor.presentation, Autocomplete)\n            else 0\n        ),\n''',
)
replace_once(
    "packages/rakit-web/src/rakit_web/relationship_routes.py",
    '        "options_path": f"{page_path}/options" if page_path is not None else None,\n',
    '        "options_path": f"{page_path}/options" if page_path is not None else None,\n        "picker_path": f"{page_path}/picker" if page_path is not None else None,\n',
)
replace_once(
    "packages/rakit-web/src/rakit_web/relationship_routes.py",
    '''            options = await _candidate_options(editor, query=request.query_params.get("q"))\n            selected = {\n''',
    '''            try:\n                candidate_page = await _candidate_options(\n                    editor,\n                    query=request.query_params.get("q"),\n                    page=max(1, int(request.query_params.get("page", "1"))),\n                )\n            except ValueError:\n                return PlainTextResponse("Invalid candidate page", status_code=400)\n            selected = {\n''',
)
replace_once(
    "packages/rakit-web/src/rakit_web/relationship_routes.py",
    '                    "options": options,\n                    "codec": relationship_binding.codec,\n',
    '                    "options": candidate_page.items,\n                    "codec": relationship_binding.codec,\n',
)
replace_once(
    "packages/rakit-web/src/rakit_web/relationship_routes.py",
    '                    "options_id": f"rakit-relationship-{editor.relationship_id}-options",\n',
    '                    "options_id": f"rakit-relationship-{editor.relationship_id}-options",\n                    "has_next": candidate_page.has_next,\n                    "next_page": candidate_page.page + 1 if candidate_page.has_next else None,\n',
)
replace_once(
    "packages/rakit-web/src/rakit_web/relationship_routes.py",
    "        async def page(request: Request, editor: RelationshipEditorBinding = editor) -> Response:\n",
    '''        async def picker(request: Request, editor: RelationshipEditorBinding = editor) -> Response:\n            identity = binding.codec.decode(request.path_params["identity"])\n            if not await _authorize_editor(binding, request, editor, identity):\n                return PlainTextResponse("Forbidden", status_code=403)\n            if (\n                not callable(getattr(binding.mutation_service, "get", None))\n                or await binding.mutation_service.get(identity) is None\n            ):\n                return PlainTextResponse("Resource was not found", status_code=404)\n            try:\n                page_number = max(1, int(request.query_params.get("page", "1")))\n            except ValueError:\n                return PlainTextResponse("Invalid candidate page", status_code=400)\n            query = request.query_params.get("q", "")\n            candidate_page = await _candidate_options(\n                editor, query=query or None, page=page_number\n            )\n            encoded_parent = binding.codec.encode(identity)\n            return_path = mounted_path(\n                request, f"{binding.path}/{encoded_parent}/edit"\n            )\n            picker_path = mounted_path(\n                request,\n                editor.relationship.route_path.replace("{identity}", encoded_parent) + "/picker",\n            )\n            return binding.templates.TemplateResponse(\n                request,\n                "relationships/picker.html",\n                {\n                    "relationship": editor.relationship.definition,\n                    "options": candidate_page.items,\n                    "codec": relationship_binding.codec,\n                    "prefix": relationship_prefix(editor.relationship_id),\n                    "multiple": isinstance(editor.presentation, MultiAutocomplete),\n                    "query": query,\n                    "page": candidate_page.page,\n                    "has_next": candidate_page.has_next,\n                    "return_path": return_path,\n                    "picker_path": picker_path,\n                },\n                headers={"Cache-Control": "no-store"},\n            )\n\n        async def page(request: Request, editor: RelationshipEditorBinding = editor) -> Response:\n''',
)
replace_once(
    "packages/rakit-web/src/rakit_web/relationship_routes.py",
    '''                Route(\n                    f"{route_path}/page/{{page:int}}",\n''',
    '''                Route(\n                    f"{route_path}/picker",\n                    picker,\n                    methods=["GET"],\n                    name=f"relationship:{editor.relationship.source_resource_id}:{editor.relationship_id}:picker",\n                ),\n                Route(\n                    f"{route_path}/page/{{page:int}}",\n''',
)
