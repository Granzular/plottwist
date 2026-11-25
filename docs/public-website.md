# Public website, user guide, and workspace tour

Implemented 25 November 2026. The public website introduces the existing DSP
workspace. It does not add a translation engine, numerical service, account,
database model, analytics system, or contact backend.

## Routes and architecture

| Name | Path | Behavior |
| --- | --- | --- |
| `core:public_home` | `/` | Public landing page. |
| `core:home` | `/workspace/` | Existing workspace; Run behavior preserved. |
| `core:user_guide` | `/guide/` | User-facing guide with section anchors and screenshots. |
| `core:about` | `/about/` | Purpose, audience, and implementation approach. |
| `core:contact` | `/contact/` | Verified email and GitHub links; reporting guidance. |
| `core:privacy` | `/privacy/` | Current processing, storage, session, and provider behavior. |
| `core:terms` | `/terms/` | Educational use, review responsibilities, permissions, and limits. |

The public landing page is now at `/`, and the workspace is at `/workspace/`.
The former `/home/` route has been removed. Django redirects `/workspace` to
`/workspace/` using its existing trailing-slash convention. Route names are
retained: every Workspace link and primary CTA reverses `core:home`, while Home
and branding links reverse `core:public_home`. The Run, result-image, and download
routes are unchanged.

Static informational pages use Django `TemplateView`; guide and privacy views
only render templates with the relevant configured lifetime/timeout values.
Public visits do not create a workspace owner token or session cookie.

`templates/base.html` still provides the HTML shell, local stylesheet, favicon,
and skip link. Public templates inherit `core/public/base.html`; article pages
share `core/public/document.html`. Navigation and footer are single includes,
also used in compact form around the existing workspace. Public styles are
scoped to their own classes and retain the established fonts, colors, and borders.
Workspace code and result panel markup is preserved.

## Landing page and factual scope

Sections appear in the requested order: hero, directional workflow, implemented
capabilities, academic/DSP examples, limitations, final workspace CTA, and footer.
The workflow explicitly separates translation from Python execution despite the
single Run action. Available exports are individual PNG/PDF/DOCX, selected
combined PDF/DOCX, generated `.py`, and submitted `.m` source. Exports reuse PNGs
or stored text; no translation or execution is repeated.

`core/transpiler/__init__.py` exposes lexical analysis only. There is no native
translator integrated into `workflow.py`, no engine selector in the form, and
no translation engine field accepted by `views.run`. Consequently, there is
no public alternative-engines section or tour step for engine selection.
The guide describes Groq and its instructed numerical scope without promising
an exhaustive MATLAB compatibility list, semantic equivalence, or universal
toolbox support.

Contact uses `mailto:ayenimichael92@gmail.com` and
`https://github.com/Granzular`. The GitHub link leads to the supplied profile;
the contact page does not invent a repository-specific issue endpoint.

## Existing product images

| Asset | Dimensions | Use |
| --- | --- | --- |
| `static/media/screenshot-1.PNG` | 1366 × 659 | Hero editor/Python preview and MATLAB guide section. |
| `static/media/screenshot-2.PNG` | 1366 × 641 | Hero figures preview, DSP example, and figure guide section. |
| `static/media/screenshot-3.PNG` | 1295 × 217 | Workflow output preview and command-window guide section. |

The uppercase `.PNG` extensions are intentional and needed on case-sensitive
hosts. The supplied files are referenced with Django's `static` tag, keep their
original bytes and proportions, and offer full-size image links. Small previews
are supported by readable captions and full-size inspection. No replacement
product screenshots, standalone plot images, stock visuals, or remote fonts are
introduced. `.gitignore` allows only these three supplied screenshots beneath
`static/media/`; generated root `media/` remains ignored.

## Practical guide

The guide covers opening the workspace, sample MATLAB, source size, Run stages,
provider involvement, read-only Python, plots/subplots and creation order,
command output, translation warnings, stage-specific failures, figure selection,
individual and combined exports, source downloads, compatibility, and common
problems. It explains that unsent editor changes do not change the displayed
run's MATLAB download. Translation failures without Python create no new stored
run, while execution failures can retain Python, warnings, and source downloads.

Runtime/retention values come from settings. Fixed limits documented from
`execution.py` and `_execution_runner.py` include 64 KiB source and each output
stream, 20 figures, 5 MiB per PNG, 20 MiB total PNGs, and 4 million rendered
pixels per figure. DOCX page breaks are implemented, but final pagination can
depend on the word processor.

## Optional interactive tour

`workspace-tour.js` is independent of `workspace.js` and submits no requests.
An unobtrusive first-use invitation offers Start tour or Dismiss; it does not
automatically open a dialog. The Workspace tour button is always available
after initialization. The seven steps cover:

1. Editable MATLAB source.
2. Run, Groq translation, and separate Python execution.
3. Read-only Python and source downloads.
4. Generated figures.
5. Command output, warnings, and stage errors.
6. Figure selection.
7. Individual and combined export controls.

The tour uses one contextual outline and a small nonmodal dialog. Back, Next,
Finish, close, and Escape are supported; the workspace is not made inert and
keyboard focus is not trapped. Opening moves focus to the title; closing returns
it to the replay/launch control. Positioning keeps the panel in the viewport,
and scrolling between steps is immediate. Reduced-motion styles suppress
transitions/animations.

Before there are figures, selection/export steps highlight the existing Figures
area and explicitly describe controls that appear after a plotting run. They
do not fabricate result cards or controls. A mutation observer resolves fresh
elements after the existing Run script replaces results, retaining the current
step and updating its explanation without registering workflow handlers.

`localStorage['plottwist.workspaceTour.v1']` stores only `completed` or `dismissed`.
Neither source nor result data goes into local storage. If storage access is
blocked, the invitation stays hidden and manual replay still works. If storage
is cleared, a first-use invitation can appear again. Failure or absence of tour
JavaScript leaves the native workspace form and result/download behavior usable.

Mobile navigation is a separate small script. Links remain visible without
JavaScript; with it, a semantic button toggles them and Escape restores focus.
Guide contents and troubleshooting disclosures work without JavaScript.

## Privacy and Terms audit

| Area | Verified implementation and policy consequence |
| --- | --- |
| Groq | `translation.py` sends the full MATLAB source as the user message plus fixed instructions after validation. Comments and strings are included. Stored figures and execution output are not in that request. Provider retention is not controlled by this app. |
| Configuration | Root dotenv does not override process variables. Groq credentials/model/timeouts are server configuration. PostgreSQL can be configured, including an externally hosted database. Policies do not assume SQLite-only deployments or promise encryption for every connection. |
| Execution | `execution.py` runs a separate child with temporary source, reduced environment, AST checks, output/image limits, and timeout. `_execution_runner.py` captures PNGs. Managed calls attempt to remove temporary work directories; crashes and filesystem errors can interrupt cleanup. These guards are not a complete sandbox. |
| Temporary results | `views.run` saves when Python exists, including execution failure. `artifacts.py` writes source, Python, public warnings/output/errors, duration, created time, owner hash, and separate PNGs; publication uses a directory rename. |
| Ownership/expiry | Reads check owner and creation-time expiry. Access/new-run cleanup and `cleanup_artifacts` delete expired files. Without scheduled idle cleanup, inaccessible files may remain. Expiry is not an immediate-deletion guarantee. |
| Sessions/database | No application models or migrations are added. Workspace data in default database-backed Django sessions holds an opaque owner token and last-run ID, not source/images. Existing Django authentication/admin tables serve site administration, without workspace registration or code storage. Cookie names and lifetime come from settings; expired session-row deletion depends on Django session cleanup. |
| Browser state | Essential session/CSRF cookies and the tour's single local preference. No analytics or advertising tracker is introduced. |
| Logs/errors | Workflow logs exception class names for unexpected failures. Public diagnostic filtering recognizes certain private lines/credential patterns and omits raw execution tracebacks. It cannot prove removal of every sensitive value. Server/hosting logs and backups have deployment-dependent retention. |
| Exports | `exports.py` builds responses in memory from PNGs or text. Downloads do not become database records or rerun code; downloaded files remain on the user's device. |

Terms cover educational/course requirements, authority to submit code to Groq,
responsible execution, translation/numerical review, temporary availability,
source-license and ownership considerations, service changes, and contact.
No legal entity, address, certification, endorsement, adoption statistic,
third-party deletion policy, or blanket privacy/security guarantee is invented.

## Verification

Use the existing standalone Tailwind CLI after CSS/template changes:

```powershell
.\.tools\tailwindcss.exe -i ./static/css/input.css -o ./static/css/app.css --minify
```

If an existing watcher continues writing CSS compiled from older input, restart
it so the updated source is read. The output must contain the public and tour
styles as well as the existing workspace utilities.

Focused checks:

```bash
uv run --locked python manage.py check
uv run --locked python manage.py test core.test_public core.test_public_browser
uv run --locked python manage.py findstatic css/app.css js/navigation.js js/workspace-tour.js media/screenshot-1.PNG media/screenshot-2.PNG media/screenshot-3.PNG
```

`core.test_public_browser` uses Python's standard library and an installed
Chromium browser, with no Node.js or browser-package dependency. It mocks
translation and exercises real execution and PDF/DOCX exports. Tests explicitly
skip when no browser is available. `PLOTTWIST_BROWSER` can supply an executable;
`PLOTTWIST_PUBLIC_SCREENSHOTS` retains review images in a chosen local directory.

Verification completed locally with Python 3.13, SQLite test databases, and
installed Chromium (Microsoft Edge). The following 140-test sequential run passed:

```bash
uv run --locked python manage.py test core.tests core.transpiler.tests core.test_public core.test_public_browser core.test_browser.BrowserConnectionTests --verbosity 1 --failfast
```

System checks and static discovery passed. Tailwind was rebuilt using the
standalone v4.1.18 CLI, and `collectstatic --noinput` completed. A separate
production-mode check with the manifest storage and WhiteNoise rendered the
six public pages and workspace, fetched eight unique static assets, verified
their successful responses, compared served screenshots with the original
bytes, and confirmed public/tour styles in the served CSS. `git diff --check`
passed. No migration or dependency change was needed.

Browser verification covered all six public routes at 1280px desktop, 768px
tablet, 360px mobile, and a 640px viewport representing 200% desktop reflow.
It checked image proportions/loading, mobile menu keyboard activation and
Escape, skip-link focus, CTA navigation, guide disclosures without JavaScript,
and tour navigation/placement at every width. Workspace checks exercised real
Python execution, live result replacement, source preservation, read-only code,
checked figure selection, actual native subset PDF/DOCX downloads with document
inspection, execution/translation failures, completion/dismissal persistence,
replay, every-step close, blocked storage, reduced motion, and native Run without
JavaScript. Review captures are local under `.tools/public-site-review/` and are
not used as replacement product visuals.

An earlier run made concurrently with browser checks hit a held-open Windows
cache file in the existing `test_artifact_bytes_survive_temporary_directory_cleanup`.
That test passed in isolation and in the final sequential 140-test run.
The services and existing tests were not modified. The policy therefore describes
working-directory cleanup as an attempt that filesystem errors can interrupt.

Live Groq translation quality, third-party data practices, production hosting
or backup retention, other browser engines/screen readers, and complete execution
isolation were not verified by these local tests. The existing Node-based legacy
browser scenario was not invoked; the new browser coverage requires no Node.js.

## Files in this change

- `.gitignore`, `README.md`, `docs/public-website.md`.
- `core/urls.py`, `core/views.py`, `core/test_public.py`, `core/test_public_browser.py`.
- `templates/base.html`, `templates/core/home.html`.
- `templates/core/includes/navigation.html`, `footer.html`, `tour.html`.
- `templates/core/public/base.html`, `document.html`, `home.html`, `about.html`,
  `contact.html`, `guide.html`, `privacy.html`, `terms.html`.
- `static/css/input.css`, compiled `static/css/app.css`.
- `static/js/navigation.js`, `static/js/workspace-tour.js`.
- The three pre-existing `static/media/screenshot-1.PNG`, `screenshot-2.PNG`,
  `screenshot-3.PNG` are now allowed in version control; their image bytes are unchanged.

The original services, result routes, workflow script, dependencies, database
models, and migrations are unchanged. Existing workspace test entry paths were
updated for `/workspace/`. No commit, merge, or deployment is part of this work.

## Resumed review and pause

The saved session was resumed on 25 November 2026 with its final instruction,
"do not run any test. pause after changes," retained. The remaining review
compared the public templates, navigation, tour selectors, and guide/policy
content with the current routes, workflow, translation, execution, and artifact
code. This resume only reformatted the new static-page URL declarations and
updated this review record; no application behavior changed.
No CSS source or utility classes changed, so no stylesheet rebuild was needed.

No tests, browser checks, or Django system checks were run during this resume.
The verification results above belong to the saved session and do not represent
validation of this resumed work. Changes remain in the working tree for review,
with no commit, merge, or deployment. Work is paused after these edits.

## Landing page and workspace route change

On 25 November 2026, the requested route change moved the public landing page
from `/home/` to `/` and the workspace from `/` to `/workspace/`. The existing
named routes keep all navigation, footer branding, guide links, and workspace
CTAs pointed at their intended pages without template or CSS changes. Tests
now expect the new paths and require both `/home` and `/home/` to return 404.
The existing browser scenarios enter the workspace at `/workspace/`.

Seven explicitly selected Django tests passed in 15.226 seconds with SQLite:
public route/template responses without creating sessions, shared navigation
and footer links, landing-page CTAs and the `/workspace` redirect, removal of
both `/home` paths, workspace form/tour rendering, the existing workspace page
test, and the new `test_landing_workspace_route_navigation` browser test. The
browser test followed both the landing CTA and navigation link to `/workspace/`
and returned to `/` through the wordmark; translation was not invoked. Django's
system check reported no issues during this run.

The full suite, translation/execution/export tests, and broad responsive/tour
browser scenarios were not run for this change. No CSS rebuild was needed.
