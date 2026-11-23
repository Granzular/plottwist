"""A position-preserving scanner; it does not parse or translate MATLAB.

The lexical contract, apostrophe evidence, and scope limitations are documented
in docs/matlab-lexer.md. Lexical success does not establish valid MATLAB syntax.
"""

from dataclasses import dataclass

from .diagnostics import Diagnostic, Severity
from .tokens import KEYWORDS, OPERATORS, UNSUPPORTED_KEYWORDS, Token, TokenType


@dataclass(frozen=True, slots=True)
class LexResult:
    tokens: tuple[Token, ...]
    diagnostics: tuple[Diagnostic, ...]

    @property
    def has_errors(self) -> bool:
        return any(
            item.severity == Severity.ERROR for item in self.diagnostics
        )


_EXPRESSION_END_TYPES = frozenset({
    TokenType.IDENTIFIER, TokenType.NUMBER, TokenType.CHARACTER_VECTOR,
    TokenType.STRING_SCALAR, TokenType.RPAREN, TokenType.RBRACKET,
    TokenType.RBRACE, TokenType.CONJUGATE_TRANSPOSE,
    TokenType.NONCONJUGATE_TRANSPOSE, TokenType.END,
})
_HORIZONTAL_WHITESPACE = " \t\f\v"


def _is_digit(character: str) -> bool:
    return "0" <= character <= "9"


def _is_letter(character: str) -> bool:
    return "a" <= character <= "z" or "A" <= character <= "Z"


def _is_identifier_part(character: str) -> bool:
    return _is_letter(character) or _is_digit(character) or character == "_"


def tokenize(source: str) -> LexResult:
    """Scan source into immutable tokens and diagnostics, always ending in EOF.

    Malformed MATLAB is reported in the result. A non-string argument is an
    API usage error and raises TypeError. Empty source is valid lexical input.
    This function needs only the Python standard library and package modules.
    """
    if not isinstance(source, str):
        raise TypeError("MATLAB source must be a string.")
    return _Scanner(source).scan()


class _Scanner:
    def __init__(self, source: str):
        self.source = source
        self.index = 0
        self.line = 1
        self.column = 1
        self.line_start = 0
        self.tokens: list[Token] = []
        self.diagnostics: list[Diagnostic] = []
        self.previous_end = 0
        self.block_starts: list[tuple[int, int]] = []

    def scan(self) -> LexResult:
        while self.index < len(self.source):
            character = self._peek()
            start, line, column = self.index, self.line, self.column
            if character in "\r\n":
                self._advance()
                self._emit(TokenType.NEWLINE, start, line, column)
            elif character in _HORIZONTAL_WHITESPACE:
                self._advance()
            elif self.block_starts:
                self._block_comment_line()
            elif character == "%":
                self._comment(start, line, column)
            elif self.source.startswith("...", self.index):
                self._continuation(start, line, column)
            elif _is_letter(character):
                self._identifier(start, line, column)
            elif _is_digit(character) or (
                character == "." and _is_digit(self._peek(1))
            ):
                self._number(start, line, column)
            elif character == '"':
                self._literal(TokenType.STRING_SCALAR, start, line, column)
            elif character == "'" and not self._is_transpose():
                self._literal(TokenType.CHARACTER_VECTOR, start, line, column)
            else:
                self._operator_or_invalid(start, line, column)

        for line, column in self.block_starts:
            self._error("Unterminated block comment.", line, column)
        self.tokens.append(Token(TokenType.EOF, "", self.line, self.column))
        return LexResult(tuple(self.tokens), tuple(self.diagnostics))

    def _peek(self, offset: int = 0) -> str:
        index = self.index + offset
        return self.source[index] if index < len(self.source) else ""

    def _advance(self) -> None:
        character = self.source[self.index]
        self.index += 1
        if character == "\r":
            if self._peek() == "\n":
                self.index += 1
            self.line += 1
            self.column = 1
            self.line_start = self.index
        elif character == "\n":
            self.line += 1
            self.column = 1
            self.line_start = self.index
        else:
            self.column += 1

    def _emit(
        self, kind: TokenType, start: int, line: int, column: int,
    ) -> None:
        self.tokens.append(
            Token(kind, self.source[start:self.index], line, column)
        )
        self.previous_end = self.index

    def _error(self, message: str, line: int, column: int) -> None:
        self.diagnostics.append(Diagnostic(message, line, column))

    def _skip_line(self) -> None:
        while self._peek() and self._peek() not in "\r\n":
            self._advance()

    def _is_block_marker(self, marker: str) -> bool:
        if not self.source.startswith(marker, self.index):
            return False
        prefix = self.source[self.line_start:self.index]
        if prefix.strip(_HORIZONTAL_WHITESPACE):
            return False
        end = self.index + len(marker)
        while (
            end < len(self.source)
            and self.source[end] in _HORIZONTAL_WHITESPACE
        ):
            end += 1
        return end == len(self.source) or self.source[end] in "\r\n"

    def _comment(self, start: int, line: int, column: int) -> None:
        if self._is_block_marker("%{"):
            self.block_starts.append((line, column))
        elif self._is_block_marker("%}"):
            self._advance()
            self._advance()
            self._emit(TokenType.INVALID, start, line, column)
            self._error(
                "Block comment closing marker has no opening marker.",
                line, column,
            )
        self._skip_line()

    def _block_comment_line(self) -> None:
        if self._is_block_marker("%{"):
            self.block_starts.append((self.line, self.column))
        elif self._is_block_marker("%}"):
            self.block_starts.pop()
        self._skip_line()

    def _continuation(self, start: int, line: int, column: int) -> None:
        self._skip_line()
        if self._peek():
            self._advance()
        else:
            self._emit(TokenType.INVALID, start, line, column)
            self._error(
                "Line continuation requires a following physical line.",
                line, column,
            )

    def _identifier(self, start: int, line: int, column: int) -> None:
        while _is_identifier_part(self._peek()):
            self._advance()
        word = self.source[start:self.index]
        if word in UNSUPPORTED_KEYWORDS:
            self._emit(TokenType.INVALID, start, line, column)
            self._error(
                f"MATLAB keyword {word!r} is outside the supported subset.",
                line, column,
            )
        else:
            self._emit(
                KEYWORDS.get(word, TokenType.IDENTIFIER), start, line, column,
            )

    def _dot_begins_operator(self) -> bool:
        return self.source.startswith("...", self.index) or self._peek(1) in (
            "*", "/", "^", "'", "\\",
        )

    def _number(self, start: int, line: int, column: int) -> None:
        while _is_digit(self._peek()):
            self._advance()
        if self._peek() == "." and not self._dot_begins_operator():
            self._advance()
            while _is_digit(self._peek()):
                self._advance()

        message = None
        if self._peek() in ("e", "E"):
            self._advance()
            if self._peek() in ("+", "-"):
                self._advance()
            if not _is_digit(self._peek()):
                message = "Scientific notation requires exponent digits."
            while _is_digit(self._peek()):
                self._advance()

        suffix_start = self.index
        while _is_identifier_part(self._peek()) or (
            self._peek() == "." and _is_digit(self._peek(1))
        ):
            self._advance()
        if self.index != suffix_start:
            suffix = self.source[suffix_start:self.index]
            if message is None:
                if suffix in ("i", "j"):
                    message = "Imaginary numeric literals are not supported."
                elif self.source[start:self.index].lower().startswith(
                    ("0x", "0b")
                ):
                    message = (
                        "Hexadecimal and binary numeric literals "
                        "are not supported."
                    )
                else:
                    message = "Malformed numeric literal."

        if message:
            self._emit(TokenType.INVALID, start, line, column)
            self._error(message, line, column)
        else:
            self._emit(TokenType.NUMBER, start, line, column)

    def _is_transpose(self) -> bool:
        # A whitespace-separated bare quote opens a character vector, even
        # after an identifier. The contiguous .' operator is handled separately.
        return bool(
            self.tokens
            and self.tokens[-1].type in _EXPRESSION_END_TYPES
            and self.previous_end == self.index
        )

    def _literal(
        self, kind: TokenType, start: int, line: int, column: int,
    ) -> None:
        quote = self._peek()
        self._advance()
        while self._peek() and self._peek() not in "\r\n":
            if self._peek() == quote:
                self._advance()
                if self._peek() == quote:
                    self._advance()
                else:
                    self._emit(kind, start, line, column)
                    return
            else:
                self._advance()
        self._emit(TokenType.INVALID, start, line, column)
        name = (
            "character vector"
            if kind == TokenType.CHARACTER_VECTOR
            else "string scalar"
        )
        self._error(
            f"Unterminated {name}; "
            "literals must close on the same physical line.",
            line, column,
        )

    def _operator_or_invalid(self, start: int, line: int, column: int) -> None:
        pair = self.source[self.index:self.index + 2]
        if len(pair) == 2 and pair in OPERATORS:
            self._advance()
            self._advance()
            self._emit(OPERATORS[pair], start, line, column)
        elif pair == ".\\":
            self._advance()
            self._advance()
            self._emit(TokenType.INVALID, start, line, column)
            self._error(
                "Element-wise left division is not supported.", line, column,
            )
        else:
            character = self._peek()
            self._advance()
            kind = OPERATORS.get(character, TokenType.INVALID)
            self._emit(kind, start, line, column)
            if kind == TokenType.INVALID:
                self._error(
                    f"Invalid or unsupported character {character!r}.",
                    line, column,
                )
