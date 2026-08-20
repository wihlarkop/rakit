from pathlib import Path


BRANCH = "phase-c1-crud-lifecycle-ergonomics"


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, got {count}: {old[:100]!r}")
    file.write_text(text.replace(old, new, 1))


def main() -> None:
    admin_path = Path("packages/rakit-web/src/rakit_web/admin.py")
    if "    def on_startup(" in admin_path.read_text():
        print("C1 Admin source patch already applied")
        return

    core = "packages/rakit/src/rakit/core.py"
    replace_once(
        core,
        "from rakit_core.auth import (\n",
        "from rakit_core.admin_types import ResourceWriteDefinition\nfrom rakit_core.auth import (\n",
    )
    replace_once(
        core,
        "from rakit_core.idempotency import (\n",
        "from rakit_core.generated_runtime import (\n"
        "    ResourceWriteServiceContext,\n"
        "    ResourceWriteServiceProvider,\n"
        ")\n"
        "from rakit_core.idempotency import (\n",
    )
    replace_once(
        core,
        '    "ResourceService",\n',
        '    "ResourceService",\n'
        '    "ResourceWriteDefinition",\n'
        '    "ResourceWriteServiceContext",\n'
        '    "ResourceWriteServiceProvider",\n',
    )

    admin = str(admin_path)
    replace_once(
        admin,
        "from types import SimpleNamespace\n",
        "from types import SimpleNamespace\nfrom typing import cast\n",
    )
    replace_once(
        admin,
        "from rakit_core.admin_types import ModelAdmin, ResourceAdmin\n",
        "from rakit_core.admin_types import ModelAdmin, ResourceAdmin, ResourceWriteDefinition\n",
    )
    replace_once(
        admin,
        "from rakit_core.generated_runtime import (\n"
        "    GeneratedResourceExecutorContext,\n"
        "    normalize_resource_adapter_runtime,\n"
        ")\n",
        "from rakit_core.generated_runtime import (\n"
        "    GeneratedResourceExecutorContext,\n"
        "    ResourceWriteServiceContext,\n"
        "    normalize_resource_adapter_runtime,\n"
        ")\n",
    )

    replace_once(
        admin,
        '''    @property
    def event_bus(self) -> EventBus:
        """The application-scoped bus used by every mutation operation."""
        return self._event_bus

    def install(self, plugin: Plugin) -> None:
''',
        '''    @property
    def event_bus(self) -> EventBus:
        """The application-scoped bus used by every mutation operation."""
        return self._event_bus

    def on_startup(
        self, callback: Callable[[], Awaitable[None]]
    ) -> Callable[[], Awaitable[None]]:
        """Register fail-fast startup work and return the callback unchanged."""
        self.lifecycle.register_starting_callback(callback)
        return callback

    def on_shutdown(
        self, callback: Callable[[], Awaitable[None]]
    ) -> Callable[[], Awaitable[None]]:
        """Register shutdown cleanup and return the callback unchanged."""
        self.lifecycle.register_stopping_callback(callback)
        return callback

    def add_health_check(
        self,
        name: str,
        check: Callable[[], Awaitable[bool]],
        *,
        critical: bool,
        timeout_seconds: float = 2.0,
        cache_seconds: float = 5.0,
    ) -> None:
        """Register one readiness check through the public Admin facade."""
        self.lifecycle.register_health_check(
            name,
            check,
            critical=critical,
            timeout_seconds=timeout_seconds,
            cache_seconds=cache_seconds,
        )

    def install(self, plugin: Plugin) -> None:
''',
    )

    replace_once(
        admin,
        '''        actions = resource_actions(
            admin_cls,
            existing_action_ids={str(action.action_id) for action in self._builder.actions},
        )

        if issubclass(admin_cls, ModelAdmin):
''',
        '''        actions = resource_actions(
            admin_cls,
            existing_action_ids={str(action.action_id) for action in self._builder.actions},
        )
        write_definition = getattr(admin_cls, "write", None)
        if write_definition is not None and not isinstance(
            write_definition, ResourceWriteDefinition
        ):
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,
                message="Invalid resource write policy declaration",
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                details={
                    "resource_id": admin_cls.resource_id,
                    "reason": "invalid_write_definition",
                },
            )

        if issubclass(admin_cls, ModelAdmin):
''',
    )

    replace_once(
        admin,
        '''        data_source = adapter_runtime.data_source
        unknown_predicate_fields = set(predicate_fields).difference(data_source.fields)
''',
        '''        data_source = adapter_runtime.data_source
        declarative_mutation_service: CreateMutationService | None = None
        if write_definition is not None:
            provider = adapter_runtime.write_service_provider
            if provider is None:
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,
                    message="Installed adapter cannot provide declared resource writes",
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    details={
                        "resource_id": admin_cls.resource_id,
                        "reason": "write_provider_unavailable",
                    },
                )
            if self._auth_backend is None or self._session_store is None:
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID,
                    message="Declarative write resources require configured authentication.",
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    details={
                        "resource_id": admin_cls.resource_id,
                        "reason": "missing_authentication",
                    },
                )
            secret_key = self.config.security.secret_key
            if secret_key is None:
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID,
                    message="Declarative write resources require a configured secret key.",
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    details={
                        "resource_id": admin_cls.resource_id,
                        "reason": "missing_secret_key",
                    },
                )
            if self._operation_idempotency_store is None:
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID,
                    message=(
                        "Declarative write resources require an Admin "
                        "operation_idempotency_store."
                    ),
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    details={
                        "resource_id": admin_cls.resource_id,
                        "reason": "missing_idempotency_store",
                    },
                )
            unknown_write_fields = set(write_definition.writable_fields).difference(
                data_source.fields
            )
            if unknown_write_fields:
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,
                    message="Invalid resource write policy declaration",
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    details={
                        "resource_id": admin_cls.resource_id,
                        "reason": "unknown_writable_field",
                        "fields": sorted(unknown_write_fields),
                    },
                )
            token_service = TokenService.single_key(
                key_id="primary",
                value=secret_key,
                admin_id=self.config.admin_id,
            )
            try:
                mutation_candidate = provider.build(
                    ResourceWriteServiceContext(
                        admin_id=self.config.admin_id,
                        resource_id=admin_cls.resource_id,
                        definition=write_definition,
                        token_service=token_service,
                    )
                )
            except RakitError:
                raise
            except (TypeError, ValueError) as exc:
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,
                    message="Adapter could not materialize declared resource writes",
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    details={
                        "resource_id": admin_cls.resource_id,
                        "reason": "write_provider_failed",
                    },
                    cause=exc,
                ) from exc
            missing_write_members = tuple(
                name
                for name in (
                    "create",
                    "get",
                    "issue_update_token",
                    "update",
                    "issue_delete_token",
                    "delete",
                )
                if not callable(getattr(mutation_candidate, name, None))
            )
            if missing_write_members:
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,
                    message="Adapter returned an invalid resource write service",
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    details={
                        "resource_id": admin_cls.resource_id,
                        "reason": "invalid_write_provider_contract",
                        "members": missing_write_members,
                    },
                )
            declarative_mutation_service = cast(CreateMutationService, mutation_candidate)

        unknown_predicate_fields = set(predicate_fields).difference(data_source.fields)
''',
    )

    replace_once(
        admin,
        '''        self._resource_services[admin_cls.resource_id] = ResourceService(data_source)
        self._resource_definitions[admin_cls.resource_id] = definition

    def register_concurrency_provider(
''',
        '''        self._resource_services[admin_cls.resource_id] = ResourceService(data_source)
        self._resource_definitions[admin_cls.resource_id] = definition
        if write_definition is not None:
            assert declarative_mutation_service is not None
            self.register_write(
                admin_cls.resource_id,
                form_schema=write_definition.form_schema,
                mutation_service=declarative_mutation_service,
                success_message=write_definition.success_message,
                htmx_refresh_targets=write_definition.htmx_refresh_targets,
            )

    def register_concurrency_provider(
''',
    )


if __name__ == "__main__":
    main()
