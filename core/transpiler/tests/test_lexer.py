"""Run with Django's test runner or python -m unittest; no settings needed."""

from unittest import TestCase

from core.transpiler import Diagnostic, Severity, Token, TokenType, tokenize


T = TokenType


class LexerTests(TestCase):
    def assert_tokens(self, source, expected):
        result = tokenize(source)
        self.assertEqual(result.diagnostics, ())
        self.assertFalse(result.has_errors)
        self.assertEqual(result.tokens, tuple(Token(*row) for row in expected))
        return result

    def assert_pairs(self, source, expected):
        result = tokenize(source)
        self.assertEqual(result.diagnostics, ())
        self.assertFalse(result.has_errors)
        self.assertEqual(
            [(item.type, item.lexeme) for item in result.tokens[:-1]],
            expected,
        )
        self.assertEqual(result.tokens[-1].type, T.EOF)
        return result

    def test_simple_assignment(self):
        self.assert_tokens("x = 10;", [
            (T.IDENTIFIER, "x", 1, 1),
            (T.ASSIGN, "=", 1, 3),
            (T.NUMBER, "10", 1, 5),
            (T.SEMICOLON, ";", 1, 7),
            (T.EOF, "", 1, 8),
        ])

    def test_multiple_statements_on_one_line(self):
        self.assert_tokens("a=1;b=2,c=3;", [
            (T.IDENTIFIER, "a", 1, 1), (T.ASSIGN, "=", 1, 2),
            (T.NUMBER, "1", 1, 3), (T.SEMICOLON, ";", 1, 4),
            (T.IDENTIFIER, "b", 1, 5), (T.ASSIGN, "=", 1, 6),
            (T.NUMBER, "2", 1, 7), (T.COMMA, ",", 1, 8),
            (T.IDENTIFIER, "c", 1, 9), (T.ASSIGN, "=", 1, 10),
            (T.NUMBER, "3", 1, 11), (T.SEMICOLON, ";", 1, 12),
            (T.EOF, "", 1, 13),
        ])

    def test_multiline_source_and_blank_lines(self):
        self.assert_tokens("a = 1;\n\n  b=2\n", [
            (T.IDENTIFIER, "a", 1, 1), (T.ASSIGN, "=", 1, 3),
            (T.NUMBER, "1", 1, 5), (T.SEMICOLON, ";", 1, 6),
            (T.NEWLINE, "\n", 1, 7), (T.NEWLINE, "\n", 2, 1),
            (T.IDENTIFIER, "b", 3, 3), (T.ASSIGN, "=", 3, 4),
            (T.NUMBER, "2", 3, 5), (T.NEWLINE, "\n", 3, 6),
            (T.EOF, "", 4, 1),
        ])

    def test_lf_crlf_cr_and_tab_positions(self):
        self.assert_tokens("a\r\n\tb\rc\n", [
            (T.IDENTIFIER, "a", 1, 1), (T.NEWLINE, "\r\n", 1, 2),
            (T.IDENTIFIER, "b", 2, 2), (T.NEWLINE, "\r", 2, 3),
            (T.IDENTIFIER, "c", 3, 1), (T.NEWLINE, "\n", 3, 2),
            (T.EOF, "", 4, 1),
        ])

    def test_numeric_literals(self):
        self.assert_tokens("10 3.14 .5 1e-3 2.5E+4 1. 1.e2", [
            (T.NUMBER, "10", 1, 1), (T.NUMBER, "3.14", 1, 4),
            (T.NUMBER, ".5", 1, 9), (T.NUMBER, "1e-3", 1, 12),
            (T.NUMBER, "2.5E+4", 1, 17), (T.NUMBER, "1.", 1, 24),
            (T.NUMBER, "1.e2", 1, 27), (T.EOF, "", 1, 31),
        ])

    def test_numeric_signs_are_operators(self):
        self.assert_pairs("n=-10:+.5;", [
            (T.IDENTIFIER, "n"), (T.ASSIGN, "="), (T.MINUS, "-"),
            (T.NUMBER, "10"), (T.COLON, ":"), (T.PLUS, "+"),
            (T.NUMBER, ".5"), (T.SEMICOLON, ";"),
        ])

    def test_arithmetic_and_elementwise_operators(self):
        self.assert_tokens("+ - * / ^ .* ./ .^", [
            (T.PLUS, "+", 1, 1), (T.MINUS, "-", 1, 3),
            (T.MULTIPLY, "*", 1, 5), (T.DIVIDE, "/", 1, 7),
            (T.POWER, "^", 1, 9),
            (T.ELEMENTWISE_MULTIPLY, ".*", 1, 11),
            (T.ELEMENTWISE_DIVIDE, "./", 1, 14),
            (T.ELEMENTWISE_POWER, ".^", 1, 17),
            (T.EOF, "", 1, 19),
        ])

    def test_comparison_logical_and_assignment_operators(self):
        self.assert_tokens("== ~= < > <= >= & | ~ && || =", [
            (T.EQUAL, "==", 1, 1), (T.NOT_EQUAL, "~=", 1, 4),
            (T.LESS_THAN, "<", 1, 7), (T.GREATER_THAN, ">", 1, 9),
            (T.LESS_EQUAL, "<=", 1, 11), (T.GREATER_EQUAL, ">=", 1, 14),
            (T.AND, "&", 1, 17), (T.OR, "|", 1, 19),
            (T.NOT, "~", 1, 21), (T.SHORT_CIRCUIT_AND, "&&", 1, 23),
            (T.SHORT_CIRCUIT_OR, "||", 1, 26), (T.ASSIGN, "=", 1, 29),
            (T.EOF, "", 1, 30),
        ])

    def test_single_character_operators_at_eof(self):
        for source, kind in (
            ("+", T.PLUS), ("=", T.ASSIGN), ("~", T.NOT),
            ("[", T.LBRACKET), (")", T.RPAREN), (":", T.COLON),
        ):
            with self.subTest(source=source):
                self.assert_tokens(source, [
                    (kind, source, 1, 1), (T.EOF, "", 1, 2),
                ])

    def test_dots_after_numbers_are_not_swallowed(self):
        self.assert_tokens("1.*x 2./x 3.^x 4.'", [
            (T.NUMBER, "1", 1, 1),
            (T.ELEMENTWISE_MULTIPLY, ".*", 1, 2),
            (T.IDENTIFIER, "x", 1, 4),
            (T.NUMBER, "2", 1, 6),
            (T.ELEMENTWISE_DIVIDE, "./", 1, 7),
            (T.IDENTIFIER, "x", 1, 9),
            (T.NUMBER, "3", 1, 11),
            (T.ELEMENTWISE_POWER, ".^", 1, 12),
            (T.IDENTIFIER, "x", 1, 14),
            (T.NUMBER, "4", 1, 16),
            (T.NONCONJUGATE_TRANSPOSE, ".'", 1, 17),
            (T.EOF, "", 1, 19),
        ])

    def test_identifiers_and_case_sensitive_keywords(self):
        self.assert_pairs(
            "if else elseif end for while break continue return "
            "ifft IF sample_1",
            [
                (T.IF, "if"), (T.ELSE, "else"), (T.ELSEIF, "elseif"),
                (T.END, "end"), (T.FOR, "for"), (T.WHILE, "while"),
                (T.BREAK, "break"), (T.CONTINUE, "continue"),
                (T.RETURN, "return"), (T.IDENTIFIER, "ifft"),
                (T.IDENTIFIER, "IF"), (T.IDENTIFIER, "sample_1"),
            ],
        )

    def test_function_and_variable_names_are_not_resolved(self):
        self.assert_pairs("unknown_function(unknown_variable);", [
            (T.IDENTIFIER, "unknown_function"), (T.LPAREN, "("),
            (T.IDENTIFIER, "unknown_variable"), (T.RPAREN, ")"),
            (T.SEMICOLON, ";"),
        ])

    def test_parentheses_matrices_vectors_and_cells(self):
        self.assert_pairs("y=x(1:2:end); M=[1,2;3,4]; C={x,y};", [
            (T.IDENTIFIER, "y"), (T.ASSIGN, "="), (T.IDENTIFIER, "x"),
            (T.LPAREN, "("), (T.NUMBER, "1"), (T.COLON, ":"),
            (T.NUMBER, "2"), (T.COLON, ":"), (T.END, "end"),
            (T.RPAREN, ")"), (T.SEMICOLON, ";"),
            (T.IDENTIFIER, "M"), (T.ASSIGN, "="), (T.LBRACKET, "["),
            (T.NUMBER, "1"), (T.COMMA, ","), (T.NUMBER, "2"),
            (T.SEMICOLON, ";"), (T.NUMBER, "3"), (T.COMMA, ","),
            (T.NUMBER, "4"), (T.RBRACKET, "]"), (T.SEMICOLON, ";"),
            (T.IDENTIFIER, "C"), (T.ASSIGN, "="), (T.LBRACE, "{"),
            (T.IDENTIFIER, "x"), (T.COMMA, ","), (T.IDENTIFIER, "y"),
            (T.RBRACE, "}"), (T.SEMICOLON, ";"),
        ])

    def test_matrix_whitespace_and_row_newlines_remain_locatable(self):
        self.assert_tokens("[1 2\n 3 4]", [
            (T.LBRACKET, "[", 1, 1), (T.NUMBER, "1", 1, 2),
            (T.NUMBER, "2", 1, 4), (T.NEWLINE, "\n", 1, 5),
            (T.NUMBER, "3", 2, 2), (T.NUMBER, "4", 2, 4),
            (T.RBRACKET, "]", 2, 5), (T.EOF, "", 2, 6),
        ])

    def test_character_vectors_and_string_scalars_preserve_contents(self):
        source = (
            r"msg = 'It''s 100% ...\literal'; "
            's = "say ""hi""";'
        )
        self.assert_pairs(source, [
            (T.IDENTIFIER, "msg"), (T.ASSIGN, "="),
            (T.CHARACTER_VECTOR, r"'It''s 100% ...\literal'"),
            (T.SEMICOLON, ";"), (T.IDENTIFIER, "s"), (T.ASSIGN, "="),
            (T.STRING_SCALAR, '"say ""hi"""'), (T.SEMICOLON, ";"),
        ])

    def test_empty_literals(self):
        self.assert_tokens("'' \"\"", [
            (T.CHARACTER_VECTOR, "''", 1, 1),
            (T.STRING_SCALAR, '""', 1, 4),
            (T.EOF, "", 1, 6),
        ])

    def test_quote_types_in_expressions(self):
        self.assert_pairs("""a='hi';b=a';c=a.';d=(a+b)';e=[1 2]';""", [
            (T.IDENTIFIER, "a"), (T.ASSIGN, "="),
            (T.CHARACTER_VECTOR, "'hi'"), (T.SEMICOLON, ";"),
            (T.IDENTIFIER, "b"), (T.ASSIGN, "="), (T.IDENTIFIER, "a"),
            (T.CONJUGATE_TRANSPOSE, "'"), (T.SEMICOLON, ";"),
            (T.IDENTIFIER, "c"), (T.ASSIGN, "="), (T.IDENTIFIER, "a"),
            (T.NONCONJUGATE_TRANSPOSE, ".'"), (T.SEMICOLON, ";"),
            (T.IDENTIFIER, "d"), (T.ASSIGN, "="), (T.LPAREN, "("),
            (T.IDENTIFIER, "a"), (T.PLUS, "+"), (T.IDENTIFIER, "b"),
            (T.RPAREN, ")"), (T.CONJUGATE_TRANSPOSE, "'"),
            (T.SEMICOLON, ";"), (T.IDENTIFIER, "e"), (T.ASSIGN, "="),
            (T.LBRACKET, "["), (T.NUMBER, "1"), (T.NUMBER, "2"),
            (T.RBRACKET, "]"), (T.CONJUGATE_TRANSPOSE, "'"),
            (T.SEMICOLON, ";"),
        ])

    def test_transposes_after_values_and_other_transposes(self):
        self.assert_pairs('2\' {x}\' "x"\' A\'\' A.\'\'', [
            (T.NUMBER, "2"), (T.CONJUGATE_TRANSPOSE, "'"),
            (T.LBRACE, "{"), (T.IDENTIFIER, "x"), (T.RBRACE, "}"),
            (T.CONJUGATE_TRANSPOSE, "'"), (T.STRING_SCALAR, '"x"'),
            (T.CONJUGATE_TRANSPOSE, "'"), (T.IDENTIFIER, "A"),
            (T.CONJUGATE_TRANSPOSE, "'"), (T.CONJUGATE_TRANSPOSE, "'"),
            (T.IDENTIFIER, "A"), (T.NONCONJUGATE_TRANSPOSE, ".'"),
            (T.CONJUGATE_TRANSPOSE, "'"),
        ])

    def test_whitespace_separated_quotes_open_character_vectors(self):
        self.assert_tokens("['a' 'b']; A 'value'", [
            (T.LBRACKET, "[", 1, 1),
            (T.CHARACTER_VECTOR, "'a'", 1, 2),
            (T.CHARACTER_VECTOR, "'b'", 1, 6),
            (T.RBRACKET, "]", 1, 9), (T.SEMICOLON, ";", 1, 10),
            (T.IDENTIFIER, "A", 1, 12),
            (T.CHARACTER_VECTOR, "'value'", 1, 14),
            (T.EOF, "", 1, 21),
        ])

    def test_whitespace_before_a_bare_quote_starts_a_character_vector(self):
        for source, column in (("A '", 3), ("A\t'", 3), ("x = A '", 7)):
            with self.subTest(source=source):
                result = tokenize(source)
                self.assertEqual(
                    result.tokens[-2], Token(T.INVALID, "'", 1, column),
                )
                self.assertEqual(
                    result.tokens[-1], Token(T.EOF, "", 1, len(source) + 1),
                )
                self.assertTrue(result.has_errors)
                self.assertEqual(len(result.diagnostics), 1)
                diagnostic = result.diagnostics[0]
                self.assertEqual(
                    (diagnostic.line, diagnostic.column, diagnostic.severity),
                    (1, column, Severity.ERROR),
                )
                self.assertIn(
                    "Unterminated character vector", diagnostic.message,
                )

    def test_transpose_whitespace_and_physical_positions(self):
        for source, kind, lexeme, column in (
            ("A'", T.CONJUGATE_TRANSPOSE, "'", 2),
            ("A.'", T.NONCONJUGATE_TRANSPOSE, ".'", 2),
            ("A .'", T.NONCONJUGATE_TRANSPOSE, ".'", 3),
            ("A\t.'", T.NONCONJUGATE_TRANSPOSE, ".'", 3),
        ):
            for prefix in ("", "x = "):
                with self.subTest(source=prefix + source):
                    expected = []
                    if prefix:
                        expected.extend([
                            (T.IDENTIFIER, "x", 1, 1),
                            (T.ASSIGN, "=", 1, 3),
                        ])
                    expected.extend([
                        (T.IDENTIFIER, "A", 1, len(prefix) + 1),
                        (kind, lexeme, 1, len(prefix) + column),
                        (T.EOF, "", 1, len(prefix + source) + 1),
                    ])
                    # Tokenization does not decide command-form syntax for
                    # the standalone whitespace-separated identifier case.
                    self.assert_tokens(prefix + source, expected)

    def test_whitespace_inside_dot_quote_is_not_normalized(self):
        for source, dot_column, quote_column in (
            ("A. '", 2, 4), ("A . '", 3, 5),
        ):
            with self.subTest(source=source):
                result = tokenize(source)
                self.assertTrue(result.has_errors)
                self.assertEqual(result.tokens, (
                    Token(T.IDENTIFIER, "A", 1, 1),
                    Token(T.INVALID, ".", 1, dot_column),
                    Token(T.INVALID, "'", 1, quote_column),
                    Token(T.EOF, "", 1, len(source) + 1),
                ))
                self.assertEqual(
                    [(item.line, item.column) for item in result.diagnostics],
                    [(1, dot_column), (1, quote_column)],
                )

    def test_literals_at_expression_start_and_assignment(self):
        for source, kind in (
            ("'A'", T.CHARACTER_VECTOR),
            ("'hello'", T.CHARACTER_VECTOR),
            ('"hello"', T.STRING_SCALAR),
            ("'It''s'", T.CHARACTER_VECTOR),
            ('"say ""hi"""', T.STRING_SCALAR),
        ):
            for prefix in ("", "x = "):
                with self.subTest(source=prefix + source):
                    result = tokenize(prefix + source)
                    self.assertFalse(result.has_errors)
                    self.assertEqual(result.diagnostics, ())
                    self.assertEqual(
                        result.tokens[-2],
                        Token(kind, source, 1, len(prefix) + 1),
                    )

    def test_indexed_cell_value_can_precede_transpose(self):
        self.assert_tokens("x = C{1}'", [
            (T.IDENTIFIER, "x", 1, 1), (T.ASSIGN, "=", 1, 3),
            (T.IDENTIFIER, "C", 1, 5), (T.LBRACE, "{", 1, 6),
            (T.NUMBER, "1", 1, 7), (T.RBRACE, "}", 1, 8),
            (T.CONJUGATE_TRANSPOSE, "'", 1, 9), (T.EOF, "", 1, 10),
        ])

    def test_continuation_does_not_join_a_bare_quote_to_its_operand(self):
        for newline in ("\n", "\r\n", "\r"):
            with self.subTest(newline=newline):
                result = tokenize("A..." + newline + "'")
                self.assertEqual(result.tokens, (
                    Token(T.IDENTIFIER, "A", 1, 1),
                    Token(T.INVALID, "'", 2, 1), Token(T.EOF, "", 2, 2),
                ))
                self.assertTrue(result.has_errors)
                self.assertEqual(len(result.diagnostics), 1)
                self.assertEqual(
                    (result.diagnostics[0].line, result.diagnostics[0].column),
                    (2, 1),
                )

    def test_continued_nonconjugate_transpose_keeps_physical_position(self):
        self.assert_tokens("x = A... ignored\r\n  .'", [
            (T.IDENTIFIER, "x", 1, 1), (T.ASSIGN, "=", 1, 3),
            (T.IDENTIFIER, "A", 1, 5),
            (T.NONCONJUGATE_TRANSPOSE, ".'", 2, 3),
            (T.EOF, "", 2, 5),
        ])

    def test_quote_after_a_statement_newline_starts_a_literal(self):
        self.assert_tokens("A\n'next'", [
            (T.IDENTIFIER, "A", 1, 1), (T.NEWLINE, "\n", 1, 2),
            (T.CHARACTER_VECTOR, "'next'", 2, 1), (T.EOF, "", 2, 7),
        ])

    def test_unterminated_literals_at_eof(self):
        for source, name in (
            ("'abc", "character vector"), ('"abc', "string scalar"),
        ):
            with self.subTest(source=source):
                result = tokenize("  " + source)
                self.assertEqual(result.tokens, (
                    Token(T.INVALID, source, 1, 3),
                    Token(T.EOF, "", 1, 7),
                ))
                self.assertTrue(result.has_errors)
                self.assertEqual(result.diagnostics, (
                    Diagnostic(
                        f"Unterminated {name}; "
                        "literals must close on the same physical line.",
                        1, 3, Severity.ERROR,
                    ),
                ))

    def test_unterminated_literals_recover_before_physical_newlines(self):
        for quote in ("'", '"'):
            for newline in ("\n", "\r\n", "\r"):
                with self.subTest(quote=quote, newline=newline):
                    result = tokenize(f"x={quote}bad{newline}y=2;")
                    self.assertEqual(result.tokens, (
                        Token(T.IDENTIFIER, "x", 1, 1),
                        Token(T.ASSIGN, "=", 1, 2),
                        Token(T.INVALID, quote + "bad", 1, 3),
                        Token(T.NEWLINE, newline, 1, 7),
                        Token(T.IDENTIFIER, "y", 2, 1),
                        Token(T.ASSIGN, "=", 2, 2),
                        Token(T.NUMBER, "2", 2, 3),
                        Token(T.SEMICOLON, ";", 2, 4),
                        Token(T.EOF, "", 2, 5),
                    ))
                    self.assertEqual(len(result.diagnostics), 1)
                    self.assertEqual(
                        (
                            result.diagnostics[0].line,
                            result.diagnostics[0].column,
                        ),
                        (1, 3),
                    )

    def test_line_comments_and_positions(self):
        self.assert_tokens("x=1; % not tokens @ ...\n% only comment\n  y=2;", [
            (T.IDENTIFIER, "x", 1, 1), (T.ASSIGN, "=", 1, 2),
            (T.NUMBER, "1", 1, 3), (T.SEMICOLON, ";", 1, 4),
            (T.NEWLINE, "\n", 1, 24),
            (T.NEWLINE, "\n", 2, 15),
            (T.IDENTIFIER, "y", 3, 3), (T.ASSIGN, "=", 3, 4),
            (T.NUMBER, "2", 3, 5), (T.SEMICOLON, ";", 3, 6),
            (T.EOF, "", 3, 7),
        ])

    def test_comment_at_eof(self):
        self.assert_tokens("% @ ' ...", [(T.EOF, "", 1, 10)])

    def test_block_comments_nested_markers_and_positions(self):
        source = "x=1;\n%{\nignored @ '...'\n  %{\nmore code\n  %}\n%}\ny=2;"
        self.assert_tokens(source, [
            (T.IDENTIFIER, "x", 1, 1), (T.ASSIGN, "=", 1, 2),
            (T.NUMBER, "1", 1, 3), (T.SEMICOLON, ";", 1, 4),
            (T.NEWLINE, "\n", 1, 5), (T.NEWLINE, "\n", 2, 3),
            (T.NEWLINE, "\n", 3, 16), (T.NEWLINE, "\n", 4, 5),
            (T.NEWLINE, "\n", 5, 10), (T.NEWLINE, "\n", 6, 5),
            (T.NEWLINE, "\n", 7, 3), (T.IDENTIFIER, "y", 8, 1),
            (T.ASSIGN, "=", 8, 2), (T.NUMBER, "2", 8, 3),
            (T.SEMICOLON, ";", 8, 4), (T.EOF, "", 8, 5),
        ])

    def test_inline_block_marker_is_an_ordinary_line_comment(self):
        self.assert_tokens("x=1; %{ ordinary line comment\nz=2;", [
            (T.IDENTIFIER, "x", 1, 1), (T.ASSIGN, "=", 1, 2),
            (T.NUMBER, "1", 1, 3), (T.SEMICOLON, ";", 1, 4),
            (T.NEWLINE, "\n", 1, 30), (T.IDENTIFIER, "z", 2, 1),
            (T.ASSIGN, "=", 2, 2), (T.NUMBER, "2", 2, 3),
            (T.SEMICOLON, ";", 2, 4), (T.EOF, "", 2, 5),
        ])

    def test_unterminated_block_comment_has_opening_position(self):
        result = tokenize("  %{\nbody @ '")
        self.assertEqual(result.diagnostics, (
            Diagnostic("Unterminated block comment.", 1, 3, Severity.ERROR),
        ))
        self.assertTrue(result.has_errors)
        self.assertEqual(result.tokens, (
            Token(T.NEWLINE, "\n", 1, 5), Token(T.EOF, "", 2, 9),
        ))

    def test_unmatched_block_comment_closer_is_diagnosed(self):
        result = tokenize("  %}\nz=1")
        self.assertEqual(result.tokens[0], Token(T.INVALID, "%}", 1, 3))
        self.assertEqual(result.diagnostics, (
            Diagnostic(
                "Block comment closing marker has no opening marker.",
                1, 3, Severity.ERROR,
            ),
        ))
        self.assertTrue(result.has_errors)
        self.assertEqual(result.tokens[-1], Token(T.EOF, "", 2, 4))

    def test_line_continuations_suppress_newlines_and_trailing_text(self):
        source = "x = 1 + ... ignored % text\r\n\t 2; ... more\n +3;"
        self.assert_tokens(source, [
            (T.IDENTIFIER, "x", 1, 1), (T.ASSIGN, "=", 1, 3),
            (T.NUMBER, "1", 1, 5), (T.PLUS, "+", 1, 7),
            (T.NUMBER, "2", 2, 3), (T.SEMICOLON, ";", 2, 4),
            (T.PLUS, "+", 3, 2), (T.NUMBER, "3", 3, 3),
            (T.SEMICOLON, ";", 3, 4), (T.EOF, "", 3, 5),
        ])

    def test_ellipsis_immediately_after_number(self):
        self.assert_tokens("1... ignored\n+2", [
            (T.NUMBER, "1", 1, 1), (T.PLUS, "+", 2, 1),
            (T.NUMBER, "2", 2, 2), (T.EOF, "", 2, 3),
        ])

    def test_line_continuation_without_a_following_line_is_diagnosed(self):
        result = tokenize("x=1+... tail")
        self.assertEqual(result.tokens[-2], Token(T.INVALID, "... tail", 1, 5))
        self.assertEqual(result.diagnostics, (
            Diagnostic(
                "Line continuation requires a following physical line.",
                1, 5, Severity.ERROR,
            ),
        ))
        self.assertTrue(result.has_errors)
        self.assertEqual(result.tokens[-1], Token(T.EOF, "", 1, 13))

    def test_invalid_characters_and_unsupported_left_division_recover(self):
        result = tokenize("a=@;\n b=2\\3; .\\4 !")
        self.assertTrue(result.has_errors)
        self.assertEqual(
            [(item.lexeme, item.line, item.column) for item in result.tokens
             if item.type == T.INVALID],
            [("@", 1, 3), ("\\", 2, 5), (".\\", 2, 9), ("!", 2, 13)],
        )
        self.assertEqual(
            [(item.line, item.column, item.severity)
             for item in result.diagnostics],
            [(1, 3, Severity.ERROR), (2, 5, Severity.ERROR),
             (2, 9, Severity.ERROR), (2, 13, Severity.ERROR)],
        )
        self.assertTrue(all(item.message for item in result.diagnostics))
        self.assertEqual(
            [item.lexeme for item in result.tokens if item.type == T.NUMBER],
            ["2", "3", "4"],
        )
        self.assertEqual(result.tokens[-1], Token(T.EOF, "", 2, 14))

    def test_bare_dot_is_not_silently_discarded(self):
        result = tokenize("x.field")
        self.assertEqual(result.tokens[1], Token(T.INVALID, ".", 1, 2))
        self.assertEqual(len(result.diagnostics), 1)
        self.assertEqual(
            (result.diagnostics[0].line, result.diagnostics[0].column), (1, 2),
        )

    def test_unicode_and_null_outside_literals_are_diagnosed(self):
        result = tokenize("α = 1;\nlabel='α';\0")
        self.assertTrue(result.has_errors)
        self.assertEqual(
            [(item.line, item.column) for item in result.diagnostics],
            [(1, 1), (2, 11)],
        )
        self.assertIn(Token(T.CHARACTER_VECTOR, "'α'", 2, 7), result.tokens)
        self.assertEqual(result.tokens[-1], Token(T.EOF, "", 2, 12))

    def test_malformed_or_unsupported_numbers_are_not_split(self):
        for source in (
            "1e", "1e+", "2E-", "3.14.15", "1e2e3", "10foo",
            "2i", "3j", "0xFF", "0b101", "1e-3.4",
        ):
            with self.subTest(source=source):
                result = tokenize("  " + source + ";")
                self.assertEqual(result.tokens, (
                    Token(T.INVALID, source, 1, 3),
                    Token(T.SEMICOLON, ";", 1, 3 + len(source)),
                    Token(T.EOF, "", 1, 4 + len(source)),
                ))
                self.assertTrue(result.has_errors)
                self.assertEqual(len(result.diagnostics), 1)
                diagnostic = result.diagnostics[0]
                self.assertEqual((diagnostic.line, diagnostic.column), (1, 3))
                self.assertEqual(diagnostic.severity, Severity.ERROR)
                self.assertTrue(diagnostic.message)

    def test_unsupported_reserved_words_are_diagnosed(self):
        for word in (
            "function", "classdef", "switch", "try", "parfor", "global",
        ):
            with self.subTest(word=word):
                result = tokenize("\n " + word)
                self.assertEqual(
                    result.tokens[1], Token(T.INVALID, word, 2, 2),
                )
                self.assertEqual(result.diagnostics, (
                    Diagnostic(
                        f"MATLAB keyword {word!r} "
                        "is outside the supported subset.",
                        2, 2, Severity.ERROR,
                    ),
                ))
                self.assertTrue(result.has_errors)

    def test_empty_source(self):
        self.assert_tokens("", [(T.EOF, "", 1, 1)])

    def test_horizontal_whitespace_only(self):
        self.assert_tokens(" \t\f\v", [(T.EOF, "", 1, 5)])

    def test_invalid_api_argument(self):
        for source in (None, 42, b"x=1;"):
            with self.subTest(source=source):
                with self.assertRaisesRegex(
                    TypeError, "source must be a string",
                ):
                    tokenize(source)

    def test_calls_do_not_share_state(self):
        self.assertTrue(tokenize("@").has_errors)
        self.assert_tokens("x", [
            (T.IDENTIFIER, "x", 1, 1), (T.EOF, "", 1, 2),
        ])

    def test_dsp_sampled_cosine_snippet(self):
        source = (
            "fs = 1000;\n"
            "T = 1;\n"
            "t = 0:1/fs:T-1/fs;\n"
            "f0 = 5;\n"
            "A = 2;\n"
            "x = A*cos(2*pi*f0*t);\n"
        )
        self.assert_tokens(source, [
            (T.IDENTIFIER, "fs", 1, 1), (T.ASSIGN, "=", 1, 4),
            (T.NUMBER, "1000", 1, 6), (T.SEMICOLON, ";", 1, 10),
            (T.NEWLINE, "\n", 1, 11),
            (T.IDENTIFIER, "T", 2, 1), (T.ASSIGN, "=", 2, 3),
            (T.NUMBER, "1", 2, 5), (T.SEMICOLON, ";", 2, 6),
            (T.NEWLINE, "\n", 2, 7),
            (T.IDENTIFIER, "t", 3, 1), (T.ASSIGN, "=", 3, 3),
            (T.NUMBER, "0", 3, 5), (T.COLON, ":", 3, 6),
            (T.NUMBER, "1", 3, 7), (T.DIVIDE, "/", 3, 8),
            (T.IDENTIFIER, "fs", 3, 9), (T.COLON, ":", 3, 11),
            (T.IDENTIFIER, "T", 3, 12), (T.MINUS, "-", 3, 13),
            (T.NUMBER, "1", 3, 14), (T.DIVIDE, "/", 3, 15),
            (T.IDENTIFIER, "fs", 3, 16), (T.SEMICOLON, ";", 3, 18),
            (T.NEWLINE, "\n", 3, 19),
            (T.IDENTIFIER, "f0", 4, 1), (T.ASSIGN, "=", 4, 4),
            (T.NUMBER, "5", 4, 6), (T.SEMICOLON, ";", 4, 7),
            (T.NEWLINE, "\n", 4, 8),
            (T.IDENTIFIER, "A", 5, 1), (T.ASSIGN, "=", 5, 3),
            (T.NUMBER, "2", 5, 5), (T.SEMICOLON, ";", 5, 6),
            (T.NEWLINE, "\n", 5, 7),
            (T.IDENTIFIER, "x", 6, 1), (T.ASSIGN, "=", 6, 3),
            (T.IDENTIFIER, "A", 6, 5), (T.MULTIPLY, "*", 6, 6),
            (T.IDENTIFIER, "cos", 6, 7), (T.LPAREN, "(", 6, 10),
            (T.NUMBER, "2", 6, 11), (T.MULTIPLY, "*", 6, 12),
            (T.IDENTIFIER, "pi", 6, 13), (T.MULTIPLY, "*", 6, 15),
            (T.IDENTIFIER, "f0", 6, 16), (T.MULTIPLY, "*", 6, 18),
            (T.IDENTIFIER, "t", 6, 19), (T.RPAREN, ")", 6, 20),
            (T.SEMICOLON, ";", 6, 21), (T.NEWLINE, "\n", 6, 22),
            (T.EOF, "", 7, 1),
        ])

    def test_dsp_unit_step_impulse_and_ramp_snippet(self):
        source = (
            "n = -10:10;\n"
            "u = double(n >= 0);\n"
            "imp = double(n == 0);\n"
            "r = n.*double(n >= 0);\n"
        )
        self.assert_tokens(source, [
            (T.IDENTIFIER, "n", 1, 1), (T.ASSIGN, "=", 1, 3),
            (T.MINUS, "-", 1, 5), (T.NUMBER, "10", 1, 6),
            (T.COLON, ":", 1, 8), (T.NUMBER, "10", 1, 9),
            (T.SEMICOLON, ";", 1, 11), (T.NEWLINE, "\n", 1, 12),
            (T.IDENTIFIER, "u", 2, 1), (T.ASSIGN, "=", 2, 3),
            (T.IDENTIFIER, "double", 2, 5), (T.LPAREN, "(", 2, 11),
            (T.IDENTIFIER, "n", 2, 12), (T.GREATER_EQUAL, ">=", 2, 14),
            (T.NUMBER, "0", 2, 17), (T.RPAREN, ")", 2, 18),
            (T.SEMICOLON, ";", 2, 19), (T.NEWLINE, "\n", 2, 20),
            (T.IDENTIFIER, "imp", 3, 1), (T.ASSIGN, "=", 3, 5),
            (T.IDENTIFIER, "double", 3, 7), (T.LPAREN, "(", 3, 13),
            (T.IDENTIFIER, "n", 3, 14), (T.EQUAL, "==", 3, 16),
            (T.NUMBER, "0", 3, 19), (T.RPAREN, ")", 3, 20),
            (T.SEMICOLON, ";", 3, 21), (T.NEWLINE, "\n", 3, 22),
            (T.IDENTIFIER, "r", 4, 1), (T.ASSIGN, "=", 4, 3),
            (T.IDENTIFIER, "n", 4, 5),
            (T.ELEMENTWISE_MULTIPLY, ".*", 4, 6),
            (T.IDENTIFIER, "double", 4, 8), (T.LPAREN, "(", 4, 14),
            (T.IDENTIFIER, "n", 4, 15), (T.GREATER_EQUAL, ">=", 4, 17),
            (T.NUMBER, "0", 4, 20), (T.RPAREN, ")", 4, 21),
            (T.SEMICOLON, ";", 4, 22), (T.NEWLINE, "\n", 4, 23),
            (T.EOF, "", 5, 1),
        ])
