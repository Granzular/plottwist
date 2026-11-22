import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import time
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

import httpx
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import resolve, reverse
from groq import (
    APIConnectionError,
    APIResponseValidationError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)
from groq.types.chat import ChatCompletion
from PIL import Image, ImageDraw
from pypdf import PdfReader
from docx import Document

from .translation import translate_matlab
from .execution import execute_python, MAX_OUTPUT_BYTES, MAX_SOURCE_BYTES
from .exports import export_figure, export_figures, export_python
from . import artifacts


class HomepageTests(TestCase):
    def test_homepage_renders_workspace(self):
        url = reverse('core:home')
        self.assertEqual(url, '/')
        self.assertEqual(resolve(url).view_name, 'core:home')

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/home.html')
        self.assertContains(response, 'plottwist')
        self.assertContains(response, 'MATLAB to Python. Code to plots.')
        self.assertContains(response, 'MATLAB code')
        self.assertContains(response, 'Generated Python')
        self.assertContains(response, 'Plots')


@override_settings(
    GROQ_API_KEY='test-api-key',
    GROQ_MODEL='test-model',
    GROQ_TIMEOUT_SECONDS='12.5',
    GROQ_RESPONSE_FORMAT='json_schema',
)
class TranslationTests(SimpleTestCase):
    def setUp(self):
        # Patch every test at the SDK boundary, including failure paths.
        groq_patch = patch('core.translation.Groq')
        self.groq = groq_patch.start()
        self.addCleanup(groq_patch.stop)
        self.client = self.groq.return_value.__enter__.return_value
        self.respond(json.dumps({'python_code': 'x = 1\n', 'warnings': []}))

    def respond(self, content, finish_reason='stop'):
        self.client.chat.completions.create.return_value = ChatCompletion(
            id='mock-completion',
            object='chat.completion',
            created=0,
            model='test-model',
            choices=[{
                'index': 0,
                'finish_reason': finish_reason,
                'message': {'role': 'assistant', 'content': content},
            }],
        )

    def assert_failed(self, result):
        self.assertEqual(set(result), {'success', 'python_code', 'warnings', 'error'})
        self.assertIs(result['success'], False)
        self.assertEqual(result['python_code'], '')
        self.assertIsInstance(result['warnings'], list)
        self.assertTrue(result['error'])

    def test_success_and_configurable_request(self):
        source = 'x = 1;\nplot(x);'
        code = 'import matplotlib.pyplot as plt\nx = 1\nplt.plot([x])\n'
        self.respond(json.dumps({'python_code': code, 'warnings': []}))

        result = translate_matlab(source)

        self.assertEqual(result, {
            'success': True, 'python_code': code, 'warnings': [], 'error': None,
        })
        self.groq.assert_called_once_with(
            api_key='test-api-key', timeout=12.5, max_retries=0,
        )
        request = self.client.chat.completions.create.call_args.kwargs
        self.assertEqual(request['model'], 'test-model')
        self.assertEqual(request['messages'][1], {'role': 'user', 'content': source})
        self.assertEqual(request['response_format']['type'], 'json_schema')
        schema = request['response_format']['json_schema']
        self.assertIs(schema['strict'], True)
        self.assertEqual(set(schema['schema']['required']), {'python_code', 'warnings'})
        self.assertIs(schema['schema']['additionalProperties'], False)

    @override_settings(GROQ_RESPONSE_FORMAT='json_object')
    def test_json_object_mode_keeps_the_same_validated_contract(self):
        self.assertTrue(translate_matlab('x = 1;')['success'])
        request = self.client.chat.completions.create.call_args.kwargs
        self.assertEqual(request['response_format'], {'type': 'json_object'})
        self.respond('{"python_code": "x = 1"}')
        self.assert_failed(translate_matlab('x = 1;'))

    def test_rejects_malformed_json_and_surrounding_prose(self):
        for content in (
            '', '{', '{"python_code": "x = 1", "warnings": [],}',
            '```json\n{"python_code": "x = 1", "warnings": []}\n```',
            'Here is the translation: {"python_code": "x = 1", "warnings": []}',
        ):
            with self.subTest(content=content):
                self.respond(content)
                result = translate_matlab('x = 1;')
                self.assert_failed(result)
                self.assertIn('invalid JSON', result['error'])

    def test_rejects_response_schema_violations(self):
        payloads = [
            None, [], 'x = 1', {},
            {'python_code': 'x = 1'},
            {'warnings': []},
            {'python_code': 'x = 1', 'warnings': [], 'extra': 'unexpected'},
            {'python_code': None, 'warnings': []},
            {'python_code': 123, 'warnings': []},
            {'python_code': 'x = 1', 'warnings': None},
            {'python_code': 'x = 1', 'warnings': 'warning'},
            {'python_code': 'x = 1', 'warnings': [123]},
            {'python_code': 'x = 1', 'warnings': ['']},
            {'python_code': 'x = 1', 'warnings': ['   ']},
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                self.respond(json.dumps(payload))
                self.assert_failed(translate_matlab('x = 1;'))

    def test_rejects_invalid_or_empty_generated_python(self):
        for code in (
            '', ' \t\n', '# Only a comment\n', 'def broken(', 'return 1',
            'break', 'await work()', '    x = 1', '```python\nx = 1\n```', '\x00',
        ):
            with self.subTest(code=code):
                self.respond(json.dumps({'python_code': code, 'warnings': []}))
                self.assert_failed(translate_matlab('x = 1;'))

    def test_preserves_translation_warnings(self):
        warnings = ['Column orientation is ambiguous.', 'Unsupported toolbox function.']
        self.respond(json.dumps({'python_code': 'x = 1\n', 'warnings': warnings}))
        result = translate_matlab('x = 1;')
        self.assertIs(result['success'], True)
        self.assertEqual(result['warnings'], warnings)

    def test_retains_warnings_when_no_usable_code_is_generated(self):
        warnings = ['The required toolbox operation is unsupported.']
        for code in ('', 'def broken('):
            with self.subTest(code=code):
                self.respond(json.dumps({'python_code': code, 'warnings': warnings}))
                result = translate_matlab('unsupported_toolbox(x);')
                self.assert_failed(result)
                self.assertEqual(result['warnings'], warnings)

    def test_generated_python_is_not_executed(self):
        code = 'raise RuntimeError("Generated code was executed")\n'
        self.respond(json.dumps({'python_code': code, 'warnings': []}))
        self.assertTrue(translate_matlab('x = 1;')['success'])

    def test_empty_or_invalid_matlab_input_does_not_call_groq(self):
        for source in ('', ' \n\t', None, 123):
            with self.subTest(source=source):
                self.assert_failed(translate_matlab(source))
        self.groq.assert_not_called()

    def test_missing_api_key_does_not_call_groq(self):
        for api_key in ('', '   ', None):
            with self.subTest(api_key=api_key), override_settings(GROQ_API_KEY=api_key):
                result = translate_matlab('x = 1;')
                self.assert_failed(result)
                self.assertIn('no Groq API key', result['error'])
        self.groq.assert_not_called()

    def test_invalid_configuration_does_not_call_groq(self):
        overrides = [
            {'GROQ_MODEL': ''},
            {'GROQ_RESPONSE_FORMAT': 'text'},
            *({'GROQ_TIMEOUT_SECONDS': timeout} for timeout in (
                '', 'not-a-number', None, '0', '-1', 'nan', 'inf',
            )),
        ]
        for values in overrides:
            with self.subTest(values=values), override_settings(**values):
                self.assert_failed(translate_matlab('x = 1;'))
        self.groq.assert_not_called()

    def test_provider_errors_are_useful_and_do_not_expose_details(self):
        request = httpx.Request('POST', 'https://api.groq.com/openai/v1/chat/completions')
        private = 'private provider details must not appear'
        errors = [
            (AuthenticationError, 401, 'authentication failed'),
            (RateLimitError, 429, 'rate-limited'),
            (BadRequestError, 400, 'could not complete'),
        ]
        for error_type, status, expected in errors:
            response = httpx.Response(status, request=request)
            with self.subTest(status=status):
                self.client.chat.completions.create.side_effect = error_type(
                    private, response=response, body={'error': private},
                )
                result = translate_matlab('x = 1;')
                self.assert_failed(result)
                self.assertIn(expected, result['error'])
                self.assertNotIn(private, json.dumps(result))

        for error in (
            APIConnectionError(message=private, request=request),
            APIResponseValidationError(httpx.Response(200, request=request), {'error': private}),
        ):
            with self.subTest(error_type=type(error).__name__):
                self.client.chat.completions.create.side_effect = error
                result = translate_matlab('x = 1;')
                self.assert_failed(result)
                self.assertNotIn(private, json.dumps(result))

    def test_timeout_returns_a_safe_error(self):
        request = httpx.Request('POST', 'https://api.groq.com/openai/v1/chat/completions')
        self.client.chat.completions.create.side_effect = APITimeoutError(request=request)
        result = translate_matlab('x = 1;')
        self.assert_failed(result)
        self.assertIn('timed out', result['error'])

    def test_incomplete_response_is_not_accepted(self):
        for reason in ('length', 'tool_calls'):
            with self.subTest(reason=reason):
                self.respond(json.dumps({'python_code': 'x = 1', 'warnings': []}), reason)
                result = translate_matlab('x = 1;')
                self.assert_failed(result)
                self.assertIn('incomplete', result['error'])

    def test_missing_completion_or_message_content(self):
        completions = [
            None, SimpleNamespace(choices=[]),
            SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop')]),
        ]
        for completion in completions:
            with self.subTest(completion=completion):
                self.client.chat.completions.create.return_value = completion
                self.assert_failed(translate_matlab('x = 1;'))
        self.respond(None)
        self.assert_failed(translate_matlab('x = 1;'))


@override_settings(EXECUTION_TIMEOUT_SECONDS='60')
class ExecutionTests(SimpleTestCase):
    def run_source(self, source):
        return execute_python(textwrap.dedent(source))

    def assert_success(self, result, figure_count=0):
        self.assertEqual(set(result), {
            'success', 'figures', 'stdout', 'stderr', 'error', 'execution_time',
        })
        self.assertTrue(result['success'], result['stderr'] or result['error'])
        self.assertIsNone(result['error'])
        self.assertEqual(len(result['figures']), figure_count)
        self.assertIsInstance(result['execution_time'], float)
        self.assertGreaterEqual(result['execution_time'], 0)
        for index, figure in enumerate(result['figures'], start=1):
            self.assertEqual(figure['name'], f'figure-{index:03d}.png')
            self.assertEqual(figure['content_type'], 'image/png')
            self.assertIsInstance(figure['data'], bytes)
            self.assertTrue(figure['data'].startswith(b'\x89PNG\r\n\x1a\n'))

    def test_valid_numerical_code_without_plots(self):
        result = self.run_source('''
            import numpy as np
            from scipy import signal
            b, a = signal.butter(2, 0.25)
            print(np.round(np.sum(np.arange(4))))
        ''')
        self.assert_success(result)
        self.assertEqual(result['stdout'], '6\n')

    def test_single_plot_and_agg_backend(self):
        result = self.run_source('''
            import matplotlib
            import matplotlib.pyplot as plt
            print(matplotlib.get_backend())
            plt.plot([0, 1], [0, 1])
            plt.xlabel('Time (s)')
        ''')
        self.assert_success(result, 1)
        self.assertEqual(result['stdout'].strip().lower(), 'agg')

    def test_multiple_figures_preserve_creation_order_even_when_closed(self):
        result = self.run_source('''
            import matplotlib.pyplot as plt
            first = plt.figure(10, figsize=(2, 1))
            plt.plot([1, 2])
            second = plt.figure(2, figsize=(3, 2))
            plt.plot([3, 4])
            plt.figure(10)
            plt.close(first)
        ''')
        self.assert_success(result, 2)
        # PNG dimensions distinguish creation order from numeric/active order.
        from PIL import Image
        sizes = [Image.open(io.BytesIO(figure['data'])).size for figure in result['figures']]
        self.assertEqual(sizes, [(200, 100), (300, 200)])

    def test_subplots_are_captured_as_one_figure(self):
        result = self.run_source('''
            import matplotlib.pyplot as plt
            fig, axes = plt.subplots(2, 1)
            axes[0].plot([1, 2, 3])
            axes[1].stem([3, 2, 1])
            fig.suptitle('Two subplots')
            print(len(fig.axes))
        ''')
        self.assert_success(result, 1)
        self.assertEqual(result['stdout'], '2\n')

    def test_captures_stdout_and_stderr(self):
        result = self.run_source('''
            import warnings
            print('DSP output: π')
            warnings.warn('Numerical warning')
        ''')
        self.assert_success(result)
        self.assertEqual(result['stdout'], 'DSP output: π\n')
        self.assertIn('Numerical warning', result['stderr'])

    def test_invalid_python_has_useful_location(self):
        result = execute_python('def broken(')
        self.assertFalse(result['success'])
        self.assertIn('SyntaxError', result['stderr'])
        self.assertIn('source.py', result['stderr'])
        self.assertEqual(result['figures'], [])

    def test_runtime_exception_and_partial_plot(self):
        result = self.run_source('''
            import matplotlib.pyplot as plt
            plt.plot([1, 2])
            print('before failure')
            raise ValueError('DSP calculation failed')
        ''')
        self.assertFalse(result['success'])
        self.assertEqual(len(result['figures']), 1)
        self.assertEqual(result['error'], 'ValueError: DSP calculation failed')
        self.assertIn('Traceback', result['stderr'])
        self.assertIn('source.py', result['stderr'])
        self.assertIn('DSP calculation failed', result['stderr'])
        self.assertEqual(result['stdout'], 'before failure\n')

    def test_missing_dependency_reports_import_failure(self):
        result = execute_python('import scipy.plottwist_missing_dependency')
        self.assertFalse(result['success'])
        self.assertIn('ModuleNotFoundError', result['error'])
        self.assertIn('plottwist_missing_dependency', result['stderr'])

    def test_timeout_kills_child_and_cleans_temporary_files(self):
        real_popen = subprocess.Popen
        children = []

        def launch(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            children.append(process)
            return process

        with tempfile.TemporaryDirectory() as parent:
            with patch('core.execution.tempfile.tempdir', parent), patch(
                'core.execution.subprocess.Popen', side_effect=launch,
            ) as popen, override_settings(EXECUTION_TIMEOUT_SECONDS='30'):
                started = time.perf_counter()
                result = execute_python('print("started", flush=True)\nwhile True: pass')
                self.assertLess(time.perf_counter() - started, 35)
                working_directory = Path(popen.call_args.kwargs['cwd'])
                self.assertFalse(working_directory.exists())
                self.assertEqual(list(Path(parent).iterdir()), [])
        self.assertFalse(result['success'])
        self.assertIn('timeout', result['error'])
        self.assertEqual(result['stdout'], 'started\n')
        self.assertIsNotNone(children[0].poll())
        self.assertEqual(result['figures'], [])

    def test_empty_source_is_rejected_before_launch(self):
        with patch('core.execution.subprocess.Popen') as popen:
            for source in ('', ' \t\n', None):
                with self.subTest(source=source):
                    result = execute_python(source)
                    self.assertFalse(result['success'])
                    self.assertEqual(result['figures'], [])
            popen.assert_not_called()

    def test_rejects_dangerous_imports_and_operations_before_launch(self):
        sources = [
            'import os', 'import subprocess as sp', 'from socket import socket',
            'import sys', 'import ctypes', 'from numpy import *',
            'eval("1 + 1")', 'exec("print(1)")', 'compile("x = 1", "x", "exec")',
            'f = eval\nf("1")', '__import__("os")', 'open("secret.txt")',
            'import numpy as np\nnp.load("secret.npy")',
            'import matplotlib as mpl\nmpl.use("TkAgg")',
            'import matplotlib.pyplot as plt\nplt.savefig("outside.png")',
            '(1).__class__', 'getattr(1, "__class__")',
        ]
        with patch('core.execution.subprocess.Popen') as popen:
            for source in sources:
                with self.subTest(source=source):
                    result = execute_python(source)
                    self.assertFalse(result['success'])
                    self.assertIn('not allowed', result['error'])
            popen.assert_not_called()

    def test_source_and_stream_output_limits(self):
        too_large = execute_python('#' + 'x' * MAX_SOURCE_BYTES)
        self.assertFalse(too_large['success'])
        self.assertIn('64 KiB', too_large['error'])
        result = execute_python('import warnings\nprint("x" * 200000)\nwarnings.warn("y" * 200000)')
        self.assert_success(result)
        for stream in ('stdout', 'stderr'):
            self.assertLessEqual(len(result[stream].encode()), MAX_OUTPUT_BYTES)
            self.assertIn('[Output truncated]', result[stream])

    def test_png_rendering_limits_are_reported(self):
        result = execute_python('import matplotlib.pyplot as plt\nplt.figure(figsize=(100, 100))')
        self.assertFalse(result['success'])
        self.assertIn('pixel', result['error'])
        self.assertEqual(result['figures'], [])

    def test_child_uses_current_interpreter_and_excludes_parent_credentials(self):
        real_popen = subprocess.Popen
        with patch.dict('os.environ', {'GROQ_API_KEY': 'test-only', 'DJANGO_SECRET_KEY': 'test-only'}):
            with patch('core.execution.subprocess.Popen', wraps=real_popen) as popen:
                result = execute_python('print("isolated process")')
        self.assert_success(result)
        self.assertEqual(popen.call_args.args[0][0], sys.executable)
        self.assertIn('-I', popen.call_args.args[0])
        environment = popen.call_args.kwargs['env']
        self.assertNotIn('GROQ_API_KEY', environment)
        self.assertNotIn('DJANGO_SECRET_KEY', environment)

    def test_artifact_bytes_survive_temporary_directory_cleanup(self):
        real_temporary = tempfile.TemporaryDirectory
        with tempfile.TemporaryDirectory() as parent:
            with patch('core.execution.tempfile.TemporaryDirectory', side_effect=lambda **kwargs:
                real_temporary(dir=parent, **kwargs)
            ):
                result = execute_python('import matplotlib.pyplot as plt\nplt.plot([1, 2])')
            self.assert_success(result, 1)
            self.assertEqual(list(Path(parent).iterdir()), [])
            self.assertTrue(result['figures'][0]['data'].startswith(b'\x89PNG'))

    def test_process_start_failure_is_reported_and_cleaned_up(self):
        with tempfile.TemporaryDirectory() as parent:
            with patch('core.execution.tempfile.tempdir', parent), patch(
                'core.execution.subprocess.Popen', side_effect=OSError('test start failure'),
            ):
                result = execute_python('x = 1')
            self.assertEqual(list(Path(parent).iterdir()), [])
        self.assertFalse(result['success'])
        self.assertIn('could not be accessed', result['error'])

    def test_invalid_timeout_configuration(self):
        with patch('core.execution.subprocess.Popen') as popen:
            for timeout in ('0', '-1', 'nan', 'inf', 'bad', None):
                with self.subTest(timeout=timeout), override_settings(EXECUTION_TIMEOUT_SECONDS=timeout):
                    self.assertFalse(execute_python('x = 1')['success'])
            popen.assert_not_called()


class ExportTests(SimpleTestCase):
    def setUp(self):
        self.figures = []
        self.sizes = [(640, 480), (320, 640)]
        for index, size in enumerate(self.sizes):
            with Image.new('RGB', size, ('white', 'lightblue')[index]) as image:
                draw = ImageDraw.Draw(image)
                draw.line((10, size[1] - 10, size[0] - 10, 10), fill='black', width=3)
                output = io.BytesIO()
                image.save(output, format='PNG')
            self.figures.append({
                'name': f'figure-{index + 1:03d}.png',
                'content_type': 'image/png', 'data': output.getvalue(),
            })

    def assert_artifact(self, artifact, name, content_type):
        self.assertEqual(set(artifact), {'name', 'content_type', 'data'})
        self.assertEqual(artifact['name'], name)
        self.assertEqual(artifact['content_type'], content_type)
        self.assertIsInstance(artifact['data'], bytes)
        self.assertTrue(artifact['data'])

    def inspect_pdf(self, artifact, expected_sizes):
        reader = PdfReader(io.BytesIO(artifact['data']), strict=True)
        self.assertEqual(len(reader.pages), len(expected_sizes))
        for page, (width, height) in zip(reader.pages, expected_sizes):
            self.assertAlmostEqual(float(page.mediabox.width / page.mediabox.height), width / height)
            # Resource dictionaries can share all images across pages. Inspect
            # actual drawing commands to verify each page uses exactly one chart.
            operations = page.get_contents().operations
            drawn = [operands[0] for operands, operator in operations if operator == b'Do']
            self.assertEqual(len(drawn), 1)
            self.assertEqual(page.images[drawn[0]].image.size, (width, height))
            matrix = next(operands for operands, operator in reversed(operations) if operator == b'cm')
            self.assertAlmostEqual(abs(float(matrix[0])), float(page.mediabox.width))
            self.assertAlmostEqual(abs(float(matrix[3])), float(page.mediabox.height))

    def inspect_docx(self, artifact, expected_sizes):
        with ZipFile(io.BytesIO(artifact['data'])) as archive:
            self.assertIsNone(archive.testzip())
            self.assertIn('[Content_Types].xml', archive.namelist())
            self.assertIn('word/document.xml', archive.namelist())
            self.assertEqual(len([name for name in archive.namelist() if name.startswith('word/media/')]),
                             len(expected_sizes))
        document = Document(io.BytesIO(artifact['data']))
        self.assertEqual(len(document.inline_shapes), len(expected_sizes))
        self.assertEqual(len(document.paragraphs), len(expected_sizes))
        breaks = [paragraph.paragraph_format.page_break_before for paragraph in document.paragraphs]
        self.assertEqual(breaks, [False] + [True] * (len(expected_sizes) - 1))
        section = document.sections[0]
        for shape, (width, height) in zip(document.inline_shapes, expected_sizes):
            self.assertAlmostEqual(shape.width / shape.height, width / height, places=5)
            self.assertLessEqual(shape.width, section.page_width - section.left_margin - section.right_margin)
            self.assertLess(shape.height, section.page_height - section.top_margin - section.bottom_margin)

    def test_individual_png_is_returned_without_modification(self):
        artifact = export_figure(self.figures, 1, 'png')
        self.assert_artifact(artifact, 'figure-002.png', 'image/png')
        self.assertIs(artifact['data'], self.figures[1]['data'])

    def test_individual_pdf_contains_selected_chart(self):
        artifact = export_figure(self.figures, 1, 'pdf')
        self.assert_artifact(artifact, 'figure-002.pdf', 'application/pdf')
        self.inspect_pdf(artifact, [self.sizes[1]])

    def test_individual_docx_contains_selected_chart(self):
        artifact = export_figure(self.figures, 1, 'docx')
        self.assert_artifact(artifact, 'figure-002.docx',
                             'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        self.inspect_docx(artifact, [self.sizes[1]])
        with ZipFile(io.BytesIO(artifact['data'])) as archive:
            image = next(name for name in archive.namelist() if name.startswith('word/media/'))
            self.assertEqual(archive.read(image), self.figures[1]['data'])

    def test_combined_pdf_has_one_chart_per_page_in_input_order(self):
        artifact = export_figures(self.figures, 'pdf')
        self.assert_artifact(artifact, 'charts.pdf', 'application/pdf')
        self.inspect_pdf(artifact, self.sizes)

    def test_combined_docx_has_one_chart_per_page_in_input_order(self):
        artifact = export_figures(self.figures, 'docx')
        self.assert_artifact(artifact, 'charts.docx',
                             'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        self.inspect_docx(artifact, self.sizes)

    def test_pdf_page_is_tight_to_image_and_bounded_by_a4(self):
        output = io.BytesIO()
        with Image.new('RGB', (1600, 800), 'white') as image:
            image.save(output, format='PNG')
        artifact = export_figure([{'data': output.getvalue()}], format='pdf')
        reader = PdfReader(io.BytesIO(artifact['data']), strict=True)
        page = reader.pages[0]
        self.assertAlmostEqual(float(page.mediabox.width / page.mediabox.height), 2)
        self.assertLessEqual(float(page.mediabox.width), 297 / 25.4 * 72 + 0.001)
        self.assertLessEqual(float(page.mediabox.height), 210 / 25.4 * 72 + 0.001)

    def test_python_source_export_preserves_text_exactly(self):
        source = '# Signal π\r\n\r\n  x = 1;  \r\n'
        artifact = export_python(source)
        self.assert_artifact(artifact, 'generated.py', 'text/x-python; charset=utf-8')
        self.assertEqual(artifact['data'], source.encode('utf-8'))

    def test_python_source_is_never_executed_or_parsed(self):
        for source in ('raise RuntimeError("must not execute")', 'def invalid('):
            with self.subTest(source=source):
                self.assertEqual(export_python(source)['data'], source.encode('utf-8'))

    def test_invalid_figure_indices(self):
        for index in (-1, len(self.figures), 100):
            with self.subTest(index=index), self.assertRaises(IndexError):
                export_figure(self.figures, index)
        for index in (True, 0.5, '0', None):
            with self.subTest(index=index), self.assertRaises(TypeError):
                export_figure(self.figures, index)

    def test_empty_figure_collections(self):
        for figures in (None, [], ()):
            for export in (export_figure, export_figures):
                with self.subTest(figures=figures, export=export.__name__), self.assertRaises(ValueError):
                    export(figures)

    def test_invalid_image_data_is_rejected_in_every_format(self):
        jpeg = io.BytesIO()
        with Image.new('RGB', (10, 10)) as image:
            image.save(jpeg, format='JPEG')
        data_values = (b'', b'not an image', self.figures[0]['data'][:-20], jpeg.getvalue(), None)
        for data in data_values:
            for format in ('png', 'pdf', 'docx'):
                with self.subTest(format=format, data_length=len(data) if data else 0):
                    with self.assertRaises(ValueError):
                        export_figure([{'data': data}], format=format)

    def test_invalid_later_figure_does_not_return_a_partial_document(self):
        figures = [self.figures[0], {'data': b'invalid'}]
        for format in ('pdf', 'docx'):
            with self.subTest(format=format), self.assertRaises(ValueError):
                export_figures(figures, format)

    def test_empty_python_source(self):
        for source in ('', ' \r\n\t'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                export_python(source)
        with self.assertRaises(TypeError):
            export_python(None)

    def test_unsupported_formats(self):
        for format in ('csv', 'svg', 'py', '', 'jpeg'):
            with self.subTest(format=format), self.assertRaises(ValueError):
                export_figure(self.figures, format=format)
        for format in ('png', 'csv', 'py', ''):
            with self.subTest(format=format), self.assertRaises(ValueError):
                export_figures(self.figures, format=format)

    def test_export_does_not_mutate_input_artifacts(self):
        original = [dict(figure) for figure in self.figures]
        export_figures(self.figures, 'pdf')
        export_figures(self.figures, 'docx')
        self.assertEqual(self.figures, original)


class WorkflowTests(TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        override = override_settings(EXECUTION_ARTIFACT_ROOT=Path(self.temporary.name), ARTIFACT_TTL_SECONDS=900)
        override.enable()
        self.addCleanup(override.disable)
        translated = patch('core.workflow.translate_matlab')
        executed = patch('core.workflow.execute_python')
        self.translate = translated.start()
        self.execute = executed.start()
        self.addCleanup(translated.stop)
        self.addCleanup(executed.stop)
        self.translate.return_value = {
            'success': True, 'python_code': 'print("DSP output")\n',
            'warnings': ['Indexing was converted to zero-based.'], 'error': None,
        }
        self.figures = []
        for size in ((80, 40), (40, 80)):
            output = io.BytesIO()
            with Image.new('RGB', size, 'white') as image:
                image.save(output, format='PNG')
            self.figures.append({'name': 'figure.png', 'content_type': 'image/png', 'data': output.getvalue()})
        self.execute.return_value = {
            'success': True, 'figures': self.figures, 'stdout': 'DSP output\n',
            'stderr': '', 'error': None, 'execution_time': 0.2,
        }
        self.client.get(reverse('core:home'))

    def post(self, data=None, client=None, **kwargs):
        return (client or self.client).post(
            reverse('core:run'), data if data is not None else {'matlab_code': 'x = 1;'},
            HTTP_ACCEPT='application/json', **kwargs,
        )

    def content(self, response):
        data = b''.join(response.streaming_content) if response.streaming else response.content
        response.close()
        return data

    def test_success_runs_services_in_order_and_stores_only_private_files(self):
        response = self.post()
        result = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(result['stage'], 'complete')
        self.translate.assert_called_once_with('x = 1;')
        self.execute.assert_called_once_with('print("DSP output")\n')
        self.assertEqual(result['stdout'], 'DSP output\n')
        self.assertEqual(result['warnings'], self.translate.return_value['warnings'])
        self.assertEqual(len(result['figures']), 2)
        self.assertNotIn('data', result['figures'][0])
        self.assertNotIn('owner', result)
        session = self.client.session
        self.assertEqual(set(session.keys()), {'plottwist_owner', 'plottwist_last_run'})
        metadata = artifacts.load_result(result['execution_id'], session['plottwist_owner'])
        self.assertEqual(metadata['python_code'], self.translate.return_value['python_code'])
        self.assertEqual(artifacts.read_figure(metadata, 0)['data'], self.figures[0]['data'])
        home = self.client.get(reverse('core:home'))
        self.assertContains(home, 'Download Python')
        self.assertContains(home, 'Combined PDF')
        self.assertContains(home, 'Combined DOCX')
        self.assertContains(home, 'Figure 2')
        self.assertContains(home, 'Translation warnings')
        self.assertContains(home, 'Execution output')
        self.assertContains(home, 'type="submit"')
        self.assertContains(home, 'action="/run/"')
        self.assertContains(home, 'id="python-code"')
        self.assertNotContains(home, '<textarea id="python-code"')
        self.assertIn(result['execution_id'], result['html'])

    def test_translation_failure_prevents_execution(self):
        self.translate.return_value.update(success=False, python_code='', error='Translation is unavailable.')
        response = self.post()
        self.assertEqual(response.status_code, 502)
        result = response.json()
        self.assertEqual(result['stage'], 'translation')
        self.assertIn('Translation failed', result['html'])
        self.execute.assert_not_called()
        self.assertIsNone(result['execution_id'])

    def test_execution_failure_preserves_code_and_translation_warnings(self):
        self.execute.return_value.update(
            success=False, error='ValueError: DSP failed',
            stderr='Traceback\nFile "C:\\private\\runner.py"\nValueError: DSP failed',
        )
        result = self.post().json()
        self.assertEqual(result['stage'], 'execution')
        self.assertEqual(result['python_code'], self.translate.return_value['python_code'])
        self.assertEqual(result['warnings'], self.translate.return_value['warnings'])
        self.assertIn('Execution failed', result['html'])
        self.assertIn('Download Python', result['html'])
        self.assertNotIn('C:\\private', json.dumps(result))
        self.assertEqual(result['stderr'], '')
        response = self.client.get(reverse('core:download_python', args=[result['execution_id']]))
        self.assertEqual(self.content(response), result['python_code'].encode())

    def test_success_without_figures_is_not_an_error(self):
        self.execute.return_value['figures'] = []
        result = self.post().json()
        self.assertTrue(result['success'])
        self.assertEqual(result['figures'], [])
        self.assertIn('Execution completed without figures', result['html'])
        self.assertNotIn('Combined PDF', result['html'])

    def test_invalid_empty_oversized_and_malformed_requests_do_not_translate(self):
        for source, status in (('', 400), ('   ', 400), (None, 400), ('x' * (MAX_SOURCE_BYTES + 1), 413)):
            with self.subTest(status=status, size=len(source) if source else 0):
                response = self.post(json.dumps({'matlab_code': source}), content_type='application/json')
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()['stage'], 'validation')
        for data in ('{', '[]', 'null'):
            self.assertEqual(self.post(data, content_type='application/json').status_code, 400)
        self.assertEqual(self.post('x=1', content_type='text/plain').status_code, 415)
        self.assertEqual(self.client.get(reverse('core:run')).status_code, 405)
        self.translate.assert_not_called()

    def test_duplicate_request_is_rejected_while_session_lock_is_held(self):
        owner = self.client.session['plottwist_owner']
        with artifacts.run_lock(owner):
            response = self.post()
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()['error_code'], 'busy')
        self.assertEqual(list(Path(self.temporary.name).glob('*.lock')), [])
        self.translate.assert_not_called()

    def test_all_individual_download_formats_and_headers(self):
        result = self.post().json()
        types = {
            'png': 'image/png', 'pdf': 'application/pdf',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        }
        for format, content_type in types.items():
            with self.subTest(format=format):
                response = self.client.get(reverse('core:download_figure', args=[result['execution_id'], 1, format]))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Content-Type'], content_type)
                self.assertIn('attachment; filename="figure-002.' + format + '"', response['Content-Disposition'])
                data = self.content(response)
                if format == 'png':
                    self.assertEqual(data, self.figures[1]['data'])
                elif format == 'pdf':
                    self.assertEqual(len(PdfReader(io.BytesIO(data)).pages), 1)
                else:
                    self.assertEqual(len(Document(io.BytesIO(data)).inline_shapes), 1)

    def test_combined_download_formats(self):
        result = self.post().json()
        for format in ('pdf', 'docx'):
            response = self.client.get(reverse('core:download_figures', args=[result['execution_id'], format]))
            self.assertEqual(response.status_code, 200)
            self.assertIn(f'filename="charts.{format}"', response['Content-Disposition'])
            data = self.content(response)
            if format == 'pdf':
                self.assertEqual(len(PdfReader(io.BytesIO(data)).pages), 2)
            else:
                self.assertEqual(len(Document(io.BytesIO(data)).inline_shapes), 2)

    def test_figures_and_exports_are_session_private(self):
        result = self.post().json()
        other = Client()
        other.get(reverse('core:home'))
        urls = [
            reverse('core:figure', args=[result['execution_id'], 0]),
            reverse('core:download_python', args=[result['execution_id']]),
            reverse('core:download_figure', args=[result['execution_id'], 0, 'png']),
            reverse('core:download_figures', args=[result['execution_id'], 'pdf']),
        ]
        for url in urls:
            self.assertEqual(other.get(url).status_code, 404)
        image = self.client.get(urls[0])
        self.assertEqual(image['Cache-Control'], 'private, no-store')
        self.assertEqual(self.content(image), self.figures[0]['data'])

    def test_expired_missing_and_invalid_indices(self):
        from uuid import uuid4
        result = self.post().json()
        self.assertEqual(self.client.get(reverse('core:figure', args=[uuid4(), 0])).status_code, 404)
        self.assertEqual(self.client.get(reverse('core:figure', args=[result['execution_id'], 99])).status_code, 404)
        self.assertEqual(self.client.get(reverse('core:download_figure', args=[result['execution_id'], 99, 'png'])).status_code, 404)
        future = time.time() + 901
        with patch('core.artifacts.time.time', return_value=future):
            response = self.client.get(reverse('core:download_python', args=[result['execution_id']]))
            self.assertEqual(response.status_code, 404)
        self.assertEqual(list(Path(self.temporary.name).iterdir()), [])

    def test_export_errors_are_safe(self):
        result = self.post().json()
        url = reverse('core:download_figure', args=[result['execution_id'], 0, 'pdf'])
        with patch('core.views.exports.export_figure', side_effect=RuntimeError('C:\\private\\secret')):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('secret', response.json()['error'])
        self.assertEqual(self.client.get(reverse('core:download_figures', args=[result['execution_id'], 'csv'])).status_code, 400)

    def test_csrf_is_required(self):
        client = Client(enforce_csrf_checks=True)
        client.get(reverse('core:home'))
        self.assertEqual(self.post(client=client).status_code, 403)
        self.translate.assert_not_called()
        response = self.post(client=client, HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200)

    def test_private_diagnostics_and_code_html_are_not_executed(self):
        self.translate.return_value['python_code'] = 'print("</code><script>alert(1)</script>")'
        self.execute.return_value.update(stdout='GROQ_API_KEY=not-for-the-browser\nDSP output',
                                         stderr='C:\\private\\library.py: warning')
        result = self.post().json()
        self.assertNotIn('not-for-the-browser', result['html'])
        self.assertNotIn('C:\\private', result['html'])
        self.assertNotIn('<script>alert(1)</script>', result['html'])
        self.assertIn('&lt;script&gt;', result['html'])

    def test_abandoned_artifacts_are_cleaned_without_following_client_paths(self):
        result = self.post().json()
        owner = self.client.session['plottwist_owner']
        with self.assertRaises(FileNotFoundError):
            artifacts.load_result('../outside', owner)
        with patch('core.artifacts.time.time', return_value=time.time() + 901):
            self.assertEqual(artifacts.cleanup_expired(), 1)
        self.assertEqual(list(Path(self.temporary.name).iterdir()), [])

    def test_timeouts_and_unexpected_service_errors_keep_the_correct_stage(self):
        self.translate.return_value.update(success=False, error='Translation timed out.', python_code='')
        response = self.post()
        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json()['stage'], 'translation')
        self.execute.assert_not_called()
        self.translate.side_effect = RuntimeError('private provider details')
        result = self.post().json()
        self.assertEqual(result['stage'], 'translation')
        self.assertNotIn('private provider details', result['error'])

    def test_execution_timeout_and_unexpected_failure_preserve_source(self):
        self.execute.return_value.update(success=False, error='Python execution exceeded the timeout.')
        response = self.post()
        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json()['stage'], 'execution')
        self.assertEqual(response.json()['python_code'], self.translate.return_value['python_code'])
        self.execute.side_effect = RuntimeError('private execution details')
        result = self.post().json()
        self.assertEqual(result['stage'], 'execution')
        self.assertIn('Download Python', result['html'])
        self.assertNotIn('private execution details', result['error'])

    def test_storage_failure_does_not_misrepresent_translation_or_drop_code(self):
        with patch('core.views.artifacts.save_result', side_effect=OSError('private filesystem')):
            response = self.post()
        self.assertEqual(response.status_code, 503)
        result = response.json()
        self.assertEqual(result['stage'], 'storage')
        self.assertEqual(result['python_code'], self.translate.return_value['python_code'])
        self.assertEqual(result['warnings'], self.translate.return_value['warnings'])
        self.assertNotIn('private filesystem', result['error'])
