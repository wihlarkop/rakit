from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one replacement, found {count}: {old[:90]!r}")
    file.write_text(text.replace(old, new, 1))


# Avoid collision with /{identity}/delete while keeping a reserved bulk namespace.
for path in (
    "packages/rakit-web/src/rakit_web/admin.py",
    "packages/rakit-web/src/rakit_web/bulk_admin.py",
    "packages/rakit-web/src/rakit_web/bulk_delete.py",
    "packages/rakit-web/src/rakit_web/security/authentication.py",
):
    text = Path(path).read_text()
    if path.endswith("authentication.py"):
        old = 'suffix == ["_bulk", "delete"]'
        new = 'suffix == ["_bulk", "delete-selected"]'
    else:
        old = '/_bulk/delete'
        new = '/_bulk/delete-selected'
    if old not in text:
        raise RuntimeError(f"{path}: missing expected bulk-delete path marker")
    Path(path).write_text(text.replace(old, new))

bulk_delete = "packages/rakit-web/src/rakit_web/bulk_delete.py"
replace_once(
    bulk_delete,
    '''from starlette.datastructures import FormData
from starlette.requests import Request
''',
    '''from starlette.datastructures import FormData
from starlette.exceptions import HTTPException
from starlette.requests import Request
''',
)
replace_once(
    bulk_delete,
    '''        if not await binding.write.verify_csrf(request):
            return _render_feedback(
                binding,
                request,
                title="Bulk delete rejected",
                message="Invalid CSRF token.",
                status_code=403,
            )
        if not await binding.write.verify_submission_token(request):
            return _render_feedback(
                binding,
                request,
                title="Bulk delete rejected",
                message="Invalid or expired submission token.",
                status_code=409,
            )
        try:
            form = await request.form(max_files=0, max_fields=(_MAX_SELECTED * 2) + 4)
        except Exception:
            return _render_feedback(
                binding,
                request,
                title="Bulk delete rejected",
                message="Invalid bulk delete submission.",
                status_code=400,
            )

''',
    '''        # Parse once with the bulk-specific bound before CSRF/submission
        # verifiers read the cached form. This avoids the generic form parser's
        # lower default field limit becoming an accidental bulk limit.
        try:
            form = await request.form(max_files=0, max_fields=(_MAX_SELECTED * 2) + 4)
        except HTTPException:
            return _render_feedback(
                binding,
                request,
                title="Bulk delete rejected",
                message="Invalid bulk delete submission.",
                status_code=400,
            )
        if not await binding.write.verify_csrf(request):
            return _render_feedback(
                binding,
                request,
                title="Bulk delete rejected",
                message="Invalid CSRF token.",
                status_code=403,
            )
        if not await binding.write.verify_submission_token(request):
            return _render_feedback(
                binding,
                request,
                title="Bulk delete rejected",
                message="Invalid or expired submission token.",
                status_code=409,
            )

''',
)
replace_once(
    bulk_delete,
    '''        reservation = await store.begin(
            hashlib.sha256(submission_token.encode()).hexdigest(),
            fingerprint=_fingerprint(selected, delete_tokens),
        )
        if reservation.status is IdempotencyStatus.COMPLETED:
            receipt = reservation.completed_receipt
            deleted = int((receipt.payload or {}).get("deleted", len(selected))) if receipt else 0
            return mutation_success(
                request,
                location=mounted_path(request, binding.write.path),
                message=f"Deleted {deleted} selected record{'s' if deleted != 1 else ''}.",
            )
''',
    '''        try:
            reservation = await store.begin(
                hashlib.sha256(submission_token.encode()).hexdigest(),
                fingerprint=_fingerprint(selected, delete_tokens),
            )
        except ValueError:
            return _render_feedback(
                binding,
                request,
                title="Bulk delete rejected",
                message="This submission token is bound to another bulk delete.",
                status_code=409,
            )
        if reservation.status is IdempotencyStatus.COMPLETED:
            receipt = reservation.completed_receipt
            payload = receipt.payload if receipt is not None and receipt.payload is not None else {}
            deleted = int(payload.get("deleted", len(selected)))
            failed = int(payload.get("failed", 0))
            if failed:
                return _render_feedback(
                    binding,
                    request,
                    title="Bulk delete partially completed",
                    message=(
                        f"Deleted {deleted} selected record{'s' if deleted != 1 else ''}; "
                        f"{failed} could not be deleted. Refresh the resource before retrying."
                    ),
                    status_code=409,
                    tone="warning",
                )
            return mutation_success(
                request,
                location=mounted_path(request, binding.write.path),
                message=f"Deleted {deleted} selected record{'s' if deleted != 1 else ''}.",
            )
''',
)

print("UI-06 polish non-test review fixes applied")
