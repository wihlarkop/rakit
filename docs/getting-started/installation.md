# Installation

Rakit requires Python 3.12 or newer.

Install the facade package first:

```bash
pip install rakit
```

Add extras only for the capabilities your application needs. Public server extras use the short
adapter names:

```bash
pip install "rakit[uvicorn]"
pip install "rakit[granian]"
```

Other current extras include `sqlalchemy`, `auth-sqlalchemy`, and `storage-local`; `standard`
installs the reference SQLAlchemy/auth/local-storage stack with Uvicorn. The older
`server-uvicorn` extra remains a compatibility alias, but new documentation and install hints use
`uvicorn`. Check your lockfile after selecting extras; adapters are explicit and Rakit does not
silently install an ORM, authentication backend, storage implementation, or alternate server.

The facade keeps adapter-specific imports namespaced. For example:

```python
from rakit.server.granian import GranianServer
from rakit.server.uvicorn import UvicornServer
from rakit.storage import FileStorage
from rakit.storage.local import LocalStorage
```

For repository development:

```bash
uv sync --all-packages --dev --locked
uv run rakit --help
```

Before serving an application, validate its compiled graph:

```bash
uv run rakit check myapp:admin
uv run rakit routes myapp:admin
```

`rakit check` fails closed when required adapter capabilities or configuration contracts are
missing.
