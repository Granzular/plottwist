"""Execute Python in a child process with basic guards, not a complete sandbox."""

import ast
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import traceback

from django.conf import settings


MAX_SOURCE_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 64 * 1024  # Each of stdout and stderr.
MAX_FIGURES = 20
MAX_FIGURE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_FIGURE_BYTES = 20 * 1024 * 1024
ALLOWED_IMPORTS = {
    'numpy', 'matplotlib', 'scipy', 'math', 'cmath', 'statistics', 'time', 'warnings',
}
FORBIDDEN_NAMES = {
    'os', 'subprocess', 'socket', 'sys', 'ctypes', 'importlib', 'builtins',
    'eval', 'exec', 'compile', '__import__', 'open', 'input', 'getattr',
    'setattr', 'delattr', 'globals', 'locals', 'vars', 'breakpoint', 'help',
}
FORBIDDEN_ATTRIBUTES = FORBIDDEN_NAMES | {
    'system', 'popen', 'spawn', 'fork', 'read', 'write', 'load', 'save',
    'savez', 'savez_compressed', 'loadtxt', 'savetxt', 'genfromtxt', 'fromfile',
    'tofile', 'memmap', 'ctypeslib', 'use', 'switch_backend', 'savefig',
    'imsave', 'imread',
}


def _check_source(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [
                node.module or '',
            ]
            if isinstance(node, ast.ImportFrom) and node.level:
                return 'Relative imports are not allowed during execution.'
            for module in modules:
                if module.split('.')[0] not in ALLOWED_IMPORTS or any(
                    part.startswith('_') or part in FORBIDDEN_ATTRIBUTES
                    for part in module.split('.')
                ):
                    return f'Import of {module!r} is not allowed during execution.'
            if isinstance(node, ast.ImportFrom) and any(
                alias.name == '*' or alias.name.startswith('_')
                or alias.name in FORBIDDEN_ATTRIBUTES for alias in node.names
            ):
                return 'This imported operation is not allowed during execution.'
        if isinstance(node, ast.Name) and (
            node.id in FORBIDDEN_NAMES or node.id.startswith('__') and node.id != '__name__'
        ):
            return f'Operation {node.id!r} is not allowed during execution.'
        if isinstance(node, ast.Attribute) and (
            node.attr.startswith('_') or node.attr in FORBIDDEN_ATTRIBUTES
        ):
            return f'Attribute or operation {node.attr!r} is not allowed during execution.'
    return None


def _drain(stream, captured, truncated):
    try:
        while chunk := os.read(stream.fileno(), 8192):
            remaining = MAX_OUTPUT_BYTES - len(captured)
            captured.extend(chunk[:remaining])
            if len(chunk) > remaining:
                truncated.set()
    except (OSError, ValueError):
        # The parent may close a pipe after the direct child has been killed.
        pass


def _output(captured, truncated):
    text = captured.decode('utf-8', errors='replace').replace('\r\n', '\n')
    encoded = text.encode('utf-8')
    if truncated.is_set() or len(encoded) > MAX_OUTPUT_BYTES:
        marker = '\n[Output truncated]\n'
        text = encoded[:MAX_OUTPUT_BYTES - len(marker)].decode('utf-8', errors='ignore') + marker
    return text


def _read_artifacts(directory):
    manifest = directory / 'result.json'
    if manifest.is_symlink() or manifest.stat().st_size > MAX_OUTPUT_BYTES:
        raise ValueError('Invalid execution manifest')
    data = json.loads(manifest.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or set(data) != {'figures', 'error'}:
        raise ValueError('Invalid execution manifest')
    names = data['figures']
    error = data['error']
    if not isinstance(names, list) or len(names) > MAX_FIGURES or (
        error is not None and not isinstance(error, str)
    ):
        raise ValueError('Invalid execution manifest')

    artifacts = []
    total_bytes = 0
    for index, name in enumerate(names, start=1):
        if name != f'figure-{index:03d}.png':
            raise ValueError('Invalid figure filename')
        path = directory / name
        if path.is_symlink() or path.resolve().parent != directory.resolve():
            raise ValueError('Invalid figure path')
        with path.open('rb') as image:
            content = image.read(MAX_FIGURE_BYTES + 1)
        total_bytes += len(content)
        if len(content) > MAX_FIGURE_BYTES or total_bytes > MAX_TOTAL_FIGURE_BYTES:
            raise ValueError('Figure artifacts exceed the size limit')
        if not content.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Invalid PNG artifact')
        artifacts.append({'name': name, 'content_type': 'image/png', 'data': content})
    return artifacts, error[:2048] if error is not None else None


def execute_python(source: str) -> dict:
    """Return success, figures, stdout, stderr, error, and execution_time.

    Each figure is {name, content_type, data}, where data is PNG bytes. Temporary
    files are deleted before returning; no paths, base64, or database rows remain.
    Runtime failures may retain figures completed before the error. Timeouts and
    invalid artifacts return no figures. execution_time is elapsed wall seconds.
    """
    started = time.perf_counter()

    def result(error=None, figures=None, stdout='', stderr=''):
        return {
            'success': error is None,
            'figures': figures or [],
            'stdout': stdout,
            'stderr': stderr,
            'error': error,
            'execution_time': round(time.perf_counter() - started, 3),
        }

    if not isinstance(source, str) or not source.strip():
        return result('Enter Python source code to execute.')
    try:
        encoded = source.encode('utf-8')
    except UnicodeEncodeError:
        return result('Python source must be valid UTF-8 text.')
    if len(encoded) > MAX_SOURCE_BYTES:
        return result('Python source exceeds the 64 KiB limit.')
    try:
        tree = ast.parse(source, filename='source.py')
    except (SyntaxError, ValueError, RecursionError) as exc:
        detail = ''.join(traceback.format_exception_only(exc)).encode('utf-8')
        truncated = threading.Event()
        if len(detail) > MAX_OUTPUT_BYTES:
            truncated.set()
        return result('Invalid Python source.', stderr=_output(detail[:MAX_OUTPUT_BYTES], truncated))
    rejected = _check_source(tree)
    if rejected:
        return result(rejected)
    try:
        timeout = float(settings.EXECUTION_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        return result('The execution timeout must be a positive number.')
    if not math.isfinite(timeout) or timeout <= 0:
        return result('The execution timeout must be a positive number.')

    stdout_buffer, stderr_buffer = bytearray(), bytearray()
    stdout_truncated, stderr_truncated = threading.Event(), threading.Event()
    try:
        with tempfile.TemporaryDirectory(prefix='plottwist-execution-') as temporary:
            directory = Path(temporary)
            (directory / 'source.py').write_bytes(encoded)
            # Keep OS runtime essentials, excluding Django/provider credentials.
            environment = {
                name: value for name, value in os.environ.items()
                if name.upper() in {'SYSTEMROOT', 'WINDIR', 'LANG', 'LC_ALL'}
            }
            environment.update({
                'MPLBACKEND': 'Agg', 'MPLCONFIGDIR': str(directory / 'mpl-config'),
                'TEMP': temporary, 'TMP': temporary,
                'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
            })
            runner = Path(__file__).with_name('_execution_runner.py').resolve()
            with subprocess.Popen(
                [
                    sys.executable, '-I', '-B', '-u', str(runner),
                    str(MAX_FIGURES), str(MAX_FIGURE_BYTES), str(MAX_TOTAL_FIGURE_BYTES),
                ],
                cwd=directory, env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}),
            ) as process:
                readers = [
                    threading.Thread(target=_drain, args=args, daemon=True)
                    for args in (
                        (process.stdout, stdout_buffer, stdout_truncated),
                        (process.stderr, stderr_buffer, stderr_truncated),
                    )
                ]
                for reader in readers:
                    reader.start()
                timed_out = False
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    process.kill()
                    process.wait()
                except BaseException:
                    process.kill()
                    process.wait()
                    raise
                finally:
                    for reader in readers:
                        reader.join(timeout=1)

                stdout = _output(stdout_buffer, stdout_truncated)
                stderr = _output(stderr_buffer, stderr_truncated)
                if timed_out:
                    return result('Python execution exceeded the timeout.', stdout=stdout, stderr=stderr)
                try:
                    figures, error = _read_artifacts(directory)
                except (OSError, ValueError, TypeError, RecursionError):
                    return result(
                        f'The execution process returned no valid result (exit code {process.returncode}).',
                        stdout=stdout, stderr=stderr,
                    )
                if process.returncode and not error:
                    error = f'The execution process failed (exit code {process.returncode}).'
                return result(error, figures, stdout, stderr)
    except OSError:
        return result(
            'The execution process or temporary storage could not be accessed.',
            stdout=_output(stdout_buffer, stdout_truncated),
            stderr=_output(stderr_buffer, stderr_truncated),
        )
