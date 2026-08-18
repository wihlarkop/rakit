"""Safe, Web-only presentation metadata for private file fields."""

from dataclasses import dataclass

from rakit_core.fields import FileField
from rakit_storage import StoredFile


@dataclass(frozen=True, slots=True)
class CurrentFilePresentation:
    """User-safe metadata for an already stored file."""

    name: str
    size_label: str
    content_type: str


@dataclass(frozen=True, slots=True)
class FileFieldPresentation:
    """Presentation-only upload policy and current-file state."""

    accept: str
    policy_hint: str
    current: CurrentFilePresentation | None = None


def _format_file_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        value = size / 1024
        unit = "KB"
    else:
        value = size / (1024 * 1024)
        unit = "MB"
    number = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{number} {unit}"


def _extension_label(extension: str) -> str:
    return extension.removeprefix(".").upper()


def file_field_presentation(
    field: FileField,
    current: StoredFile | None,
) -> FileFieldPresentation:
    """Build explanatory metadata without exposing storage implementation details."""

    hints: list[str] = []
    if field.allowed_extensions:
        hints.append(
            "Allowed files: "
            + ", ".join(_extension_label(extension) for extension in field.allowed_extensions)
        )
    elif field.allowed_mime_types:
        hints.append("Allowed types: " + ", ".join(field.allowed_mime_types))
    hints.append(f"Maximum size: {_format_file_size(field.max_size)}")
    if field.max_filename_length < 255:
        hints.append(f"File name: up to {field.max_filename_length} characters")

    current_view = (
        CurrentFilePresentation(
            name=current.original_name,
            size_label=_format_file_size(current.size),
            content_type=current.content_type,
        )
        if current is not None
        else None
    )
    return FileFieldPresentation(
        accept=",".join((*field.allowed_extensions, *field.allowed_mime_types)),
        policy_hint=". ".join(hints) + ".",
        current=current_view,
    )


__all__ = ["CurrentFilePresentation", "FileFieldPresentation", "file_field_presentation"]
