"""Public re-export of the plugin protocol.

`Plugin` is defined in `rakit_core.compiler` alongside `ApplicationBuilder`,
since the protocol's `configure` method is defined in terms of the builder
and the two are tightly coupled. This module exists so that plugin authors
can depend on a stable, purpose-named import (`rakit_core.plugins`) without
needing to know that the compiler module is where it physically lives.
"""

from .compiler import Plugin

__all__ = ["Plugin"]
