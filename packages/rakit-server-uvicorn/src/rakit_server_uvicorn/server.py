from dataclasses import dataclass, fields
from typing import Any

import uvicorn


@dataclass(frozen=True)
class UvicornServer:
    app: str
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False
    log_level: str | None = None

    def run(self, **overrides: Any) -> None:
        unsupported = set(overrides) - {f.name for f in fields(self)}
        if unsupported:
            raise ValueError(
                f"Unsupported Uvicorn option(s): {', '.join(sorted(unsupported))}. "
                f"UvicornServer only supports: "
                f"{', '.join(sorted(f.name for f in fields(self) if f.name != 'app'))}."
            )
        merged = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "app"}
        merged.update(overrides)
        uvicorn.run(self.app, **{k: v for k, v in merged.items() if v is not None})
