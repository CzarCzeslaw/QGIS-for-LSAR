"""Small bounded JSONL log; operational data is excluded from diagnostic bundles."""

import json
import logging
import platform
import sys
import zipfile
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .. import __version__


class JsonFormatter(logging.Formatter):
    def format(self, record):
        item = {
            "time": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
            "code": getattr(record, "code", ""),
        }
        if record.exc_info:
            item["traceback"] = self.formatException(record.exc_info)
        return json.dumps(item, ensure_ascii=False)


class Diagnostics:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger("sar_tools." + str(id(self)))
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        handler = RotatingFileHandler(
            self.directory / "sar.jsonl", maxBytes=1_000_000, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(JsonFormatter())
        self.logger.addHandler(handler)

    def event(self, event, code=""):
        self.logger.info(event, extra={"code": code})

    def exception(self, code):
        self.logger.exception("operation_failed", extra={"code": code})

    def export(self, destination, health):
        for handler in self.logger.handlers:
            handler.flush()
        report = {
            "plugin": __version__,
            "python": sys.version,
            "platform": platform.platform(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "health": health,
            "contains": (
                "Environment and technical logs only; no project, addresses, GPS or API keys."
            ),
        }
        # Exclusive creation prevents accidentally overwriting an existing report.
        with zipfile.ZipFile(destination, "x", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("environment.json", json.dumps(report, indent=2, ensure_ascii=False))
            for path in sorted(self.directory.glob("sar.jsonl*")):
                archive.write(path, "logs/" + path.name)

    def close(self):
        for handler in self.logger.handlers[:]:
            handler.close()
            self.logger.removeHandler(handler)
