# Schema adapters

Rakit keeps schema behavior behind the framework-neutral `SchemaAdapter` contract. Concrete schema engines live in first-party integration packages rather than in `rakit-core` or `rakit-web`.

## Default: Pydantic

The ordinary `rakit` distribution installs `rakit-schema-pydantic`, so an `Admin` with no explicit schema selection resolves `schema.pydantic` deterministically.

```python
from rakit import Admin

admin = Admin(title="Backoffice")
```

The adapter accepts native Pydantic `BaseModel` classes. Rakit does not introduce a separate schema DSL or base model.

## Optional: msgspec

Install the msgspec integration through the root convenience extra:

```bash
uv add "rakit[msgspec]"
```

Then select it explicitly:

```python
from rakit import Admin

admin = Admin(
    title="Backoffice",
    schema_integration_id="schema.msgspec",
)
```

The adapter accepts native `msgspec.Struct` classes. Installing msgspec does **not** make it active by discovery order; when both adapters are installed and no explicit selection is provided, Pydantic remains the default.

For modular installations, `rakit-schema-msgspec` and `rakit-schema-pydantic` can also be installed directly. `rakit-core` and `rakit-web` do not require either concrete schema engine.

## Capability contract

Both first-party adapters currently pass the same four version-1 schema capability contracts:

| Capability | Pydantic | msgspec |
| --- | --- | --- |
| `schema.field-introspection@1` | Yes | Yes |
| `schema.input-validation@1` | Yes | Yes |
| `schema.output-serialization@1` | Yes | Yes |
| `schema.partial-update@1` | Yes | Yes |

Capability parity is a result of conformance, not a requirement imposed on future adapters. A future schema integration should advertise only the capabilities it can satisfy honestly.

### Partial update semantics

`schema.partial-update@1` is presence-aware:

- omitted required fields do not have to be supplied;
- an omitted field is different from a field explicitly supplied as `None`;
- only supplied fields are returned;
- validation still applies to each supplied field;
- an empty mapping is a valid partial input.

For example, if `nickname` is nullable, `{}` remains `{}`, while `{"nickname": None}` remains `{"nickname": None}`.

## Discovery and explicit selection

Schema adapter packages publish two separate kinds of entry points:

- `rakit.integrations` exposes capability/discovery metadata;
- `rakit.schema_adapters` exposes the concrete runtime adapter factory.

Runtime selection never uses "first installed wins". An explicit integration identifier must resolve to an installed adapter or configuration fails with the requested identifier and the available installed schema integrations.

Passing a concrete `schema_adapter=` remains supported for custom or advanced composition. If both a concrete adapter and `schema_integration_id=` are supplied, their integration metadata must agree or configuration fails closed.
