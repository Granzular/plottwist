"""Independent native MATLAB transpiler components.

Milestone 1 exposes lexical analysis only. ``tokenize(source)`` returns a
``LexResult`` containing ordered tokens (including EOF) and diagnostics.
Consumers must check ``result.has_errors`` before using the token stream.
The future translation entry point will retain the application's result
contract; lexical results do not contain generated Python or invoke services.
"""

from .diagnostics import Diagnostic, Severity
from .lexer import LexResult, tokenize
from .tokens import Token, TokenType

__all__ = [
    "Diagnostic",
    "LexResult",
    "Severity",
    "Token",
    "TokenType",
    "tokenize",
]
