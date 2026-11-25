"""Public pages and tour checks with Chromium and Python's standard library.

No Node.js or browser package is required. Translation is mocked; execution
and export requests use the existing services. Set PLOTTWIST_PUBLIC_SCREENSHOTS
to retain review images, or PLOTTWIST_BROWSER to choose a Chromium executable.
"""

import base64
import io
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import time
from unittest import SkipTest
from unittest.mock import patch
from urllib.parse import urlparse
from urllib.request import urlopen

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from docx import Document
from PIL import Image
from pypdf import PdfReader

from .test_browser import _browser_executable, _translation
from .test_public import TEST_STORAGES


class _DevTools:
    """The small WebSocket subset needed to drive an installed browser."""

    def __init__(self, url):
        parsed = urlparse(url)
        self.socket = socket.create_connection((parsed.hostname, parsed.port), timeout=20)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f'GET {parsed.path} HTTP/1.1\r\nHost: {parsed.netloc}\r\n'
            'Upgrade: websocket\r\nConnection: Upgrade\r\n'
            f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n'
        )
        self.socket.sendall(request.encode())
        headers = b''
        while not headers.endswith(b'\r\n\r\n'):
            headers += self._exact(1)
        if not headers.startswith(b'HTTP/1.1 101 '):
            raise RuntimeError('The browser rejected the DevTools connection.')
        self.number = 0
        self.events = []

    def _exact(self, count):
        data = b''
        while len(data) < count:
            chunk = self.socket.recv(count - len(data))
            if not chunk:
                raise EOFError('The DevTools connection closed.')
            data += chunk
        return data

    def _send(self, data, opcode=1):
        mask = os.urandom(4)
        size = len(data)
        header = bytes([0x80 | opcode])
        if size < 126:
            header += bytes([0x80 | size])
        elif size < 65536:
            header += bytes([0x80 | 126]) + struct.pack('!H', size)
        else:
            header += bytes([0x80 | 127]) + struct.pack('!Q', size)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(data))
        self.socket.sendall(header + mask + masked)

    def _receive(self):
        message = b''
        while True:
            flags, length = self._exact(2)
            size = length & 127
            if size == 126:
                size = struct.unpack('!H', self._exact(2))[0]
            elif size == 127:
                size = struct.unpack('!Q', self._exact(8))[0]
            mask = self._exact(4) if length & 128 else None
            data = self._exact(size)
            if mask:
                data = bytes(value ^ mask[index % 4] for index, value in enumerate(data))
            opcode = flags & 15
            if opcode == 9:
                self._send(data, opcode=10)
                continue
            if opcode == 8:
                raise EOFError('The DevTools connection closed.')
            message += data
            if flags & 128:
                return json.loads(message)

    def call(self, method, **params):
        self.number += 1
        number = self.number
        self._send(json.dumps({'id': number, 'method': method, 'params': params}).encode())
        while True:
            response = self._receive()
            if response.get('id') == number:
                if 'error' in response:
                    raise RuntimeError(response['error'])
                return response.get('result', {})
            if 'method' in response:
                self.events.append(response)

    def evaluate(self, expression):
        result = self.call(
            'Runtime.evaluate', expression=expression, awaitPromise=True,
            returnByValue=True, userGesture=True,
        )
        if 'exceptionDetails' in result:
            raise AssertionError(result['exceptionDetails'])
        return result['result'].get('value')

    def close(self):
        self.socket.close()


@override_settings(STORAGES=TEST_STORAGES)
class PublicWebsiteBrowserTests(StaticLiveServerTestCase):
    @classmethod
    def _make_connections_override(cls):
        overrides = super()._make_connections_override()
        for alias, connection in list(overrides.items()):
            name = str(connection.settings_dict['NAME'])
            if name.startswith('file:') and 'mode=memory' in name and 'cache=shared' in name:
                # Use per-thread connections to Django's shared test database.
                del overrides[alias]
        return overrides

    @classmethod
    def setUpClass(cls):
        cls.browser = _browser_executable()
        if not cls.browser:
            raise SkipTest('Public browser checks need an installed Chromium browser.')
        super().setUpClass()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='plottwist-public-browser-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        settings = override_settings(
            EXECUTION_ARTIFACT_ROOT=self.directory / 'artifacts',
            ARTIFACT_TTL_SECONDS=900, EXECUTION_TIMEOUT_SECONDS='60',
        )
        settings.enable()
        self.addCleanup(settings.disable)
        translation = patch('core.workflow.translate_matlab', side_effect=_translation)
        self.translate = translation.start()
        self.addCleanup(translation.stop)
        profile = self.directory / 'profile'
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
        port = None
        while self.process.poll() is None and time.monotonic() < deadline:
            try:
                lines = (profile / 'DevToolsActivePort').read_text().splitlines()
                if lines and lines[0].isdigit():
                    port = int(lines[0])
                    break
            except OSError:
                pass
            time.sleep(.1)
        self.assertIsNotNone(port, 'The browser did not open a DevTools port.')
        with urlopen(f'http://127.0.0.1:{port}/json/list', timeout=10) as response:
            tabs = json.load(response)
        tab = next(tab for tab in tabs if tab['type'] == 'page')
        self.devtools = _DevTools(tab['webSocketDebuggerUrl'])
        for domain in ('Page', 'Runtime', 'Network'):
            self.devtools.call(f'{domain}.enable')

    def _stop_browser(self):
        if hasattr(self, 'devtools'):
            try:
                self.devtools.call('Browser.close')
            except (OSError, EOFError):
                pass
            finally:
                self.devtools.close()
        if self.process.poll() is None:
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=10)

    def _wait(self, expression, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.devtools.evaluate(expression):
                return
            time.sleep(.1)
        self.fail(f'Browser condition did not become true: {expression}')

    def _viewport(self, width, height=900, mobile=False, scale=1):
        self.devtools.call(
            'Emulation.setDeviceMetricsOverride', width=width, height=height,
            deviceScaleFactor=scale, mobile=mobile,
        )

    def _navigate(self, path):
        marker = str(time.monotonic_ns())
        self.devtools.evaluate(f'window.__publicNavigationMarker = {json.dumps(marker)}')
        self.devtools.call('Page.navigate', url=self.live_server_url + path)
        self._wait(
            f'window.__publicNavigationMarker !== {json.dumps(marker)} '
            f'&& location.pathname === {json.dumps(path)} && document.readyState === "complete"'
        )
        self.devtools.call('Page.bringToFront')
        self.devtools.evaluate('document.querySelectorAll("img").forEach(img => img.loading = "eager")')
        self._wait('[...document.images].every(image => image.complete && image.naturalWidth > 0)')

    def _key(self, key, code, number, shift=False):
        for kind in ('keyDown', 'keyUp'):
            character = '\r' if key == 'Enter' else ' ' if key == ' ' else ''
            self.devtools.call(
                'Input.dispatchKeyEvent', type=kind, key=key, code=code,
                windowsVirtualKeyCode=number, modifiers=8 if shift else 0,
                text=character if kind == 'keyDown' else '',
            )

    def _click(self, selector):
        point = self.devtools.evaluate(f'''(() => {{
            const element = document.querySelector({json.dumps(selector)});
            element.scrollIntoView({{block: 'center', behavior: 'instant'}});
            const rect = element.getBoundingClientRect();
            return {{x: rect.x + rect.width / 2, y: rect.y + rect.height / 2}};
        }})()''')
        # Let any anchored tour panel follow the scroll before hit testing.
        self.devtools.evaluate('new Promise(resolve => requestAnimationFrame(resolve))')
        self.devtools.call('Input.dispatchMouseEvent', type='mouseMoved', **point)
        self.devtools.call('Input.dispatchMouseEvent', type='mousePressed', button='left', clickCount=1, **point)
        self.devtools.call('Input.dispatchMouseEvent', type='mouseReleased', button='left', clickCount=1, **point)

    def _capture(self, name, full=False):
        directory = os.environ.get('PLOTTWIST_PUBLIC_SCREENSHOTS')
        if not directory:
            return
        destination = Path(directory).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        params = {'format': 'png', 'captureBeyondViewport': full}
        if full:
            size = self.devtools.call('Page.getLayoutMetrics')['cssContentSize']
            params['clip'] = {**size, 'scale': 1}
        image = self.devtools.call('Page.captureScreenshot', **params)
        (destination / f'{name}.png').write_bytes(base64.b64decode(image['data']))

    def _assert_layout(self, label):
        layout = self.devtools.evaluate('''(() => ({
            width: innerWidth, pageWidth: document.scrollingElement.scrollWidth,
            headings: document.querySelectorAll('h1').length,
            images: [...document.images].map(image => {
                const rect = image.getBoundingClientRect();
                return {width: rect.width, height: rect.height,
                    naturalWidth: image.naturalWidth, naturalHeight: image.naturalHeight};
            }),
            buttons: [...document.querySelectorAll('.site-button')].map(button => ({
                height: button.getBoundingClientRect().height,
                width: button.getBoundingClientRect().width,
            })),
            body: {background: getComputedStyle(document.body).backgroundColor,
                font: getComputedStyle(document.body).fontFamily}
        }))()''')
        self.assertLessEqual(layout['pageWidth'], layout['width'], label)
        self.assertEqual(layout['headings'], 1, label)
        self.assertEqual(layout['body']['background'], 'rgb(250, 250, 248)')
        for image in layout['images']:
            self.assertGreater(image['naturalWidth'], 0, label)
            self.assertAlmostEqual(
                image['width'] / image['height'],
                image['naturalWidth'] / image['naturalHeight'], delta=.01, msg=label,
            )
        for button in layout['buttons']:
            self.assertGreaterEqual(button['height'], 44, label)

    def _assert_no_script_or_static_errors(self):
        errors = [event for event in self.devtools.events if event['method'] == 'Runtime.exceptionThrown']
        self.assertEqual(errors, [])
        static_errors = [
            event['params']['response'] for event in self.devtools.events
            if event['method'] == 'Network.responseReceived'
            and '/static/' in event['params']['response']['url']
            and event['params']['response']['status'] >= 400
        ]
        self.assertEqual(static_errors, [])

    def test_landing_workspace_route_navigation(self):
        self._viewport(1280)
        self._navigate('/')
        self.assertTrue(self.devtools.evaluate('!!document.querySelector("#hero-heading")'))
        self.assertFalse(self.devtools.evaluate('!!document.querySelector("#run-form")'))
        self.assertEqual(self.devtools.evaluate(
            'document.querySelector("#site-links [aria-current=page]").getAttribute("href")'
        ), '/')

        for selector in ('.hero-actions .site-button', '#site-links a[href="/workspace/"]'):
            with self.subTest(link=selector):
                self._click(selector)
                self._wait('location.pathname === "/workspace/" && !!document.querySelector("#run-form")')
                self.assertEqual(self.devtools.evaluate(
                    'document.querySelector("#site-links [aria-current=page]").getAttribute("href")'
                ), '/workspace/')
                self._click('.site-wordmark')
                self._wait('location.pathname === "/" && !!document.querySelector("#hero-heading")')

        self.assertEqual(self.translate.call_count, 0)
        self._assert_no_script_or_static_errors()

    def test_public_pages_responsive_navigation_assets_and_no_javascript(self):
        widths = [('desktop', 1280, 900, False, 1), ('tablet', 768, 1024, False, 1),
                  ('mobile', 360, 800, True, 1), ('zoom', 640, 450, False, 2)]
        for label, width, height, mobile, scale in widths:
            self._viewport(width, height, mobile, scale)
            for path in ('/', '/guide/', '/about/', '/contact/', '/privacy/', '/terms/'):
                with self.subTest(width=width, page=path):
                    self._navigate(path)
                    self._assert_layout(label + path)
                    self.devtools.evaluate('window.scrollTo(0, 0)')
                    if path in ('/', '/guide/', '/contact/'):
                        self._capture((path.strip('/') or 'home') + '-' + label, full=True)
                    if path == '/':
                        self._capture(f'home-{label}-hero')
                    self.assertEqual(self.devtools.evaluate(
                        '[...document.querySelectorAll("#site-links a")].map(a => a.textContent)'
                    ), ['Home', 'Workspace', 'User Guide', 'About', 'Contact'])
                    if width < 768:
                        self.assertTrue(self.devtools.evaluate('document.querySelector("#site-links").hidden'))
                        self.devtools.evaluate('document.querySelector("#site-menu-toggle").focus()')
                        self._key('Enter', 'Enter', 13)
                        self._wait('!document.querySelector("#site-links").hidden', timeout=5)
                        self.assertFalse(self.devtools.evaluate('document.querySelector("#site-links").hidden'))
                        self.assertEqual(self.devtools.evaluate(
                            'getComputedStyle(document.activeElement).outlineWidth'
                        ), '2px')
                        self._key('Escape', 'Escape', 27)
                        self.assertEqual(self.devtools.evaluate('document.activeElement.id'), 'site-menu-toggle')
                        self.assertTrue(self.devtools.evaluate('document.querySelector("#site-links").hidden'))

        self._viewport(1280)
        self._navigate('/')
        self._key('Tab', 'Tab', 9)
        self.assertEqual(self.devtools.evaluate('document.activeElement.textContent'), 'Skip to content')
        self.assertEqual(self.devtools.evaluate('getComputedStyle(document.activeElement).zIndex'), '100')
        self._key('Enter', 'Enter', 13)
        self.assertEqual(self.devtools.evaluate('document.activeElement.id'), 'main-content')
        self._click('.hero-actions .site-button')
        self._wait('location.pathname === "/workspace/" && !!document.querySelector("#run-form")')
        self.assertEqual(self.translate.call_count, 0)

        self._viewport(360, 800, True)
        self.devtools.call('Emulation.setScriptExecutionDisabled', value=True)
        self._navigate('/')
        self.assertFalse(self.devtools.evaluate('document.querySelector("#site-links").hidden'))
        self.assertTrue(self.devtools.evaluate('document.querySelector("#site-menu-toggle").hidden'))
        self._assert_layout('no JavaScript home')
        self._capture('home-mobile-no-javascript')
        self._navigate('/guide/')
        self.devtools.evaluate('document.querySelector("#troubleshooting details summary").click()')
        self.assertTrue(self.devtools.evaluate('document.querySelector("#troubleshooting details").open'))
        self._assert_no_script_or_static_errors()
        print('Public browser exercised all six pages at desktop/tablet/mobile/zoom widths, assets, keyboard navigation, CTA, and no-JavaScript navigation.')

    def _assert_tour(self, step):
        state = self.devtools.evaluate('''(() => {
            const panel = document.querySelector('#workspace-tour');
            const rect = panel.getBoundingClientRect();
            return {hidden: panel.hidden, step: Number(panel.dataset.step),
                highlights: document.querySelectorAll('.tour-highlight').length,
                left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom,
                width: innerWidth, height: innerHeight,
                modal: panel.getAttribute('aria-modal')};
        })()''')
        self.assertFalse(state['hidden'])
        self.assertEqual(state['step'], step)
        self.assertEqual(state['highlights'], 1)
        self.assertEqual(state['modal'], 'false')
        self.assertGreaterEqual(state['left'], 0)
        self.assertGreaterEqual(state['top'], 0)
        self.assertLessEqual(state['right'], state['width'])
        self.assertLessEqual(state['bottom'], state['height'])

    def _run(self, source):
        self.assertTrue(self.devtools.evaluate(f'''
            document.querySelector('#matlab-code').value = {json.dumps(source)};
            document.querySelector('#run-form').requestSubmit();
            document.querySelector('#run-button').disabled;
        '''))
        self.assertTrue(self.devtools.evaluate('document.querySelector("#matlab-code").readOnly'))
        self.assertTrue(self.devtools.evaluate('document.querySelector("#clear-source").disabled'))
        self._wait('!document.querySelector("#run-button").disabled', timeout=90)
        self.assertFalse(self.devtools.evaluate('document.querySelector("#matlab-code").readOnly'))
        self.devtools.evaluate('document.querySelectorAll("img").forEach(image => image.loading = "eager")')
        self._wait('[...document.images].every(image => image.complete && image.naturalWidth > 0)')

    def test_tour_navigation_persistence_replay_live_results_and_fallbacks(self):
        self._viewport(1280)
        self._navigate('/workspace/')
        self._wait('!document.querySelector("#tour-replay").hidden')
        original_source = self.devtools.evaluate('document.querySelector("#matlab-code").value')
        self.assertFalse(self.devtools.evaluate('document.querySelector("#tour-invitation").hidden'))
        self.assertTrue(self.devtools.evaluate('document.querySelector("#workspace-tour").hidden'))
        self.devtools.evaluate('document.querySelector("[data-tour-start]").focus()')
        self._key('Enter', 'Enter', 13)
        self._wait('!document.querySelector("#workspace-tour").hidden', timeout=5)
        self._assert_tour(1)
        self.assertEqual(self.devtools.evaluate('document.activeElement.id'), 'tour-title')
        self._key('Tab', 'Tab', 9)
        self._key('Tab', 'Tab', 9)
        self.assertEqual(self.devtools.evaluate('document.activeElement.id'), 'tour-next')
        self.assertEqual(self.devtools.evaluate('getComputedStyle(document.activeElement).outlineWidth'), '2px')
        self._key('Enter', 'Enter', 13)
        self._assert_tour(2)
        self._click('#tour-next')
        self._assert_tour(3)
        self._click('#tour-back')
        self._assert_tour(2)
        self._click('#tour-back')
        self._assert_tour(1)
        self.assertEqual(self.devtools.evaluate('document.activeElement.id'), 'tour-next')
        # The source remains accessible while the nonmodal tour is open.
        self.devtools.evaluate('document.querySelector("#matlab-code").focus()')
        self.assertEqual(self.devtools.evaluate('document.activeElement.id'), 'matlab-code')
        self.assertFalse(self.devtools.evaluate('document.querySelector("#matlab-code").readOnly'))
        for step in range(2, 8):
            self._click('#tour-next')
            self._assert_tour(step)
        self.assertEqual(self.devtools.evaluate('document.querySelector("#matlab-code").value'), original_source)
        self.assertIn('When figures are available', self.devtools.evaluate('document.querySelector("#tour-text").textContent'))
        self._capture('tour-empty-exports')

        # A real run can finish during the tour. Highlight the new export controls.
        self._run('TWO_FIGURES')
        self._assert_tour(7)
        self.assertTrue(self.devtools.evaluate(
            'document.querySelector("[aria-label=\\"Export selected figures\\"]").classList.contains("tour-highlight")'
        ))
        self.assertEqual(self.devtools.evaluate('document.querySelectorAll("input[name=indices]:checked").length'), 2)
        self.assertFalse(self.devtools.evaluate('document.querySelector("#python-code").isContentEditable'))
        self._click('#tour-back')
        self._assert_tour(6)
        self._click('#figure-select-0')
        self.assertEqual(self.devtools.evaluate('document.querySelector("#selection-count").textContent'), '1 of 2 selected')
        self._click('#tour-next')
        self._capture('tour-live-exports')
        self._click('#tour-next')
        self.assertTrue(self.devtools.evaluate('document.querySelector("#workspace-tour").hidden'))
        self.assertEqual(self.devtools.evaluate('localStorage.getItem("plottwist.workspaceTour.v1")'), 'completed')

        # Native export forms still use the checked subset after finishing the tour.
        downloads = self.directory / 'downloads'
        downloads.mkdir()
        self.devtools.call('Browser.setDownloadBehavior', behavior='allow', downloadPath=str(downloads))
        for format in ('pdf', 'docx'):
            self._click(f'[data-combined-export][formaction$="/{format}/"]')
            deadline = time.monotonic() + 30
            while not (downloads / f'charts.{format}').exists() and time.monotonic() < deadline:
                time.sleep(.1)
            self.assertTrue((downloads / f'charts.{format}').is_file())
        pages = PdfReader(downloads / 'charts.pdf', strict=True).pages
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].images[0].image.size, (240, 320))
        document = Document(downloads / 'charts.docx')
        self.assertEqual(len(document.inline_shapes), 1)
        relationship = document.inline_shapes[0]._inline.xpath('.//a:blip/@r:embed')[0]
        with Image.open(io.BytesIO(document.part.related_parts[relationship].blob)) as image:
            self.assertEqual(image.size, (240, 320))
        checks = self.devtools.evaluate('''(async () => {
            const links = [document.querySelector('#matlab-download'),
                document.querySelector('#python-panel .download-link'),
                document.querySelector('[data-figure-index="0"] .download-link')];
            const output = [];
            document.querySelector('#matlab-code').value = '% unsubmitted changes';
            for (const link of links) {
                const response = await fetch(link.href);
                const data = await response.arrayBuffer();
                output.push({status: response.status,
                    disposition: response.headers.get('Content-Disposition'),
                    bytes: data.byteLength,
                    text: link.id === 'matlab-download' ? new TextDecoder().decode(data) : null});
            }
            return output;
        })()''')
        for check in checks:
            self.assertEqual(check['status'], 200)
            self.assertIn('attachment', check['disposition'])
            self.assertGreater(check['bytes'], 0)
        self.assertEqual(checks[0]['text'], 'TWO_FIGURES')
        self.assertEqual(self.translate.call_count, 1)

        self._navigate('/workspace/')
        self.assertTrue(self.devtools.evaluate('document.querySelector("#tour-invitation").hidden'))
        for width, height, mobile in ((1280, 900, False), (768, 1024, False), (360, 800, True), (640, 450, False)):
            self._viewport(width, height, mobile)
            layout = self.devtools.evaluate('''(() => {
                const box = selector => document.querySelector(selector).getBoundingClientRect().toJSON();
                return {pageWidth: document.scrollingElement.scrollWidth, source: box('#run-form'),
                    python: box('#python-panel'), figures: box('#figure-workspace'), command: box('#command-panel')};
            })()''')
            self.assertLessEqual(layout['pageWidth'], width)
            if width >= 1024:
                self.assertEqual(layout['source']['top'], layout['python']['top'])
                self.assertGreater(layout['python']['left'], layout['source']['left'])
            else:
                self.assertGreaterEqual(layout['python']['top'], layout['source']['bottom'])
            self.assertGreaterEqual(layout['figures']['top'], layout['python']['bottom'])
            self.assertGreaterEqual(layout['command']['top'], layout['figures']['bottom'])
            self._click('#tour-replay')
            for step in range(1, 8):
                self._assert_tour(step)
                if step < 7:
                    self._click('#tour-next')
            self._capture(f'tour-{width}')
            self._key('Escape', 'Escape', 27)
            self.assertTrue(self.devtools.evaluate('document.querySelector("#workspace-tour").hidden'))
            self.assertEqual(self.devtools.evaluate('document.activeElement.id'), 'tour-replay')
        self.assertEqual(self.devtools.evaluate('localStorage.getItem("plottwist.workspaceTour.v1")'), 'dismissed')
        self._navigate('/workspace/')
        self.assertTrue(self.devtools.evaluate('document.querySelector("#tour-invitation").hidden'))

        # Closing from every step remains available; no tour overlay traps focus.
        self._viewport(1280)
        for stop_at in range(1, 8):
            self._click('#tour-replay')
            for _ in range(1, stop_at):
                self._click('#tour-next')
            self._click('#workspace-tour [data-tour-dismiss]')
            self.assertTrue(self.devtools.evaluate('document.querySelector("#workspace-tour").hidden'))
            self.assertEqual(self.devtools.evaluate('document.querySelectorAll(".tour-highlight").length'), 0)

        self.devtools.call('Emulation.setEmulatedMedia', features=[{'name': 'prefers-reduced-motion', 'value': 'reduce'}])
        self._click('#tour-replay')
        self.assertTrue(self.devtools.evaluate('matchMedia("(prefers-reduced-motion: reduce)").matches'))
        self.assertEqual(self.devtools.evaluate('getComputedStyle(document.documentElement).scrollBehavior'), 'auto')
        self._click('#tour-next')
        self._click('#tour-next')
        self._run('FAIL_EXECUTION')
        self._assert_tour(3)
        self.assertTrue(self.devtools.evaluate('document.querySelector("#command-panel").textContent.includes("Execution failed")'))
        self.assertTrue(self.devtools.evaluate('document.querySelector("#python-code").textContent.includes("raise ValueError")'))
        self._run('FAIL_TRANSLATION')
        self._assert_tour(3)
        self.assertTrue(self.devtools.evaluate('document.querySelector("#command-panel").textContent.includes("Translation failed")'))
        self._key('Escape', 'Escape', 27)

        # Blocked browser storage suppresses the invitation and preserves replay.
        injected = self.devtools.call('Page.addScriptToEvaluateOnNewDocument', source='''
            Object.defineProperty(window, 'localStorage', {get() { throw new DOMException('Blocked', 'SecurityError'); }});
        ''')['identifier']
        self._navigate('/workspace/')
        self.assertTrue(self.devtools.evaluate('document.querySelector("#tour-invitation").hidden'))
        self._click('#tour-replay')
        self._assert_tour(1)
        self._key('Escape', 'Escape', 27)
        self.devtools.call('Page.removeScriptToEvaluateOnNewDocument', identifier=injected)

        self.devtools.call('Emulation.setScriptExecutionDisabled', value=True)
        self._navigate('/workspace/')
        self.assertTrue(self.devtools.evaluate('document.querySelector("#tour-replay").hidden'))
        self.assertTrue(self.devtools.evaluate('document.querySelector("#tour-invitation").hidden'))
        self.devtools.evaluate('document.querySelector("#matlab-code").value = "NO_FIGURES"; document.querySelector("#run-form").requestSubmit()')
        self._wait('location.pathname === "/run/" && document.readyState === "complete"', timeout=90)
        self.assertTrue(self.devtools.evaluate('document.querySelector("#results").textContent.includes("Execution completed without figures")'))
        self._assert_no_script_or_static_errors()
        print('Tour browser exercised seven steps, keyboard/back/dismiss/finish, persistence/replay, responsive placement, live subprocess results, native subset exports, failure states, blocked storage, reduced motion, and no-JavaScript Run.')
