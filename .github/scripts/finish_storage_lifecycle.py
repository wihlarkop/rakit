from pathlib import Path

FORM_ROUTES = Path("packages/rakit-web/src/rakit_web/form_routes.py")
ADMIN = Path("packages/rakit-web/src/rakit_web/admin.py")
TESTS = Path("packages/rakit-web/tests/test_files.py")


def replace_once(text: str, old: str, new: str) -> str:
    if old not in text:
        raise RuntimeError(f"expected patch anchor was not found: {old[:120]!r}")
    return text.replace(old, new, 1)


text = FORM_ROUTES.read_text()
text = replace_once(
    text,
    "import uuid\nfrom collections.abc",
    "import uuid\nfrom urllib.parse import quote\nfrom collections.abc",
)
text = replace_once(
    text,
    "from starlette.responses import PlainTextResponse, Response\n",
    "from starlette.responses import PlainTextResponse, Response, StreamingResponse\n",
)
text = replace_once(
    text,
    "    FilePreparation,\n    canonical_submission_values,\n    compensate_uploads,\n",
    "    FilePreparation,\n    canonical_submission_values,\n    cleanup_deleted_record_files,\n    cleanup_replaced_uploads,\n    compensate_uploads,\n",
)
text = replace_once(
    text,
    "    prepare_file_submission,\n    submission_for_display,\n",
    "    prepare_file_submission,\n    record_stored_file,\n    submission_for_display,\n",
)

old_helpers = '''async def _compensate_bound_files(
    binding: WriteResourceBinding,
    preparation: FilePreparation,
) -> None:
    if not preparation.uploads:
        return
    async with _file_services(binding) as services:
        await compensate_uploads(preparation.uploads, services=services)
'''
new_helpers = old_helpers + '''

async def _cleanup_replaced_bound_files(
    binding: WriteResourceBinding,
    preparation: FilePreparation,
) -> None:
    if not preparation.uploads:
        return
    async with _file_services(binding) as services:
        await cleanup_replaced_uploads(preparation.uploads, services=services)


async def _cleanup_deleted_bound_files(
    binding: WriteResourceBinding,
    record: object,
) -> None:
    if not has_file_fields(binding.form_schema):
        return
    async with _file_services(binding) as services:
        await cleanup_deleted_record_files(binding.form_schema, record, services=services)
'''
text = replace_once(text, old_helpers, new_helpers)

start = text.index("    async def update_post(request: Request) -> Response:")
end = text.index("\n    async def delete_get", start)
update_block = '''    async def update_post(request: Request) -> Response:
        if not await binding.authorize(request):
            return _error(403, "Forbidden")
        identity = _identity(binding, request.path_params["identity"])
        if identity is None:
            return _error(400, "Invalid resource identity")
        authorization = await _authorization(binding, request, "update", identity)
        if authorization is None:
            return _error(403, "Forbidden")
        if not await binding.verify_csrf(request):
            return _error(403, "Invalid CSRF token")
        if not await binding.verify_submission_token(request):
            return _error(409, "Invalid submission token")
        record = await mutation_service.get(identity)
        if record is None:
            return _error(404, "Resource was not found")
        parsed = await _parse_form(request, binding)
        if parsed is None:
            return _error(400, "Invalid form")
        submitted, tokens = parsed
        display_submitted = submission_for_display(submitted)
        preparation = FilePreparation(values=dict(submitted), uploads=(), issues=())
        reservation: IdempotencyReservation | None = None
        try:
            scalar_submitted, _ = split_relationship_submission(
                binding.relationship_form, submitted
            )
            preparation = await _prepare_bound_files(
                binding,
                scalar_submitted,
                previous_record=record,
            )
            if preparation.issues:
                await _compensate_bound_files(binding, preparation)
                return await _form_response(
                    binding,
                    request,
                    title=f"Edit {binding.label}",
                    action_path=f"{binding.path}/{request.path_params['identity']}/edit",
                    submitted=display_submitted,
                    issues=preparation.issues,
                    concurrency_token=tokens.get("concurrency_token"),
                    operation="update",
                    status_code=422,
                    parent_identity=identity,
                )
            state = binding.form_schema.parse(preparation.values)
            normalized = dict(state.normalized)
            changes = (
                await build_relationship_changes(
                    binding.relationship_form, submitted, parent_identity=identity
                )
                if binding.relationship_form is not None
                else ()
            )
            if binding.relationship_form is not None:
                graph_service = cast(GraphMutationService, mutation_service)
                if not callable(getattr(graph_service, "update_graph", None)):
                    raise RakitError(
                        code=ErrorCode.CONFIG_INVALID,
                        message="Relationship forms require graph mutation support.",
                        status_code=500,
                    )
                graph_authorizations = await _graph_authorizations(
                    binding, request, authorization, identity, changes
                )
                await _execute_with_deadline(
                    binding,
                    request,
                    graph_service.update_graph(
                        identity,
                        state,
                        relationship_changes=changes,
                        authorizations=graph_authorizations,
                        concurrency_token=tokens.get("concurrency_token"),
                        idempotency_token=tokens.get("submission_token"),
                    ),
                    authorization,
                )
            else:
                reservation, replay = await _claim_submission(
                    binding,
                    request,
                    submitted=normalized,
                    tokens=tokens,
                    operation="update",
                    identity=identity,
                )
                if replay is not None:
                    await _compensate_bound_files(binding, preparation)
                    return replay
                await _execute_with_deadline(
                    binding,
                    request,
                    mutation_service.update(
                        identity,
                        state,
                        concurrency_token=tokens.get("concurrency_token"),
                        authorization=authorization,
                    ),
                    authorization,
                )
                if reservation is not None and binding.idempotency_store is not None:
                    await binding.idempotency_store.complete(
                        reservation,
                        OperationReceipt(
                            operation_id=str(uuid.uuid4()),
                            status="succeeded",
                            result_kind="redirect",
                            redirect_route=binding.path,
                        ),
                    )
            await _cleanup_replaced_bound_files(binding, preparation)
        except FormValidationError as exc:
            await _compensate_bound_files(binding, preparation)
            return await _form_response(
                binding,
                request,
                title=f"Edit {binding.label}",
                action_path=f"{binding.path}/{request.path_params['identity']}/edit",
                submitted=display_submitted,
                issues=exc.state.issues,
                concurrency_token=tokens.get("concurrency_token"),
                operation="update",
                status_code=422,
                parent_identity=identity,
            )
        except RakitError as exc:
            await _compensate_bound_files(binding, preparation)
            if reservation is not None and binding.idempotency_store is not None:
                await binding.idempotency_store.release(reservation)
            if binding.relationship_form is not None:
                return await _form_response(
                    binding,
                    request,
                    title=f"Edit {binding.label}",
                    action_path=f"{binding.path}/{request.path_params['identity']}/edit",
                    submitted=display_submitted,
                    issues=()
                    if _relationship_error_issues(exc)
                    else (FormIssue(None, exc.message),),
                    relationship_issues=_relationship_error_issues(exc),
                    concurrency_token=tokens.get("concurrency_token"),
                    operation="update",
                    status_code=exc.status_code,
                    parent_identity=identity,
                )
            return _error(exc.status_code, "Mutation rejected")
        except ValueError:
            await _compensate_bound_files(binding, preparation)
            if reservation is not None and binding.idempotency_store is not None:
                await binding.idempotency_store.release(reservation)
            return _error(400, "Invalid form")
        return mutation_success(
            request,
            location=mounted_path(request, binding.path),
            refresh_targets=binding.htmx_refresh_targets,
            message=binding.success_message,
        )
'''
text = text[:start] + update_block + text[end:]

start = text.index("    async def delete_post(request: Request) -> Response:")
end = text.index("\n    routes.extend", start)
delete_and_download = '''    async def delete_post(request: Request) -> Response:
        if not await binding.authorize(request):
            return _error(403, "Forbidden")
        identity = _identity(binding, request.path_params["identity"])
        if identity is None:
            return _error(400, "Invalid resource identity")
        authorization = await _authorization(binding, request, "delete", identity)
        if authorization is None:
            return _error(403, "Forbidden")
        if not await binding.verify_csrf(request):
            return _error(403, "Invalid CSRF token")
        if not await binding.verify_submission_token(request):
            return _error(409, "Invalid submission token")
        parsed = await _parse_form(request, binding)
        if parsed is None:
            return _error(400, "Invalid form")
        submitted, tokens = parsed
        token = tokens.get("delete_token")
        if not token:
            return _error(400, "Invalid delete confirmation")
        record = await mutation_service.get(identity)
        if record is None:
            return _error(404, "Resource was not found")
        reservation: IdempotencyReservation | None = None
        try:
            reservation, replay = await _claim_submission(
                binding,
                request,
                submitted=submitted,
                tokens=tokens,
                operation="delete",
                identity=identity,
            )
            if replay is not None:
                return replay
            await _execute_with_deadline(
                binding,
                request,
                mutation_service.delete(token, identity=identity, authorization=authorization),
                authorization,
            )
            if reservation is not None and binding.idempotency_store is not None:
                await binding.idempotency_store.complete(
                    reservation,
                    OperationReceipt(
                        operation_id=str(uuid.uuid4()),
                        status="succeeded",
                        result_kind="redirect",
                        redirect_route=binding.path,
                    ),
                )
            await _cleanup_deleted_bound_files(binding, record)
        except RakitError as exc:
            if reservation is not None and binding.idempotency_store is not None:
                await binding.idempotency_store.release(reservation)
            return _error(exc.status_code, "Delete rejected")
        except ValueError:
            if reservation is not None and binding.idempotency_store is not None:
                await binding.idempotency_store.release(reservation)
            return _error(400, "Delete rejected")
        return mutation_success(
            request,
            location=mounted_path(request, binding.path),
            refresh_targets=binding.htmx_refresh_targets,
            message=binding.success_message,
        )

    async def download_file(request: Request) -> Response:
        if not await binding.authorize(request):
            return _error(403, "Forbidden")
        identity = _identity(binding, request.path_params["identity"])
        if identity is None:
            return _error(400, "Invalid resource identity")
        field_id = request.path_params["field_id"]
        field = next(
            (
                candidate
                for candidate in file_fields(binding.form_schema)
                if candidate.field_id == field_id and candidate.readable and not candidate.sensitive
            ),
            None,
        )
        if field is None:
            return _error(404, "File was not found")
        record = await mutation_service.get(identity)
        if record is None:
            return _error(404, "Resource was not found")
        stored = record_stored_file(record, field)
        if stored is None:
            return _error(404, "File was not found")
        if stored.storage_id != field.storage_id:
            return _error(404, "File was not found")

        async def stream() -> AsyncIterator[bytes]:
            async with _file_services(binding) as services:
                storage = services.require(FileStorage, name=stored.storage_id)
                await storage.resolve_access(stored)
                async for chunk in storage.open(stored):
                    yield chunk

        filename = quote(stored.original_name, safe="")
        return StreamingResponse(
            stream(),
            media_type=stored.content_type,
            headers={
                "Cache-Control": "private, no-store",
                "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
                "Content-Length": str(stored.size),
                "X-Content-Type-Options": "nosniff",
            },
        )
'''
text = text[:start] + delete_and_download + text[end:]

old_routes = '''            Route(
                binding.delete_path,
                delete_post,
                methods=["POST"],
                name=f"resource:{binding._route_resource_id}:delete.submit",
            ),
'''
new_routes = old_routes + '''            Route(
                f"{binding.path}/{{identity}}/_files/{{field_id}}",
                download_file,
                methods=["GET"],
                name=f"resource:{binding._route_resource_id}:file.download",
            ),
'''
text = replace_once(text, old_routes, new_routes)
FORM_ROUTES.write_text(text)

text = ADMIN.read_text()
old = '''            (f"resource:{resource_id}:delete", ("GET",), binding.delete_path),
            (f"resource:{resource_id}:delete.submit", ("POST",), binding.delete_path),
'''
new = old + '''            (
                f"resource:{resource_id}:file.download",
                ("GET",),
                f"{binding.path}/{{identity}}/_files/{{field_id}}",
            ),
'''
text = replace_once(text, old, new)
ADMIN.write_text(text)

text = TESTS.read_text()
text = replace_once(
    text,
    "from rakit_core.di import ServiceRegistry, ServiceScope\n",
    "from rakit_core.di import ServiceRegistry, ServiceScope\nfrom rakit_core.events import EventBus, EventPublisher\n",
)
old = '''    registry.add_value(
        FileStorage,
        storage,
        scope=ServiceScope.APPLICATION,
        name=storage.storage_id,
    )
'''
new = old + '''    registry.add_value(EventBus, EventBus(), scope=ServiceScope.APPLICATION)
    registry.add_factory(
        EventPublisher,
        lambda resolver: EventPublisher(resolver.require(EventBus)),
        scope=ServiceScope.OPERATION,
    )
'''
text = replace_once(text, old, new)
TESTS.write_text(text)
