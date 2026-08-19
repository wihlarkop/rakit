from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one replacement, found {count}: {old[:80]!r}")
    file.write_text(text.replace(old, new, 1))


# Admin composition: register the built-in route, preserve secured write bindings,
# expose CRUD presentation permissions, and build bulk routes even with zero custom actions.
admin = "packages/rakit-web/src/rakit_web/admin.py"
replace_once(
    admin,
    '''            (f"resource:{resource_id}:delete", ("GET",), binding.delete_path),
            (f"resource:{resource_id}:delete.submit", ("POST",), binding.delete_path),
            (
''',
    '''            (f"resource:{resource_id}:delete", ("GET",), binding.delete_path),
            (f"resource:{resource_id}:delete.submit", ("POST",), binding.delete_path),
            (
                f"resource:{resource_id}:bulk.delete",
                ("GET", "POST"),
                f"{binding.path}/_bulk/delete",
            ),
            (
''',
)
replace_once(
    admin,
    '''            binding = ResourceBinding(
                definition=self._resource_definitions[resource_id],
                service=service,
                templates=templates,
                crud_paths=crud_paths,
            )
''',
    '''            binding = ResourceBinding(
                definition=self._resource_definitions[resource_id],
                service=service,
                templates=templates,
                crud_paths=crud_paths,
                admin_id=self.config.admin_id,
                auth_enabled=self._auth_backend is not None and self._session_store is not None,
                superuser_bypass=self._superuser_bypass,
            )
''',
)
replace_once(
    admin,
    '''            for write_binding in self._write_resource_bindings.values():
                secured_binding = replace(
''',
    '''            secured_write_bindings: dict[str, WriteResourceBinding] = {}
            for write_binding in self._write_resource_bindings.values():
                secured_binding = replace(
''',
)
replace_once(
    admin,
    '''                )
                write_routes.extend(build_write_routes(secured_binding))
                if secured_binding.relationship_form is not None:
''',
    '''                )
                if secured_binding.resource_id is None:
                    raise RuntimeError("Secured write resource is missing its resource id")
                secured_write_bindings[secured_binding.resource_id] = secured_binding
                write_routes.extend(build_write_routes(secured_binding))
                if secured_binding.relationship_form is not None:
''',
)
replace_once(
    admin,
    '''            action_routes = []
            if self.compiled.action_routes:
                for action_binding in self._action_bindings(
                    templates=templates,
                    codec=IdentityCodec(),
                    verify_csrf=verify_write_csrf,
                    issue_submission_token=issue_submission_token,
                    verify_submission_token=verify_submission_token,
                    token_service=write_token_service,
                    operation_scope=operation_scope,
                    unit_of_work_factory=action_uow_factory,
                ):
                    action_routes.extend(build_action_routes(action_binding))
                assert self._operation_idempotency_store is not None
                action_routes.extend(
                    build_admin_bulk_action_routes(
                        compiled=self.compiled,
                        resource_services=self._resource_services,
                        concurrency_providers=self._concurrency_providers,
                        templates=templates,
                        verify_csrf=verify_write_csrf,
                        verify_submission_token=verify_submission_token,
                        issue_submission_token=issue_submission_token,
                        token_service=write_token_service,
                        idempotency_store=self._operation_idempotency_store,
                        admin_id=self.config.admin_id,
                        superuser_bypass=self._superuser_bypass,
                        deadline_seconds=self._mutation_deadline_seconds,
                        operation_scope=operation_scope,
                        unit_of_work_factory=action_uow_factory,
                        label=self.config.title,
                    )
                )
''',
    '''            action_routes = []
            if self.compiled.action_routes:
                for action_binding in self._action_bindings(
                    templates=templates,
                    codec=IdentityCodec(),
                    verify_csrf=verify_write_csrf,
                    issue_submission_token=issue_submission_token,
                    verify_submission_token=verify_submission_token,
                    token_service=write_token_service,
                    operation_scope=operation_scope,
                    unit_of_work_factory=action_uow_factory,
                ):
                    action_routes.extend(build_action_routes(action_binding))
            if secured_write_bindings or self.compiled.action_routes:
                action_routes.extend(
                    build_admin_bulk_action_routes(
                        compiled=self.compiled,
                        resource_services=self._resource_services,
                        write_resource_bindings=secured_write_bindings,
                        concurrency_providers=self._concurrency_providers,
                        templates=templates,
                        verify_csrf=verify_write_csrf,
                        verify_submission_token=verify_submission_token,
                        issue_submission_token=issue_submission_token,
                        token_service=write_token_service,
                        idempotency_store=self._operation_idempotency_store,
                        admin_id=self.config.admin_id,
                        superuser_bypass=self._superuser_bypass,
                        deadline_seconds=self._mutation_deadline_seconds,
                        operation_scope=operation_scope,
                        unit_of_work_factory=action_uow_factory,
                        label=self.config.title,
                    )
                )
''',
)

# Resource CRUD launchers must follow the same exact permission keys as the route gate.
resource_routes = "packages/rakit-web/src/rakit_web/resource_routes.py"
replace_once(
    resource_routes,
    '''from rakit_core.pagination import ResourcePaginationPolicy
from rakit_core.query import ResourceQuery
''',
    '''from rakit_core.pagination import ResourcePaginationPolicy
from rakit_core.permissions import PermissionRequirement
from rakit_core.query import ResourceQuery
''',
)
replace_once(
    resource_routes,
    '''    crud_paths: ResourceCrudPaths | None = None
    codec: IdentityCodec = field(default_factory=IdentityCodec)

    @property
''',
    '''    crud_paths: ResourceCrudPaths | None = None
    admin_id: str = "admin"
    auth_enabled: bool = False
    superuser_bypass: bool = True
    codec: IdentityCodec = field(default_factory=IdentityCodec)

    def can_mutate(self, request: Request, operation: str) -> bool:
        if self.crud_paths is None:
            return False
        if not self.auth_enabled:
            return True
        principal = request.scope.get("state", {}).get("principal")
        if principal is None or not principal.authenticated:
            return False
        requirement = PermissionRequirement.all_of(
            f"{self.admin_id}.resources.{self.resource_id}.{operation}"
        )
        return requirement.matches(principal, superuser_bypass=self.superuser_bypass)

    @property
''',
)
replace_once(
    resource_routes,
    '''            "create_url": (
                _mounted_path(request, binding.crud_paths.create_path)
                if binding.crud_paths is not None
                else ""
            ),
''',
    '''            "create_url": (
                _mounted_path(request, binding.crud_paths.create_path)
                if binding.crud_paths is not None and binding.can_mutate(request, "create")
                else ""
            ),
''',
)
replace_once(
    resource_routes,
    '''        if binding.crud_paths is not None:
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
''',
    '''        if binding.crud_paths is not None:
            if binding.crud_paths.update_path and binding.can_mutate(request, "update"):
                edit_url = _mounted_path(
                    request,
                    binding.crud_paths.update_path.replace("{identity}", encoded_identity),
                )
            if binding.crud_paths.delete_path and binding.can_mutate(request, "delete"):
                delete_url = _mounted_path(
                    request,
                    binding.crud_paths.delete_path.replace("{identity}", encoded_identity),
                )
''',
)

# Route middleware must classify framework bulk delete as the resource DELETE capability.
auth = "packages/rakit-web/src/rakit_web/security/authentication.py"
replace_once(
    auth,
    '''                    if suffix == ["new"]:
                        operation = "create"
                    elif len(suffix) == 2 and suffix[1] in {"edit", "delete"}:
                        operation = "update" if suffix[1] == "edit" else "delete"
                    elif len(suffix) >= 2 and suffix[1] == "_relationships":
''',
    '''                    if suffix == ["new"]:
                        operation = "create"
                    elif suffix == ["_bulk", "delete"]:
                        operation = "delete"
                    elif len(suffix) == 2 and suffix[1] in {"edit", "delete"}:
                        operation = "update" if suffix[1] == "edit" else "delete"
                    elif len(suffix) >= 2 and suffix[1] == "_relationships":
''',
)

# Fix the bulk delete helper's preflight typing without changing runtime behavior.
bulk_delete = "packages/rakit-web/src/rakit_web/bulk_delete.py"
replace_once(
    bulk_delete,
    '''from rakit_core.identity import RecordIdentity
''',
    '''from rakit_core.identity import RecordIdentity
from rakit_core.mutations import MutationAuthorization
''',
)
replace_once(
    bulk_delete,
    '''        preflight: list[tuple[RecordIdentity, object, object]] = []
''',
    '''        preflight: list[tuple[RecordIdentity, object, MutationAuthorization]] = []
''',
)
replace_once(
    bulk_delete,
    '''                        cast("object", authorization),
''',
    '''                        authorization,
''',
)

# Resource table: shared click-away popover, page select-all, and a reusable dialog host.
table = "packages/rakit-web/src/rakit_web/templates/resources/_table.html"
replace_once(
    table,
    '''      <form method="get" data-rakit-bulk-actions="{{ resource.resource_id }}">
''',
    '''      <form method="get" data-rakit-bulk-actions="{{ resource.resource_id }}" data-rakit-bulk-selection>
''',
)
# Every bulk submit button remains a normal GET submitter for no-JS; JS only enhances it.
text = Path(table).read_text()
text = text.replace('type="submit" formaction="{{ action.url }}"', 'type="submit" formaction="{{ action.url }}" data-rakit-bulk-review-trigger')
text = text.replace('type="submit" formaction="{{ bulk_primary.item.url }}"', 'type="submit" formaction="{{ bulk_primary.item.url }}" data-rakit-bulk-review-trigger')
Path(table).write_text(text)
replace_once(
    table,
    '''              <div class="absolute left-0 z-20 mt-2 min-w-56 rounded-lg border border-rakit-border bg-rakit-surface p-2 shadow-lg">
''',
    '''              <div class="rakit-popover min-w-56">
''',
)
replace_once(
    table,
    '''{% if action.intent == 'danger' %} mt-1 border-t border-rakit-border pt-3 text-red-700 hover:bg-red-50{% else %} text-rakit-text hover:bg-rakit-surface-muted{% endif %}''',
    '''{% if action.intent == 'danger' %} mt-1 border-t border-rakit-border pt-3 text-rakit-danger hover:bg-rakit-danger-subtle{% else %} text-rakit-text hover:bg-rakit-surface-subtle{% endif %}''',
)
replace_once(
    table,
    '''                <th scope="col" class="w-12 px-4 py-3"><span class="sr-only">Select</span></th>
''',
    '''                <th scope="col" class="w-12 px-4 py-3">
                  <input class="rakit-checkbox" type="checkbox" data-rakit-select-page aria-label="Select all records on this page" />
                </th>
''',
)
replace_once(
    table,
    '''                  <input class="rakit-checkbox" type="checkbox" name="selected" value="{{ row.detail_url.rsplit('/', 1)[-1] }}" aria-label="Select {{ row.display_cells[0] }}" />
''',
    '''                  <input class="rakit-checkbox" type="checkbox" name="selected" value="{{ row.detail_url.rsplit('/', 1)[-1] }}" data-rakit-select-row aria-label="Select {{ row.display_cells[0] }}" />
''',
)
replace_once(
    table,
    '''      {% if bulk_actions %}
      </form>
      {% endif %}

      <div class="flex flex-col gap-3 border-t border-rakit-border pt-4 lg:flex-row lg:items-center lg:justify-between"''',
    '''      {% if bulk_actions %}
      </form>
      <dialog
        id="rakit-bulk-dialog-{{ resource.resource_id }}"
        class="rakit-dialog"
        data-rakit-dialog
        data-rakit-dialog-backdrop-close
        data-rakit-bulk-dialog
        aria-label="Bulk action"
      >
        <div class="rakit-dialog-body" data-rakit-bulk-dialog-content></div>
      </dialog>
      {% endif %}

      <div class="flex flex-col gap-3 border-t border-rakit-border pt-4 lg:flex-row lg:items-center lg:justify-between"''',
)

# Stable native select semantics with a framework-positioned CSS chevron.
css = "packages/rakit-web/src/rakit_web/assets/rakit.css"
replace_once(
    css,
    '''  .rakit-select {
    @apply block min-h-9 w-full appearance-auto rounded-rakit-sm border border-rakit-border-strong bg-rakit-surface px-3 py-1.5 pr-8 text-sm text-rakit-text shadow-rakit-sm focus:border-rakit-focus;
  }
''',
    '''  .rakit-select {
    @apply block min-h-9 w-full appearance-none rounded-rakit-sm border border-rakit-border-strong bg-rakit-surface px-3 py-1.5 pr-10 text-sm text-rakit-text shadow-rakit-sm focus:border-rakit-focus;
    background-image: linear-gradient(45deg, transparent 50%, currentColor 50%), linear-gradient(135deg, currentColor 50%, transparent 50%);
    background-position: calc(100% - 1rem) calc(50% - 0.125rem), calc(100% - 0.7rem) calc(50% - 0.125rem);
    background-repeat: no-repeat;
    background-size: 0.32rem 0.32rem;
  }
''',
)

# Bulk selection state + modal review progressive enhancement.
ui = "packages/rakit-web/src/rakit_web/static/rakit-ui.js"
insert_before = '''document.addEventListener("DOMContentLoaded", () => {
'''
helpers = r'''function rakitBulkRows(form) {
  return [...form.querySelectorAll("[data-rakit-select-row]")].filter(
    (row) => row instanceof HTMLInputElement && !row.disabled,
  );
}

function rakitSyncBulkSelection(form) {
  if (!(form instanceof HTMLFormElement)) return;
  const rows = rakitBulkRows(form);
  const selected = rows.filter((row) => row.checked);
  const page = form.querySelector("[data-rakit-select-page]");
  if (page instanceof HTMLInputElement) {
    page.checked = rows.length > 0 && selected.length === rows.length;
    page.indeterminate = selected.length > 0 && selected.length < rows.length;
  }
  const count = form.querySelector("[data-rakit-selected-count]");
  if (count instanceof HTMLElement) count.textContent = `${selected.length} selected`;
}

function rakitEnhanceBulkSelections(root = document) {
  const direct = root instanceof HTMLFormElement && root.hasAttribute("data-rakit-bulk-selection")
    ? [root]
    : [];
  const nested = root.querySelectorAll?.("form[data-rakit-bulk-selection]") || [];
  [...direct, ...nested].forEach((form) => rakitSyncBulkSelection(form));
}

function rakitBulkDialog(form) {
  const resourceId = form.dataset.rakitBulkActions;
  if (!resourceId) return null;
  const dialog = document.getElementById(`rakit-bulk-dialog-${resourceId}`);
  return dialog instanceof HTMLDialogElement ? dialog : null;
}

function rakitShowBulkDialog(form, trigger, content) {
  const dialog = rakitBulkDialog(form);
  if (!(dialog instanceof HTMLDialogElement)) return false;
  const target = dialog.querySelector("[data-rakit-bulk-dialog-content]");
  if (!(target instanceof HTMLElement)) return false;
  target.innerHTML = content;
  rakitEnhanceGenericDialog(dialog);
  rakitGenericDialogReturnFocus.set(dialog, trigger);
  if (!dialog.open) dialog.showModal();
  const initialFocus = dialog.querySelector(
    "[data-rakit-dialog-initial-focus], button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled)",
  );
  if (initialFocus instanceof HTMLElement) initialFocus.focus({ preventScroll: true });
  return true;
}

async function rakitOpenBulkReview(form, submitter) {
  const selected = rakitBulkRows(form).filter((row) => row.checked);
  if (!selected.length) {
    const content = `
      <section class="space-y-5" data-rakit-bulk-feedback>
        <header><h1 class="text-xl font-semibold tracking-tight text-rakit-text">Bulk action needs attention</h1></header>
        <div class="rakit-alert rakit-alert-danger" role="alert">Select at least one resource before running a bulk action.</div>
        <footer class="flex justify-end"><button class="rakit-button rakit-button-secondary" type="button" data-rakit-dialog-close>Close</button></footer>
      </section>`;
    rakitShowBulkDialog(form, submitter, content);
    return;
  }

  const url = new URL(submitter.formAction || form.action || window.location.href, window.location.href);
  url.search = "";
  selected.forEach((row) => url.searchParams.append("selected", row.value));
  try {
    const response = await fetch(url, {
      credentials: "same-origin",
      headers: { Accept: "text/html", "X-Rakit-Dialog": "bulk" },
    });
    const content = await response.text();
    if (!rakitShowBulkDialog(form, submitter, content)) window.location.assign(url);
  } catch {
    window.location.assign(url);
  }
}

'''
replace_once(ui, insert_before, helpers + insert_before)
replace_once(
    ui,
    '''  rakitEnhanceFilterUis(document);
  rakitEnhanceGenericDialogs(document);
});
''',
    '''  rakitEnhanceFilterUis(document);
  rakitEnhanceGenericDialogs(document);
  rakitEnhanceBulkSelections(document);
});
''',
)
# Add a submit enhancement before the existing click handler.
replace_once(
    ui,
    '''document.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof Element)) return;
''',
    '''document.addEventListener("submit", (event) => {
  const form = event.target;
  const submitter = event.submitter;
  if (
    !(form instanceof HTMLFormElement) ||
    !form.hasAttribute("data-rakit-bulk-actions") ||
    !(submitter instanceof HTMLButtonElement) ||
    !submitter.hasAttribute("data-rakit-bulk-review-trigger") ||
    !("HTMLDialogElement" in window)
  ) return;
  event.preventDefault();
  rakitOpenBulkReview(form, submitter);
});

document.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof Element)) return;
''',
)
# Extend the existing change listener before relationship-select handling.
replace_once(
    ui,
    '''document.addEventListener("change", (event) => {
  const select = event.target;
  if (!(select instanceof HTMLSelectElement) || !select.matches("[data-rakit-relationship-set]")) {
    return;
  }
''',
    '''document.addEventListener("change", (event) => {
  const control = event.target;
  if (control instanceof HTMLInputElement && control.matches("[data-rakit-select-page]")) {
    const form = control.closest("form[data-rakit-bulk-selection]");
    if (form instanceof HTMLFormElement) {
      rakitBulkRows(form).forEach((row) => { row.checked = control.checked; });
      rakitSyncBulkSelection(form);
    }
    return;
  }
  if (control instanceof HTMLInputElement && control.matches("[data-rakit-select-row]")) {
    const form = control.closest("form[data-rakit-bulk-selection]");
    if (form instanceof HTMLFormElement) rakitSyncBulkSelection(form);
    return;
  }

  const select = control;
  if (!(select instanceof HTMLSelectElement) || !select.matches("[data-rakit-relationship-set]")) {
    return;
  }
''',
)
replace_once(
    ui,
    '''  rakitEnhanceFilterUis(root);
  rakitEnhanceGenericDialogs(root);
});
''',
    '''  rakitEnhanceFilterUis(root);
  rakitEnhanceGenericDialogs(root);
  rakitEnhanceBulkSelections(root);
});
''',
)

print("UI-06 polish source patch applied")
