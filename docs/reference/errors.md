# Errors

Framework failures use `RakitError` with an `ErrorCode`, human-facing message, HTTP status where
applicable, structured safe details, and an optional internal cause. Public callers should branch on
the error code/details contract rather than parsing English messages.

Configuration errors fail before serving when possible. Request validation/auth failures are
translated at the web boundary without exposing internal exception tracebacks in production.

Public warning classes include configuration, deprecation, performance, and security warnings.
Warnings are not substitutes for errors: an unsafe configuration that Rakit cannot support safely
fails closed rather than merely warning.

Adapter contract suites include portable error-translation checks where the adapter advertises the
corresponding capability. Third-party adapters should translate backend-specific exceptions at the
adapter boundary instead of leaking database/storage implementation types into core callers.
