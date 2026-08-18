from pathlib import Path


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label} not found")
    return text.replace(old, new, 1)


# Resource presentation metadata.
resource = Path("packages/rakit-web/src/rakit_web/resource_routes.py")
text = resource.read_text(encoding="utf-8")
anchor = '''@dataclass(frozen=True)
class ResourceBinding:
    """Everything a request handler needs to serve one resource's pages."""

    definition: ResourceDefinition
    service: ResourceService
    templates: Jinja2Templates
    codec: IdentityCodec = field(default_factory=IdentityCodec)
'''
replacement = '''@dataclass(frozen=True)
class ResourceCrudPaths:
    """Registered built-in CRUD routes available to resource presentation."""

    create_path: str
    update_path: str | None = None
    delete_path: str | None = None


@dataclass(frozen=True)
class ResourceBinding:
    """Everything a request handler needs to serve one resource's pages."""

    definition: ResourceDefinition
    service: ResourceService
    templates: Jinja2Templates
    crud_paths: ResourceCrudPaths | None = None
    codec: IdentityCodec = field(default_factory=IdentityCodec)
'''
text = replace_once(text, anchor, replacement, label="ResourceBinding declaration")

anchor = '''            "resource_path": resource_path,
            "count_url": count_url,
'''
replacement = '''            "resource_path": resource_path,
            "create_url": (
                _mounted_path(request, binding.crud_paths.create_path)
                if binding.crud_paths is not None
                else ""
            ),
            "count_url": count_url,
'''
text = replace_once(text, anchor, replacement, label="list create URL context")

anchor = '''        record = await binding.service.detail(identity)
        fields = binding.detail_fields
        context = {
            "resource": binding.definition,
            "record": record,
            "fields": fields,
            "cells": {field_name: _field_value(record, field_name) for field_name in fields},
        }
'''
replacement = '''        record = await binding.service.detail(identity)
        fields = binding.detail_fields
        cells = {field_name: _field_value(record, field_name) for field_name in fields}
        encoded_identity = binding.codec.encode(identity)
        edit_url = ""
        delete_url = ""
        if binding.crud_paths is not None:
            if binding.crud_paths.update_path:
                edit_url = _mounted_path(
                    request,
                    binding.crud_paths.update_path.replace("{identity}", encoded_identity),
                )
            if binding.crud_paths.delete_path:
                delete_url = _mounted_path(
                    request,
                    binding.crud_paths.delete_path.replace("{identity}", encoded_identity),
                )
        context = {
            "resource": binding.definition,
            "record": record,
            "fields": fields,
            "cells": cells,
            "display_cells": {
                field_name: _display_value(value) for field_name, value in cells.items()
            },
            "edit_url": edit_url,
            "delete_url": delete_url,
        }
'''
text = replace_once(text, anchor, replacement, label="detail CRUD context")
resource.write_text(text, encoding="utf-8")


# Write route capability and safe navigation context.
forms = Path("packages/rakit-web/src/rakit_web/form_routes.py")
text = forms.read_text(encoding="utf-8")
anchor = '''    @property
    def delete_path(self) -> str:
        return f"{self.path}/{{identity}}/delete"


async def _parse_form(
'''
replacement = '''    @property
    def delete_path(self) -> str:
        return f"{self.path}/{{identity}}/delete"

    @property
    def has_record_write_routes(self) -> bool:
        service = self.mutation_service
        return all(
            callable(getattr(service, name, None))
            for name in ("get", "issue_update_token", "update", "issue_delete_token", "delete")
        )


async def _parse_form(
'''
text = replace_once(text, anchor, replacement, label="write route capability property")

anchor = '''def _write_routes_available(binding: WriteResourceBinding) -> bool:
    service = binding.mutation_service
    return all(
        callable(getattr(service, name, None))
        for name in ("get", "issue_update_token", "update", "issue_delete_token", "delete")
    )
'''
replacement = '''def _write_routes_available(binding: WriteResourceBinding) -> bool:
    return binding.has_record_write_routes
'''
text = replace_once(text, anchor, replacement, label="write route capability helper")

anchor = '''    return binding.templates.TemplateResponse(
        request,
        "forms/form.html",
        {
            "title": title,
            "label": binding.label,
'''
replacement = '''    cancel_path = binding.path
    if operation == "update" and action_path.endswith("/edit"):
        cancel_path = action_path.removesuffix("/edit")
    return binding.templates.TemplateResponse(
        request,
        "forms/form.html",
        {
            "title": title,
            "label": binding.label,
            "resource_url": mounted_path(request, binding.path),
            "cancel_url": mounted_path(request, cancel_path),
'''
text = replace_once(text, anchor, replacement, label="form navigation context")

anchor = '''            {
                "action_url": mounted_path(
                    request, f"{binding.path}/{request.path_params['identity']}/delete"
                ),
                "csrf_token": request.cookies.get(CSRF_COOKIE_NAME, ""),
'''
replacement = '''            {
                "label": binding.label,
                "cancel_url": mounted_path(request, binding.path),
                "action_url": mounted_path(
                    request, f"{binding.path}/{request.path_params['identity']}/delete"
                ),
                "csrf_token": request.cookies.get(CSRF_COOKIE_NAME, ""),
'''
text = replace_once(text, anchor, replacement, label="delete navigation context")
forms.write_text(text, encoding="utf-8")


# Admin composition: expose only routes that are actually built.
admin = Path("packages/rakit-web/src/rakit_web/admin.py")
text = admin.read_text(encoding="utf-8")
anchor = '''from .resource_routes import ResourceBinding, build_resource_routes, build_templates
'''
replacement = '''from .resource_routes import (
    ResourceBinding,
    ResourceCrudPaths,
    build_resource_routes,
    build_templates,
)
'''
text = replace_once(text, anchor, replacement, label="admin resource route imports")

anchor = '''        for resource_id, service in self._resource_services.items():
            binding = ResourceBinding(
                definition=self._resource_definitions[resource_id],
                service=service,
                templates=templates,
            )
'''
replacement = '''        for resource_id, service in self._resource_services.items():
            write_binding = self._write_resource_bindings.get(resource_id)
            crud_paths = None
            if write_binding is not None:
                crud_paths = ResourceCrudPaths(
                    create_path=write_binding.create_path,
                    update_path=(
                        write_binding.update_path if write_binding.has_record_write_routes else None
                    ),
                    delete_path=(
                        write_binding.delete_path if write_binding.has_record_write_routes else None
                    ),
                )
            binding = ResourceBinding(
                definition=self._resource_definitions[resource_id],
                service=service,
                templates=templates,
                crud_paths=crud_paths,
            )
'''
text = replace_once(text, anchor, replacement, label="admin CRUD path composition")
admin.write_text(text, encoding="utf-8")
