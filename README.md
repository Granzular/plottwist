# plottwist

**MATLAB to Python. Code to plots.**

plottwist is a web-based MATLAB-to-Python transpilation and visualization tool designed for Digital Signal Processing (DSP) coursework and experimentation.

The workspace connects independent translation, Python execution, and export services through one Run action. Enter MATLAB source to view generated Python, ordered plots, output, translation warnings, and useful execution errors. Generated code remains available when execution fails.

## Overview

The goal of plottwist is to make it easier to work with MATLAB-based DSP exercises without requiring a MATLAB installation.

The workflow is:

1. Write or paste MATLAB code.
2. Run the code through plottwist.
3. The application translates the MATLAB code into Python.
4. The generated Python code is executed.
5. Generated plots and execution output are displayed.
6. Download generated Python and individual or combined chart documents.

Generated Python code is displayed as read-only output. Users interact with the original MATLAB source rather than editing the translated code.

## Features

Implemented foundation:

- Django workspace with editable MATLAB source and empty code/plot result areas.
- Backend MATLAB-to-Python translation service with validated JSON responses and mocked tests.
- Child-process Python execution using NumPy, Matplotlib, and SciPy, with separate PNG artifacts and actual subprocess tests.
- Exports of individual charts as PNG/PDF/DOCX, combined charts as PDF/DOCX, and Python source as `.py`.
- Integrated Run form with loading feedback, temporary private results, and downloads.
- Original MATLAB source downloads, checked figure selection, and combined exports of the selected figures.
- Public website, user guide, About, Contact, Privacy Policy, and Terms of Use.
- Optional workspace tour with backward/forward navigation, dismissal, and replay.

Planned functionality:

- CSV export for supported numerical data.
- Optional user accounts for saving generated plots.

## Technology Stack

| Component | Technology |
|---|---|
| Backend | Django |
| Frontend | Django Templates, JavaScript |
| Styling | Tailwind CSS |
| LLM inference | Groq |
| Numerical computing | NumPy |
| Plotting | Matplotlib |
| Scientific computing | SciPy |
| Database | SQLite or configured PostgreSQL |
| Dependency management | uv |

## Getting Started

### Requirements

- Python 3.13
- uv

### Installation

Clone the repository:

```bash
git clone https://github.com/Granzular/plottwist.git
cd plottwist
```

Install dependencies:

```bash
uv sync --locked
```

Create an environment file:

```bash
cp .env.example .env
```

On PowerShell, use `Copy-Item .env.example .env` instead of `cp`.

Generate a local secret:

```bash
uv run python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Set `DJANGO_SECRET_KEY` in `.env` to that value, enclosed in quotes. Django refuses to start without a secret. Do not reuse this secret for a deployed environment.

### Database setup

```bash
uv run python manage.py migrate
```

### Start the development server

```bash
uv run python manage.py runserver
```

Open `http://127.0.0.1:8000/` for the public website,
`http://127.0.0.1:8000/workspace/` for the workspace, or
`http://127.0.0.1:8000/guide/` for the user guide. The former `/home/` route
has been removed.

The public navigation links to the workspace and informational pages. New visitors
can start or dismiss a small tour invitation in the workspace; use **Workspace
tour** to replay it. Completion/dismissal is remembered in browser local storage,
without storing source or results. Read [docs/public-website.md](docs/public-website.md)
for route, content, data-handling, and verification details.

## Configuration

The application uses environment variables for configuration. Never commit API credentials or other secrets to the repository.

Refer to `.env.example` for the expected configuration variables.

| Variable | Behavior |
|---|---|
| `DJANGO_SECRET_KEY` | Required; no built-in default. |
| `DJANGO_DEBUG` | Defaults to `False`; `true`, `1`, `yes`, or `on` enable it, case-insensitively. The example enables it for local development. |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames, defaulting to `localhost,127.0.0.1,[::1]`. |
| `GROQ_API_KEY` | Existing Groq credential variable; required for translation, optional for Django startup. |
| `GROQ_MODEL` | Defaults to `openai/gpt-oss-120b`, which supports strict structured output. |
| `GROQ_TIMEOUT_SECONDS` | Positive finite request timeout in seconds; defaults to `30`. Automatic SDK retries are disabled. |
| `GROQ_RESPONSE_FORMAT` | Defaults to `json_schema`; use `json_object` for models without strict JSON Schema support. |
| `EXECUTION_TIMEOUT_SECONDS` | Positive finite child-process timeout, defaulting to `60` seconds; includes library startup and PNG rendering. |
| `ARTIFACT_TTL_SECONDS` | Positive result lifetime, defaulting to `900` seconds (15 minutes). |

The root `.env` is loaded with python-dotenv. Existing process environment variables take precedence. SQLite remains at `db.sqlite3`; templates and static sources use the root `templates/` and `static/` directories. Media is configured at `/media/` with local storage in `media/`; no upload or media-serving workflow is implemented yet.

WhiteNoise serves collected application assets at `/static/`. Before starting a
deployment (or testing with `DJANGO_DEBUG=False`), run:

```bash
uv run python manage.py collectstatic --noinput
```

Assets are collected into the ignored `staticfiles/` directory, with compressed
copies and manifest-hashed URLs. Tailwind's `static/css/input.css` is build source
and is excluded from collection; rebuild `static/css/app.css` with the standalone
CLI before collecting after frontend changes. To exercise WhiteNoise locally
instead of Django's development static handler, use
`uv run python manage.py runserver --nostatic` after collecting. WhiteNoise does
not serve `media/` or private `.cache/executions/` artifacts; their existing
session-protected view/download endpoints remain responsible for delivery.

Reuse your existing `GROQ_API_KEY`; it does not need to be copied into `.env`. On Windows, restart your terminal/server after changing user environment variables so the process inherits them. No credentials are stored in committed files.

## Translation service

Call the entry point from a Django context:

```python
from core.translation import translate_matlab

result = translate_matlab(matlab_source)
```

Every call returns a dictionary with:

- `success`: a boolean.
- `python_code`: generated source on success, or an empty string on failure.
- `warnings`: a list of translation warnings, retained on code-validation failures when available.
- `error`: `None` on success, otherwise a safe, useful error message.

The provider must return exactly `python_code` and `warnings` in JSON. The default model uses strict [Groq structured output](https://console.groq.com/docs/structured-outputs); a model configured for `json_object` still undergoes the same local validation. Choose a response format supported by your model; unsupported model/format combinations fail cleanly without automatic fallback requests. Arbitrary prose, markdown fences, incomplete responses, schema violations, and invalid/empty Python are rejected.

Translation instructions prioritize NumPy, Matplotlib, and SciPy for elementary DSP, including MATLAB indexing, colon sampling, matrix versus element-wise operations, and figure/subplot organization. Unsupported essential operations should yield no code and an explanatory warning rather than fabricated results.

The service parses and compiles Python for syntax validation only. It never executes the source or imports generated dependencies. Success does not prove mathematical correctness, complete MATLAB compatibility, or execution safety; generated source remains untrusted. The function and result contract allow the Groq implementation to be replaced without coupling callers to a provider or execution engine.

## Python execution service

Call `core.execution.execute_python(source)` from a Django context. It accepts
Python directly and does not call Groq or the translation service. It returns:

- `success`: whether source execution and figure capture completed successfully.
- `figures`: ordered dictionaries with `name`, `content_type` (`image/png`), and
  `data` (PNG bytes). Later views can use an `HttpResponse` and exports can consume
  these bytes through `BytesIO`; no base64 encoding or database storage is involved.
- `stdout` and `stderr`: captured UTF-8 text with normalized line endings.
- `error`: `None` on success, otherwise a useful failure description; runtime
  tracebacks, including source locations, are captured in `stderr`.
- `execution_time`: elapsed wall time in seconds, including process startup and
  figure capture.

The child uses `sys.executable` from the active uv environment in isolated mode,
sets Matplotlib to `Agg` before importing pyplot, and runs in a fresh temporary
directory. Each figure is saved as a separate PNG in creation order, including
figures closed by the source. Subplots remain within their parent figure. The
parent reads PNG bytes and removes the working directory before returning.
Success without plots returns an empty figure list. Runtime errors may preserve
figures created before the error; a timeout kills and waits for the child, returns
captured output without figures, and removes temporary files.

Basic safeguards reject unsupported imports, direct/aliased dangerous builtins,
private attribute access, obvious file operations, and backend switching. Allowed
imports are NumPy, Matplotlib, SciPy, math, cmath, statistics, time, and warnings.
The child receives OS runtime essentials and execution settings rather than
inheriting Django/Groq credentials. Source is limited to 64 KiB; stdout/stderr to
64 KiB each, with a truncation marker and continuous draining. Artifact limits
are 20 figures, 4 million pixels per figure, 5 MiB per PNG, and 20 MiB total PNG
bytes. PNG filenames, paths, signatures, and sizes are checked before returning.

These checks are not complete Python sandboxing. There is no hard memory/CPU
quota or operating-system permission isolation; library behavior can bypass AST
checks, and the child retains the host user's filesystem/network privileges.
The timeout controls the direct child, not a process tree created through a
bypass. The Run endpoint uses this service for local development. These safeguards
do not make the application suitable for untrusted public execution; deployment
requires separately considered operating-system isolation and resource controls.

## Export service

`core.exports` accepts supplied data and never calls translation or execution:

```python
from core.exports import export_figure, export_figures, export_matlab, export_python

chart = export_figure(figures, index=0, format='png')
combined = export_figures(figures, format='pdf')
python_file = export_python(python_source)
matlab_file = export_matlab(matlab_source)
```

- `export_figure(figures, index=0, format='png')`: individual PNG, PDF, or DOCX.
  Indices are zero-based; negative indices are rejected.
- `export_figures(figures, format='pdf')`: combined PDF or DOCX, one chart per
  page in input order. Pass a nonempty ordered list or tuple of PNG artifacts.
- `export_python(source)`: UTF-8 `generated.py`, preserving source exactly,
  including whitespace and line endings. This function does not validate syntax.
- `export_matlab(source)`: UTF-8 `generated.m`, preserving the submitted MATLAB
  text exactly, with `text/x-matlab; charset=utf-8`. No parsing or formatting occurs.

Every export returns `name`, `content_type`, and `data` (immutable file bytes),
matching the execution artifact shape. Individual filenames are
`figure-001.png/pdf/docx` according to the selected index; combined documents are
`charts.pdf/docx`. Incoming artifact names do not control download filenames.
Everything is generated in memory without database storage or persistent files.

PNG exports validate the image and return its original bytes. PDF pages tightly
fit the chart at a nominal 100 DPI, reduced to A4 bounds when necessary, with
preserved aspect ratio and no added margins. Matplotlib embeds the existing
raster image; exporting to PDF does not recover vector plotting data. DOCX uses
A4 portrait pages with 0.75-inch margins, proportionally fitted original PNGs,
and explicit page breaks between charts. Inline baseline space is reserved to
avoid an extra page for tall images.

Missing figures, malformed/corrupt/non-PNG image data, images over 4 million
pixels, empty source text, and unsupported formats raise `ValueError`.
Invalid integer indices raise `IndexError`; incorrect argument types raise
`TypeError`. A bad chart later in a collection raises rather than returning a
partial combined document. CSV and other formats are not implemented.

Pillow and Matplotlib provide image validation/PDF writing; python-docx (with
lxml) provides DOCX writing. pypdf is installed in the `dev` dependency group
for structural PDF tests and is not required by the export service. The standard
`uv sync --locked` command installs test dependencies too.

## Integrated workspace and downloads

The workspace form posts `matlab_code` to the named `core:run` route at `/run/`.
The endpoint accepts form-encoded/multipart or JSON requests, preserves CSRF,
rejects empty source, and limits MATLAB input to 64 KiB of UTF-8. Requests are
limited to 128 KiB including their envelope. JavaScript submits JSON with
`Accept: application/json` and the form's CSRF token, preserving the textarea's
line endings. It disables repeat clicks while pending and replaces the results
with an autoescaped Django template. A normal form POST also renders the
workspace without JavaScript.

The compact toolbar contains Run, Clear source, and the optional Workspace tour. Desktop code panels sit
side by side above the figure workspace and command window; mobile stacks
MATLAB, generated Python, figures, then output. The existing fonts, typography,
and colour palette are retained. Python remains read-only. Clearing the editor
does not change the submitted source associated with the displayed results.

Each code panel has a keyboard-accessible Copy control. MATLAB copying reads
the current editor value; Python copying preserves the complete generated source,
including indentation and line endings. Copying uses the browser Clipboard API
with a local fallback, briefly shows `Copied` on success, and reports failure
with manual-copy guidance. Empty code cannot be copied. Source downloads remain
available independently and continue to refer to the displayed stored run.

Responses distinguish `validation`, `translation`, `execution`, `storage`, and
`complete` stages. They include generated Python, translation warnings, public
output/errors, duration, an execution ID, and figure URLs rather than image bytes.
Raw execution tracebacks/private diagnostic lines are omitted. A translation
failure stops before execution; an execution failure retains Python/warnings and
any captured figures. Successful code without figures is shown as a success.

Status codes include 400 for invalid input, 413 for oversized input, 415 for
unsupported content types, 409 for an active run in the same session, 502 for
translation failures, 422 for execution failures, 504 for stage timeouts, and
503 for temporary-storage failures. Export generation failures return a safe
error rather than provider details or internal paths.

Private artifacts are stored beneath `.cache/executions/<random-UUID>/`, never
served as public media/static. PNGs are written once and metadata contains the
original MATLAB text, Python, warnings, public output, creation time, and an
owner-token hash. Django's existing
session stores only an opaque owner token and last execution ID, with no plots,
generated code, or new database models. Files survive separate requests/processes
and server restarts within their lifetime. Atomic directory renaming prevents
partially written runs from becoming visible. Exclusive owner-specific lock
files reject concurrent runs from the same established browser session.

Every image/download read checks the session owner and fixed creation-time
expiration. Unknown, expired, unauthorized results and invalid individual figure
indices return 404. Invalid combined selections return 400 after ownership is
checked. Knowing another execution's UUID is insufficient for access. Expired
results are deleted on access, and new runs clean expired directories and stale
locks. To remove expired artifacts while the application is idle, run or schedule:

```bash
uv run python manage.py cleanup_artifacts
```

Without periodic cleanup, inaccessible expired files remain until the next
cleanup/access. The private directory must be shared by Django workers on the
same host; multiple hosts need a separately considered storage arrangement.

Named download/image routes:

| Route | Behavior |
|---|---|
| `core:figure` | Displays the selected PNG, with private/no-store caching. |
| `core:download_figure` | Individual PNG/PDF/DOCX by execution ID and zero-based index. |
| `core:download_figures` | Combined PDF/DOCX for validated selected indices, in stored figure order. |
| `core:download_python` | Unmodified generated source as `generated.py`, including after execution failure. |
| `core:download_matlab` | Exact MATLAB source submitted for that stored run as `generated.m`, including after execution failure. |

Downloads use `Content-Disposition: attachment`, the export service's MIME types,
and deterministic filenames. Exporting does not translate or execute the source
again. Individual downloads load only the requested image; combined documents
load only the selected stored PNGs. Source downloads share the run's session
ownership, expiration, and cleanup. Subsequent editor changes or runs do not
change an existing run's source. Translation failures do not create execution
artifacts; storage failures cannot offer downloads.

Every figure is checked by default when new results arrive. Select all and Clear
selection update the selected count; an empty selection disables combined
downloads and displays an explanation. Individual previews/downloads remain
available. New runs replace the selection with all of their own figures.

Combined download forms send repeated zero-based `indices` query parameters,
for example `?selection=1&indices=0&indices=2&indices=4`. The `selection` marker
distinguishes an explicitly empty selection from older links that omit selection
parameters and export the full collection. Empty selections, duplicates,
noncanonical integers, negative values, and out-of-range indices return 400.
Valid indices are sorted against the stored collection before exporting;
arriving as `4, 0, 2` still exports original figures 1, 3, and 5. Without JavaScript,
the checkboxes and native download forms still submit the chosen subset, while
bulk selection controls and the live count are hidden.

## Frontend development

The interface follows [.agents/skills/ui-design/SKILL.md](.agents/skills/ui-design/SKILL.md). It uses local, compiled Tailwind CSS without a browser CDN or Node dependency. `static/css/input.css` is the source and `static/css/app.css` is the committed output.

Download the pinned Tailwind v4.1.18 standalone CLI once, then rebuild after changing templates or CSS. On Windows PowerShell:

```powershell
New-Item -ItemType Directory -Path .tools -Force
Invoke-WebRequest -Uri https://github.com/tailwindlabs/tailwindcss/releases/download/v4.1.18/tailwindcss-windows-x64.exe -OutFile .tools/tailwindcss.exe
.\.tools\tailwindcss.exe -i ./static/css/input.css -o ./static/css/app.css --minify
```

On other platforms, use the matching standalone binary from the same [Tailwind release](https://github.com/tailwindlabs/tailwindcss/releases/tag/v4.1.18) with the same input/output arguments. Add `--watch` for template development. The local `.tools/` directory is ignored by Git. Starting Django needs only the compiled CSS already in the repository.

## Verification

```bash
uv run python manage.py check
uv run python manage.py test
uv run python manage.py findstatic css/app.css
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py migrate --check
uv lock --check
git diff --check
```

The named workspace route is `core:home` at `/workspace/`; the public homepage is
`core:public_home` at `/`. Tests cover service behavior and workflow/download integration, including
exact MATLAB/Python source downloads, selected exports and original order, private
ownership, expiration, input validation, CSRF, duplicate requests, stage-specific
errors, and template rendering. Public tests also check shared navigation, screenshot
paths, guide anchors, configured retention text, and optional tour markup. Translation
is mocked without Groq API requests; execution service tests use actual subprocesses.
Export tests inspect real PDF/DOCX documents. Read [AGENTS.md](AGENTS.md) for project
development rules.

The public-page and tour browser checks use an installed Chromium browser and
Python's standard library, with no Node.js or browser package requirement:

```bash
uv run python manage.py test core.test_public core.test_public_browser
```

They cover desktop/tablet/mobile/zoom layouts, mobile navigation, keyboard focus,
tour persistence and replay, live result replacement, selected PDF/DOCX downloads,
blocked local storage, reduced motion, and native Run without JavaScript.
Set `PLOTTWIST_PUBLIC_SCREENSHOTS` to a local directory to retain review screenshots.
Browser checks explicitly skip if no supported browser is installed.

`core.test_browser` uses Django's live test server, an installed Chromium browser
(Edge, Chrome, or Chromium), and Node.js 22+ with native DevTools/WebSocket calls;
no browser package is installed. It mocks translation and exercises real Python
subprocesses, selection defaults and changes, disabled empty exports, native
subset downloads, source preservation, result replacement, failure states,
keyboard focus, fonts/colours, and layout at 1280px, 360px, and a 640px viewport
equivalent to 200% desktop zoom. Downloaded PDF/DOCX files are opened to check
the selected figures and order. These checks run with the full suite when the
tools are available and explicitly skip otherwise. Run them separately with:

```bash
uv run python manage.py test core.test_browser
```

Set `PLOTTWIST_BROWSER` to an executable path if automatic detection cannot find
the browser. Optionally set `PLOTTWIST_BROWSER_SCREENSHOTS` to a local directory
to retain screenshots; other browser profiles, downloads, and execution
artifacts are temporary and cleaned after the test.

## Project Status

plottwist is under active development.

The Run workflow and downloads are integrated. Accounts, saved plots, and CSV exports remain outside the implemented scope. Live Groq translation quality has not been verified by mocked tests. DOCX pagination is checked structurally; final rendering can vary by word processor. Passing checks does not establish production execution security.

## License

License not yet selected.
