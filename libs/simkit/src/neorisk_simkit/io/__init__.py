"""Datasets on disk: the writer, the reader and the legacy fraud adapter."""

from neorisk_simkit.io.read import RunData, read
from neorisk_simkit.io.writer import DatasetExists, write

__all__ = ["DatasetExists", "RunData", "read", "write"]
