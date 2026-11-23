# Milestone 1: MATLAB lexer

`core.transpiler.tokenize(source)` performs lexical analysis only. It returns an
immutable `LexResult` with ordered tokens, a final EOF token, diagnostics, and
`has_errors`. It needs only Python 3.13's standard library and local package
modules. It does not call Django, Groq, execution, artifact, or export services.
Lexical success means that the source can be represented by tokens; it does not
establish a valid MATLAB statement or generate Python.

## Apostrophes and transpose

The lexical decision is to retain the adjacency rule for a bare apostrophe.
An adjacent `'` after a token that can end an expression is conjugate transpose.
A whitespace-separated bare apostrophe opens a character vector, even after an
identifier. Thus `A '` and `x = A '` contain unterminated character vectors;
they are not accepted as spaced conjugate transposes.

The two characters in `.'` must remain contiguous. Whitespace before this
operator is allowed in expression contexts, such as `x = A .'`; whitespace
between its dot and apostrophe is not removed or normalized.

| Source | Lexical handling |
|---|---|
| `A'`, `x = A'` | Identifier followed by conjugate transpose. |
| `A '`, `x = A '` | Bare quote starts an unterminated character vector; error at the quote. |
| `A.'`, `x = A.'` | Identifier followed by nonconjugate transpose. |
| `x = A .'` (also with a tab before the dot) | Nonconjugate transpose; preserve the operator's physical position. |
| `A .'` | Identifier and contiguous `.'` tokens with a source gap; command-form classification is outside this lexer, as explained below. |
| `A . '`, `A. '` | Invalid standalone dot and unterminated character vector; diagnose both locations. |
| `'A'`, `'hello'`, `x = 'hello'` | Character vectors, including original delimiters. |
| `"hello"`, `x = "hello"` | String scalars, including original delimiters. |
| `2'`, `x = (A)'`, `x = [1 2]'`, `C{1}'` | Conjugate transpose after a number or closing delimiter. |
| `x = A''`, `A.''` | Distinct successive transpose tokens. |
| `['a' 'b']` | Two character vectors; whitespace does not become a transpose. |

`'` and `.'` remain distinct tokens: conjugate transpose also conjugates complex
values, whereas nonconjugate transpose only exchanges indices. The lexer does
not calculate either operation. Double quotes always open string scalars.
Within either literal, doubling its delimiter escapes it. Backslashes are
ordinary source characters. Literal lexemes are preserved without decoding.

An identifier at the start of a statement followed by whitespace can introduce
MATLAB command-form syntax. The compatibility scanner described below rejects
standalone `A .'` as an unterminated command argument but recognizes `x = A .'`
as nonconjugate transpose. This lexer deliberately does not classify commands
or resolve names. It preserves the identifier, operator, and source gap rather
than claiming the standalone command is a valid transpose statement. Use `A.'`
or an explicit expression/assignment context. A later stage must reject
unsupported command syntax; consumers must not treat `has_errors == False` as
statement validation. The same distinction applies to tokens for `A 'value'`.

### Evidence and verification limits

Investigation on 2026-11-23 found no MATLAB/Octave executable on PATH, no usual
installation directories, and no MATLAB installation keys in the inspected
MathWorks registry locations. No MATLAB or Octave runtime was installed or run.

MathWorks' [conjugate transpose reference](https://www.mathworks.com/help/matlab/ref/ctranspose.html)
and [nonconjugate transpose reference](https://www.mathworks.com/help/matlab/ref/transpose.html)
establish the operator meanings. The live pages returned HTTP 403 in this
environment; their translated [ctranspose copy](https://docs.exponenta.ru/matlab/ref/ctranspose.html)
and [transpose copy](https://docs.exponenta.ru/matlab/ref/transpose.html) were
accessible. These references do not explicitly settle the disputed whitespace
case. Whitespace created by HTML formatting is not executable syntax evidence.

The whitespace decision is supported by inspecting and running the MATLAB-mode
scanner in [MISS_HIT revision 9db1143](https://github.com/florianschanda/miss_hit/blob/9db1143b88e115ee54e92c5ab7189b26e49f48cb/miss_hit_core/m_lexer.py#L625-L683).
Its bare-quote branch explicitly treats preceding whitespace as a character
vector; its dotted-operator branch requires contiguous dot and quote. A
temporary source copy, outside the project and with no installation, exercised
every example in the table and continuation variants. The probe used the
scanner only, with a diagnostic handler that raised an exception on a lexical
error; it did not run a parser or execute MATLAB. The source copy was removed.
These are **compatibility results, not direct MATLAB runtime verification**.

The [tree-sitter MATLAB scanner](https://raw.githubusercontent.com/acristoffers/tree-sitter-matlab/master/src/scanner.c)
provides corroborating source evidence for the adjacent bare-quote rule.
[Octave's scanner](https://github.com/gnu-octave/octave/blob/50d7066ea770e8b01e8d209b1bd25dbd048deb0d/libinterp/parse-tree/lex.ll#L1515-L1581)
uses different context/whitespace rules in some expression cases. Its source
was inspected, not executed. Octave permissiveness is not taken as proof of
MATLAB syntax.

## Token contract and DSP scope

The scanner covers identifiers; the required `if`, `else`, `elseif`, `end`,
`for`, and `while` keywords; integer, decimal, and scientific notation; the
agreed arithmetic, element-wise, comparison, logical, assignment, and transpose
operators; `()[]{},;:`; character vectors and string scalars; `%` comments;
continuations; and newlines. Existing `break`, `continue`, and `return` tokens
are retained; no additional language constructs were introduced by this task.

- Multi-character operators are recognized before their shorter prefixes.
  A decimal dot is not consumed when it begins `.*`, `./`, `.^`, `.'`, or `...`.
  Numeric signs are separate operators; exponent signs remain in number lexemes.
- NEWLINE, comma, and semicolon remain visible. Whitespace and comments are
  trivia. `...` consumes the remainder of its physical line and its newline,
  preserving physical positions without introducing a statement separator.
  It does not join a bare apostrophe to an earlier operand across that gap.
- LF, CRLF, and CR each advance one physical line; NEWLINE lexemes preserve
  their original endings. Lines and columns are one-based. Tabs and Unicode
  characters in literals/comments each count as one source character.
- Block-comment markers `%{` and `%}` must occupy their own lines. Nesting is
  supported; missing closers are diagnosed at their opening positions. Physical
  newlines inside block comments remain NEWLINE tokens.
- EOF has an empty lexeme and points immediately after the physical source.
  Empty source is valid lexical input. A non-string API argument raises TypeError.

Diagnostics contain `message`, `line`, `column`, and `severity`. Invalid lexemes
produce INVALID tokens and error diagnostics; scanning recovers where possible.
Unterminated literals recover at a physical newline. Unterminated block comments
and incomplete continuations are diagnosed. Callers must check `has_errors`.

Identifiers use ASCII letters followed by ASCII letters, digits, or underscores.
Physical multiline literals, imaginary/base-prefixed numbers, left division,
field access, function handles, and reserved words outside the initial subset
are diagnosed rather than silently discarded. Function names are identifiers;
unknown functions and variables are not resolved. Delimiter balance, command
syntax, operand validity, indexing semantics, and statement syntax belong to
later stages. There is no parser, AST, code generation, or Run integration.

## Verification commands

```sh
uv run --no-sync python manage.py test core.transpiler.tests
uv run --no-sync python -S -m unittest core.transpiler.tests.test_lexer
uv run --no-sync python manage.py test core.test_browser
uv run --no-sync python manage.py test
uv run --no-sync python manage.py check
uv lock --check
```

The Django and standalone lexer suites cover all agreed token categories,
numeric/operator boundaries, escaped literals, transpose contexts, comments,
continuations, physical positions, malformed input, EOF, and DSP examples.

### Completion verification, 2026-11-23

- Lexer: 49 tests passed through Django and 49 passed with `python -S`.
  A fresh isolated import loaded no Django, Groq, or application services.
- Browser/workflow group: all 30 tests passed.
- Full Django suite: all 129 tests passed in 120.333 seconds, including the
  browser and real execution/export checks.
- Django system check, static discovery, migration checks, lockfile check,
  and Git/whitespace checks passed. Dependencies and Groq code are unchanged.

The earlier browser failure was independent of the lexer and reproduced in
isolation. With the old fixture connection sharing, a three-run sample passed
once and failed twice. Network diagnostics revealed HTTP 500/404 image responses,
not unfinished decoding; a server exception identified SQLite `InterfaceError:
bad parameter or other API misuse` during concurrent session reads. Django's
live-server fixture was passing one in-memory connection to all request threads.

`WorkspaceBrowserTests` now lets request threads open separate connections to
the same shared-cache memory URI. Plain `:memory:` retains Django's connection
sharing because separate connections would see different databases; two small
tests cover this distinction. Three controlled runs and the permanent isolated
browser run passed after the correction. A separate observed race was fixed by
submitting Run and asserting its synchronous busy state in one DevTools
evaluation. Image-loading conditions and timeouts were not relaxed. These
changes affect test fixtures/assertions only; application database settings,
session handling, views, and workflow code were not modified.
