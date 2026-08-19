# Field and relationship presentations

Rakit separates data semantics from Web presentation. Field types, relationship cardinality,
permissions, validation, storage policy, and mutation behavior remain authoritative; a
`presentation=` object only selects a typed interaction and rendering policy for the built-in Web UI.

## Direct declarations

Direct field and relationship declarations can carry a typed presentation inline:

```python
from decimal import Decimal

from rakit import Autocomplete, Currency, FieldDefinition, RelationshipDefinition
from rakit import RelationshipCardinality, RelationshipKind
from rakit_core.relationships import RelationshipEditMode

price = FieldDefinition(
    field_id="price",
    python_type=Decimal,
    presentation=Currency(currency="IDR", locale="id-ID"),
)

customer = RelationshipDefinition(
    relationship_id="customer",
    target_resource_id="customers",
    label="Customer",
    kind=RelationshipKind.MANY_TO_ONE,
    cardinality=RelationshipCardinality.TO_ONE,
    writable=True,
    edit_mode=RelationshipEditMode.LINK,
    record_label_field="name",
    presentation=Autocomplete(
        search_fields=("name", "email"),
        display_fields=("name", "email"),
        placeholder="Search customer...",
    ),
)
```

`rakit-core` carries this presentation value as opaque metadata. Core parsing, query, authorization,
storage, and mutation code does not import or branch on Web presentation types.

## Adapter-generated resources

When an adapter generates fields or relationships, use `ResourceWebPresentation` to override the
Web presentation without changing adapter-owned semantic metadata:

```python
from rakit import Autocomplete, MultiAutocomplete, ResourceWebPresentation

admin.register(
    OrdersAdmin,
    web=ResourceWebPresentation(
        relationships={
            "customer": Autocomplete(
                search_fields=("name",),
                display_fields=("name", "email"),
            ),
            "participants": MultiAutocomplete(
                search_fields=("name",),
                display_fields=("name", "email"),
            ),
        }
    ),
)
```

Resolution is deterministic:

1. `ResourceWebPresentation` override;
2. inline `presentation=` value;
3. legacy `FieldDefinition.widget` compatibility hint;
4. a conservative safe default based on the field type.

Rakit does not infer domain intent such as currency, percentages, switches, or remote autocomplete
from a Python type or database row count.

## Built-in presentations

UI-07D provides these first-wave presentation types:

| Family | Presentations |
| --- | --- |
| Choice and relationship | `Select`, `SearchableSelect`, `Autocomplete`, `MultiAutocomplete` |
| Date and time | `DatePicker`, `TimePicker`, `DateTimePicker`, `DateRangePicker` |
| Numeric | `NumberInput`, `Currency`, `Percentage` |
| Boolean and small choice | `Checkbox`, `Switch`, `SegmentedControl` |
| File | `FileUpload`, `ImageUpload` |

`DateRangePicker` is limited to one typed range value in this wave; it does not compose arbitrary
`start_date` and `end_date` fields.

## Relationship autocomplete

`Autocomplete` is for one related identity; `MultiAutocomplete` is for to-many relationships.
The browser displays labels but transports canonical encoded identities. Labels are never treated as
mutation identity.

Candidate discovery uses the existing relationship candidate/query path. It remains bounded by the
server, requires the exact relationship permission, verifies the parent resource, and uses the target
resource's existing searchable/query policy. A presentation may narrow the configured search fields;
it may not broaden the fields already allowed by the relationship editor.

Remote autocomplete uses a small bounded page of candidates and progressive enhancement. JavaScript
adds keyboard navigation, live loading/empty/error states, selection chips, request debouncing, and
stale-response protection. The server remains authoritative if a stale, malformed, or unauthorized
identity is submitted.

For a large candidate set, the no-JavaScript path provides a separate server-rendered searchable and
paginated picker rather than expanding the entire target table into one `<select>`.

## Canonical types stay canonical

Presentation never creates an alternate business type:

- `Currency` still submits a numeric value such as `Decimal` after normal form parsing;
- `Percentage` requires explicit whole/fraction scale semantics;
- `Switch` remains a boolean control;
- date/time presentations keep the declared date/time type;
- `FileUpload` and `ImageUpload` still use the existing `FileField` storage and validation policy.

For monetary values, prefer `Decimal` over `float`.

## Progressive enhancement

Advanced presentations retain semantic native fallbacks:

| Advanced presentation | No-JavaScript baseline |
| --- | --- |
| `SearchableSelect` | native `<select>` |
| `Autocomplete` / `MultiAutocomplete` | bounded native candidates plus server picker |
| `DatePicker` | `<input type="date">` |
| `TimePicker` | `<input type="time">` |
| `DateTimePicker` | `<input type="datetime-local">` |
| `NumberInput` / `Currency` / `Percentage` | numeric input |
| `Switch` | checkbox |
| `SegmentedControl` | radio group |
| `FileUpload` / `ImageUpload` | `<input type="file">` |

The enhanced browser layer does not replace CSRF, permission checks, server validation, relationship
authorization, or storage policy.

## Custom presentation registry

`PresentationRegistry` is the Web rendering extension boundary. A custom presentation is an immutable
presentation object with a registered renderer. The renderer receives already-resolved form/view state
and returns rendering data; it must not fetch directly from a database or execute mutations.

Full distributable presentation-plugin packaging is intentionally deferred. UI-07D establishes the
typed registry boundary without turning custom widgets into a parallel application framework.
