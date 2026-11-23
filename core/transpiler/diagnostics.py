"""Source diagnostics shared by native transpiler stages."""

from dataclasses import dataclass
from enum import StrEnum


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A message located at a one-based source line and column."""

    message: str
    line: int
    column: int
    severity: Severity = Severity.ERROR
