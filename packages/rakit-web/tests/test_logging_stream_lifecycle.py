import io
import logging
import sys

import structlog

from rakit_web.logging import configure_logging


def test_configured_loggers_follow_replaced_stderr(monkeypatch) -> None:
    first_stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", first_stream)
    configure_logging(debug=False)

    first_stream.close()
    replacement_stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", replacement_stream)

    structlog.get_logger("rakit_web.test").info("structlog.after.stderr.replacement")
    logging.getLogger("rakit_web.test").warning("stdlib.after.stderr.replacement")

    output = replacement_stream.getvalue()
    assert "structlog.after.stderr.replacement" in output
    assert "stdlib.after.stderr.replacement" in output
