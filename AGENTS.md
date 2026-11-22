# plottwist development guidance

## Purpose and stack

plottwist is an academic computing tool for DSP coursework: MATLAB to Python.
Code to plots. The application provides a server-rendered workspace and
independent translation, Python execution, and export services connected through
the homepage's single Run action.

Use Python 3.13, Django, Django Templates, vanilla JavaScript, Tailwind CSS,
SQLite, and uv. Existing dependencies include python-dotenv, Groq, NumPy,
Matplotlib, and SciPy. Groq powers translation; numerical execution runs in a
separate Python process.
Exports reuse PNG artifacts with Pillow/Matplotlib and python-docx. pypdf is a
development dependency for PDF validation; Pillow is declared directly.

## Structure

- `config/`: the single Django settings module and project URL/ASGI/WSGI setup.
- `core/`: the existing application, including views, application URLs, tests,
  and independent `translate_matlab` / `execute_python` entry points in
  `translation.py` / `execution.py`. `_execution_runner.py` is the trusted child
  bootstrap and imports no Django settings or translation code.
- `core/exports.py`: exports from supplied PNG artifacts or Python text; no
  dependency on requests, sessions, or invoking other services.
- `core/workflow.py`: stage-aware orchestration and public diagnostic filtering.
- `core/artifacts.py`: private temporary result files and per-session run locks.
- `core/management/commands/cleanup_artifacts.py`: expiration cleanup for idle periods.
- `templates/`: root template directory; page templates live in `templates/core/`.
- `static/`: root static directory; Tailwind source and compiled CSS in `css/`.
- `media/`: local generated/uploaded media, ignored by Git.
- `src/plottwist/`: existing uv package scaffold; web execution uses `manage.py`.
- `.agents/skills/ui-design/SKILL.md`: reusable UI implementation guidance.
- `.env.example`: documented configuration; `.env` stays local and untracked.

## Development commands

```sh
uv sync --locked
# Copy .env.example to .env and generate a local secret:
uv run python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
uv run python manage.py check
uv run python manage.py migrate
uv run python manage.py runserver
uv run python manage.py test
uv run python manage.py findstatic css/app.css
uv run python manage.py cleanup_artifacts
```

Set `DJANGO_SECRET_KEY` in `.env` before running Django. See `README.md` for
environment setup and the standalone Tailwind build command. Commit compiled
CSS with its source so running Django does not need Node or a CSS build service.

## Implementation conventions

- Inspect existing files and applicable guidance before editing; preserve work.
- Prefer straightforward solutions; avoid duplication, unnecessary files,
  excessive fragmentation, and abstractions without a concrete need.
- Use uv for Python dependency management and execution. Add dependencies only
  for a demonstrated requirement and update the lockfile deliberately.
- Follow Django conventions and PEP 8. Use named, namespaced routes in
  `core/urls.py`, then include them from the project URL configuration.
- Keep views small: handle requests and render responses. When application logic
  arrives, keep it in `core` outside views/templates; do not pre-create layers.
- Keep settings in `config/settings.py`; retain SQLite for development.
- Keep documentation aligned with implemented behavior and tested commands.

## Frontend

Read and apply `.agents/skills/ui-design/SKILL.md` for UI changes. Use Django
templates, semantic HTML, Tailwind, and vanilla JavaScript only when interaction
requires it. Keep code inputs, read-only generated code, and figures distinct.
Use template inheritance where it avoids duplication. Reference assets with
Django's `static` tag. Rebuild compiled CSS when classes or CSS source change.
Do not put processing logic in templates or imply unavailable actions work.

## Verification

Use Django's built-in testing framework, not pytest. Add small, meaningful tests
for routes, responses, template rendering, and application behavior as it arrives.
Mock Groq at the SDK boundary in translation tests; never make real API requests
or expose credentials in test output.
Exercise real subprocesses for execution tests, including figure order, output,
runtime errors, timeouts, and temporary artifact cleanup.
Validate exports by opening PDFs with pypdf and DOCX files with python-docx/ZIP
inspection. Check page/image counts, order, geometry, aspect ratios, and errors.
Run system checks and relevant tests after changes; run migrations when needed.
Check static discovery and browser rendering at desktop/mobile widths for UI
changes, including keyboard focus, labels, overflow, and honest feedback.
Mock translation in workflow/browser tests; verify actual subprocess execution
where practical. Check session ownership, expiration, CSRF, duplicate requests,
safe errors, and download response headers in integration tests.
Do not claim behavior works without verifying it; report verification limits.

## Security and scope

Load the root `.env` with python-dotenv without overriding process environment
variables. Require a secret from the environment; never commit credentials or
provide a built-in secret. Default debug off and restrict allowed hosts. Preserve
Django's CSRF protection, template autoescaping, and standard security middleware.
Treat submitted code as untrusted: never execute it in the Django process. The
execution service uses a temporary working directory, a reduced environment,
AST checks, bounded output/artifacts, and a child-process timeout. These are basic
safeguards, not a complete sandbox: the child retains the host user's permissions.
Do not expose arbitrary public execution without separately considering isolation.

Keep the existing single `core` app and simple server-rendered architecture.
Do not introduce DRF, React, Celery, Redis, pytest, additional Django apps, or
configuration packages. Keep translation independent of the homepage and
execution logic. Preserve its result dictionary (`success`, `python_code`,
`warnings`, `error`) so a native translator can later replace Groq internally.
Keep execution independent of Groq/MATLAB and preserve its result dictionary
(`success`, `figures`, `stdout`, `stderr`, `error`, `execution_time`). Figure
artifacts contain PNG bytes, filenames, and content types; temporary paths must
not survive a call. Export functions return the same `name`, `content_type`,
`data` artifact shape and raise clear exceptions on invalid inputs. Supported
exports are individual PNG/PDF/DOCX, combined PDF/DOCX, and generated Python.
Do not rerun source to export, add CSV/other formats, or store exports in the DB.
Keep orchestration in `workflow.py` and HTTP handling in views. Do not merge or
rewrite the three services to add web behavior. Preserve generated Python and
translation warnings when execution fails. Never send raw tracebacks, private
filesystem paths, owner tokens, or credentials to the frontend.

Results live under `.cache/executions/`, outside media/static. Django sessions
store only an opaque owner token and last execution ID, never generated code or
images. Every file read checks ownership and expiration. PNG bytes are stored
once; JSON metadata contains no image data. Publish only fully written runs using
an atomic rename. Run locks use exclusive file creation. Cleanup removes expired
runs on access/new runs; schedule `cleanup_artifacts` when idle cleanup is needed.
Current scope excludes authentication, accounts, saved plots, and execution history.
