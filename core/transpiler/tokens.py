"""Token definitions for the coursework MATLAB subset."""

from dataclasses import dataclass
from enum import StrEnum


class TokenType(StrEnum):
    IDENTIFIER = "IDENTIFIER"
    NUMBER = "NUMBER"
    CHARACTER_VECTOR = "CHARACTER_VECTOR"
    STRING_SCALAR = "STRING_SCALAR"

    IF = "IF"
    ELSE = "ELSE"
    ELSEIF = "ELSEIF"
    END = "END"
    FOR = "FOR"
    WHILE = "WHILE"
    BREAK = "BREAK"
    CONTINUE = "CONTINUE"
    RETURN = "RETURN"

    PLUS = "PLUS"
    MINUS = "MINUS"
    MULTIPLY = "MULTIPLY"
    DIVIDE = "DIVIDE"
    POWER = "POWER"
    ELEMENTWISE_MULTIPLY = "ELEMENTWISE_MULTIPLY"
    ELEMENTWISE_DIVIDE = "ELEMENTWISE_DIVIDE"
    ELEMENTWISE_POWER = "ELEMENTWISE_POWER"

    EQUAL = "EQUAL"
    NOT_EQUAL = "NOT_EQUAL"
    LESS_THAN = "LESS_THAN"
    GREATER_THAN = "GREATER_THAN"
    LESS_EQUAL = "LESS_EQUAL"
    GREATER_EQUAL = "GREATER_EQUAL"
    AND = "AND"
    OR = "OR"
    NOT = "NOT"
    SHORT_CIRCUIT_AND = "SHORT_CIRCUIT_AND"
    SHORT_CIRCUIT_OR = "SHORT_CIRCUIT_OR"
    ASSIGN = "ASSIGN"
    CONJUGATE_TRANSPOSE = "CONJUGATE_TRANSPOSE"
    NONCONJUGATE_TRANSPOSE = "NONCONJUGATE_TRANSPOSE"

    LPAREN = "LPAREN"
    RPAREN = "RPAREN"
    LBRACKET = "LBRACKET"
    RBRACKET = "RBRACKET"
    LBRACE = "LBRACE"
    RBRACE = "RBRACE"
    COMMA = "COMMA"
    SEMICOLON = "SEMICOLON"
    COLON = "COLON"
    NEWLINE = "NEWLINE"
    INVALID = "INVALID"
    EOF = "EOF"


@dataclass(frozen=True, slots=True)
class Token:
    """A raw source lexeme and its one-based starting position.

    Literal lexemes include their delimiters and doubled quote escapes. No
    unescaping, numeric conversion, or whitespace normalization occurs here.
    EOF has an empty lexeme and points immediately after the physical source.
    """

    type: TokenType
    lexeme: str
    line: int
    column: int


KEYWORDS = {
    "if": TokenType.IF,
    "else": TokenType.ELSE,
    "elseif": TokenType.ELSEIF,
    "end": TokenType.END,
    "for": TokenType.FOR,
    "while": TokenType.WHILE,
    "break": TokenType.BREAK,
    "continue": TokenType.CONTINUE,
    "return": TokenType.RETURN,
}

# Reserved words must not silently become ordinary function/variable names.
# These constructs are outside the initial coursework subset.
UNSUPPORTED_KEYWORDS = frozenset({
    "case", "catch", "classdef", "function", "global", "otherwise", "parfor",
    "persistent", "spmd", "switch", "try",
})

OPERATORS = {
    "+": TokenType.PLUS,
    "-": TokenType.MINUS,
    "*": TokenType.MULTIPLY,
    "/": TokenType.DIVIDE,
    "^": TokenType.POWER,
    ".*": TokenType.ELEMENTWISE_MULTIPLY,
    "./": TokenType.ELEMENTWISE_DIVIDE,
    ".^": TokenType.ELEMENTWISE_POWER,
    "==": TokenType.EQUAL,
    "~=": TokenType.NOT_EQUAL,
    "<": TokenType.LESS_THAN,
    ">": TokenType.GREATER_THAN,
    "<=": TokenType.LESS_EQUAL,
    ">=": TokenType.GREATER_EQUAL,
    "&": TokenType.AND,
    "|": TokenType.OR,
    "~": TokenType.NOT,
    "&&": TokenType.SHORT_CIRCUIT_AND,
    "||": TokenType.SHORT_CIRCUIT_OR,
    "=": TokenType.ASSIGN,
    "'": TokenType.CONJUGATE_TRANSPOSE,
    ".'": TokenType.NONCONJUGATE_TRANSPOSE,
    "(": TokenType.LPAREN,
    ")": TokenType.RPAREN,
    "[": TokenType.LBRACKET,
    "]": TokenType.RBRACKET,
    "{": TokenType.LBRACE,
    "}": TokenType.RBRACE,
    ",": TokenType.COMMA,
    ";": TokenType.SEMICOLON,
    ":": TokenType.COLON,
}
