from rakit import run

from .app import admin

if __name__ == "__main__":
    run(admin, server="uvicorn", host="127.0.0.1", port=8000, reload=False)
