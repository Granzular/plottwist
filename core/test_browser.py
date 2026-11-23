"""Workspace checks using an installed Chromium browser and native DevTools.

No browser package is required. These tests skip when Node.js or a supported
browser is unavailable; PLOTTWIST_BROWSER can specify the browser executable.
"""

import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from types import SimpleNamespace
from unittest import SkipTest
from unittest.mock import patch

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import SimpleTestCase, override_settings
from docx import Document
from PIL import Image
from pypdf import PdfReader


def _browser_executable():
    candidates = [os.environ.get('PLOTTWIST_BROWSER')]
    candidates.extend(shutil.which(name) for name in (
        'msedge', 'chrome', 'chromium', 'chromium-browser', 'google-chrome',
    ))
    for variable in ('PROGRAMFILES(X86)', 'PROGRAMFILES', 'LOCALAPPDATA'):
        root = os.environ.get(variable)
        if root:
            candidates.extend(str(Path(root) / relative) for relative in (
                'Microsoft/Edge/Application/msedge.exe',
                'Google/Chrome/Application/chrome.exe',
            ))
    candidates.extend((
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    ))
    return next((path for path in candidates if path and Path(path).is_file()), None)


def _translation(source):
    """Mock translation only; the workflow still executes a real Python child."""
    marker = source.strip()
    if marker == 'FAIL_TRANSLATION':
        return {
            'success': False, 'python_code': '', 'warnings': [],
            'error': 'Translation test failure.',
        }
    if marker == 'FAIL_EXECUTION':
        code = 'print("Before failure")\nraise ValueError("DSP test failure")\n'
    elif marker == 'NO_FIGURES':
        code = 'print("Completed without plots")\n'
    else:
        count = 2 if marker == 'TWO_FIGURES' else 5
        code = (
            'import matplotlib.pyplot as plt\n'
            f'sizes = [(4.8, 2.4), (2.4, 3.2), (5.2, 2.6), (3.6, 3.6), (3.2, 2.4)][:{count}]\n'
            'for index, size in enumerate(sizes, start=1):\n'
            '    plt.figure(figsize=size)\n'
            '    plt.plot([0, 1, 2], [index, 0, index])\n'
            '    plt.title(f"Figure {index}")\n'
            '    plt.xlabel("Sample")\n'
            '    plt.ylabel("Amplitude")\n'
            '    plt.grid(True)\n'
            '    plt.tight_layout()\n'
            f'print("{count} figures generated")\n'
            '# Long code lines must scroll inside the Python panel: ' + 'x' * 600 + '\n'
        )
    return {
        'success': True, 'python_code': code,
        'warnings': ['MATLAB indexing is converted to zero-based indexing.'],
        'error': None,
    }


class WorkspaceBrowserTests(StaticLiveServerTestCase):
    @classmethod
    def _make_connections_override(cls):
        overrides = super()._make_connections_override()
        for alias, connection in list(overrides.items()):
            name = str(connection.settings_dict['NAME'])
            if (
                name.startswith('file:')
                and 'mode=memory' in name
                and 'cache=shared' in name
            ):
                # The URI shares the fixture database, so request threads can
                # use separate connections. Sharing one connection caused
                # SQLite API errors and failed concurrent figure/session reads.
                del overrides[alias]
        return overrides

    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which('node')
        cls.browser = _browser_executable()
        if not cls.node or not cls.browser:
            raise SkipTest('Workspace browser checks need Node.js and an installed Chromium browser.')
        version = subprocess.run([cls.node, '--version'], capture_output=True, text=True, timeout=10)
        if version.returncode or int(version.stdout.strip().lstrip('v').split('.')[0]) < 22:
            raise SkipTest('Workspace browser checks need Node.js 22 or newer for native WebSocket support.')
        super().setUpClass()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='plottwist-browser-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        override = override_settings(
            EXECUTION_ARTIFACT_ROOT=self.directory / 'artifacts',
            EXECUTION_TIMEOUT_SECONDS='60', ARTIFACT_TTL_SECONDS=900,
        )
        override.enable()
        self.addCleanup(override.disable)
        translated = patch('core.workflow.translate_matlab', side_effect=_translation)
        self.translate = translated.start()
        self.addCleanup(translated.stop)

        profile = self.directory / 'browser-profile'
        self.process = subprocess.Popen(
            [
                self.browser, '--headless=new', '--disable-gpu',
                '--remote-debugging-port=0', f'--user-data-dir={profile}',
                '--no-first-run', '--no-default-browser-check',
                '--disable-background-networking', '--disable-component-update',
                '--disable-sync', '--disable-extensions', 'about:blank',
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
        )
        self.addCleanup(self._stop_browser)
        deadline = time.monotonic() + 20
        port_file = profile / 'DevToolsActivePort'
        self.port = None
        while self.process.poll() is None and time.monotonic() < deadline:
            try:
                # Chromium briefly holds this file exclusively while writing it.
                lines = port_file.read_text().splitlines()
                if len(lines) >= 2 and lines[0].isdigit():
                    self.port = int(lines[0])
                    break
            except OSError:
                pass
            time.sleep(0.1)
        self.assertIsNotNone(self.port, 'The browser did not open a DevTools port.')

    def _stop_browser(self):
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=10)

    def test_workspace_selection_downloads_and_responsive_layout(self):
        downloads = self.directory / 'downloads'
        downloads.mkdir()
        result = subprocess.run(
            [
                self.node, str(Path(__file__).with_name('browser_tests.cjs')),
                self.live_server_url, str(self.port), str(downloads),
            ],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.translate.call_count, 5)

        # Inspect files produced by actual checkbox form submissions in the browser.
        expected_sizes = [(480, 240), (520, 260), (320, 240)]
        pages = PdfReader(downloads / 'charts.pdf', strict=True).pages
        sizes = []
        for page in pages:
            drawn = [args[0] for args, op in page.get_contents().operations if op == b'Do']
            self.assertEqual(len(drawn), 1)
            sizes.append(page.images[drawn[0]].image.size)
        self.assertEqual(sizes, expected_sizes)
        document = Document(downloads / 'charts.docx')
        sizes = []
        for shape in document.inline_shapes:
            relationship = shape._inline.xpath('.//a:blip/@r:embed')[0]
            with Image.open(io.BytesIO(document.part.related_parts[relationship].blob)) as image:
                sizes.append(image.size)
        self.assertEqual(sizes, expected_sizes)
        print(result.stdout.strip())


class BrowserConnectionTests(SimpleTestCase):
    def test_shared_memory_uri_uses_per_thread_connections(self):
        connection = SimpleNamespace(settings_dict={
            'NAME': 'file:memorydb_default?mode=memory&cache=shared',
        })
        with patch.object(
            StaticLiveServerTestCase, '_make_connections_override',
            return_value={'default': connection},
        ):
            self.assertEqual(
                WorkspaceBrowserTests._make_connections_override(), {},
            )

    def test_plain_memory_database_keeps_django_connection_sharing(self):
        connection = SimpleNamespace(settings_dict={'NAME': ':memory:'})
        with patch.object(
            StaticLiveServerTestCase, '_make_connections_override',
            return_value={'default': connection},
        ):
            self.assertEqual(
                WorkspaceBrowserTests._make_connections_override(),
                {'default': connection},
            )
