"""Error log file: every WARNING and above from the web app, Celery worker and beat goes to LOG_DIR/errors.log.

The dashboard's Error log page (Owner only) reads it back with ``read_entries``. This module is imported
from settings (the filter), so it must not import Django models at module level.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

LINE_START = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ \| (\w+) +\| ([^|]+?) \| (.*)$")
READ_TAIL_BYTES = 3 * 1024 * 1024  # only the newest 3 MB is parsed, so a big file never slows the page


class SkipClientErrors(logging.Filter):
    """Drop routine 4xx request warnings (404 Not Found, 405, 403): they are visitors, not faults."""

    def filter(self, record):
        status = getattr(record, "status_code", None)
        if status is None and record.name in ("django.request", "django.server", "django.channels.server"):
            return record.levelno >= logging.ERROR
        return not (status and 400 <= int(status) < 500)


@dataclass
class Entry:
    when: str
    level: str
    logger: str
    message: str
    details: list = field(default_factory=list)

    @property
    def summary(self):
        """The last line of a traceback says what actually went wrong; show it next to the message."""
        for line in reversed(self.details):
            if line.strip() and not line.startswith(" "):
                return line.strip()
        return ""


def log_path():
    from django.conf import settings

    return Path(settings.LOG_DIR) / "errors.log"


def read_entries(path=None):
    """Parse the log file (newest READ_TAIL_BYTES) into entries, newest first."""
    path = path or log_path()
    if not path.exists():
        return []
    with path.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - READ_TAIL_BYTES))
        text = fh.read().decode("utf-8", errors="replace")
    if size > READ_TAIL_BYTES:
        text = text.split("\n", 1)[-1]  # drop the partial first line
    entries = []
    for line in text.splitlines():
        m = LINE_START.match(line)
        if m:
            entries.append(Entry(m[1], m[2], m[3].strip(), m[4]))
        elif entries:
            entries[-1].details.append(line)
    entries.reverse()
    return entries
