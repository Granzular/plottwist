"""Private, expiring filesystem artifacts; session tokens identify their owner."""

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import tempfile
import time
from uuid import UUID, uuid4

from django.conf import settings

from .execution import MAX_FIGURES, MAX_FIGURE_BYTES, MAX_TOTAL_FIGURE_BYTES


def _root():
    root = Path(settings.EXECUTION_ARTIFACT_ROOT).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def _owner_hash(owner):
    if not isinstance(owner, str) or not owner:
        raise FileNotFoundError('Result unavailable')
    return hashlib.sha256(owner.encode()).hexdigest()


def _directory(execution_id):
    try:
        name = UUID(str(execution_id)).hex
    except (ValueError, TypeError, AttributeError) as exc:
        raise FileNotFoundError('Result unavailable') from exc
    directory = _root() / name
    if directory.is_symlink() or directory.resolve().parent != _root():
        raise FileNotFoundError('Result unavailable')
    return directory


def _lock_lifetime():
    try:
        duration = float(settings.GROQ_TIMEOUT_SECONDS) + float(settings.EXECUTION_TIMEOUT_SECONDS) + 60
        if not math.isfinite(duration):
            duration = 900
    except (ValueError, TypeError):
        duration = 900
    return max(900, settings.ARTIFACT_TTL_SECONDS, duration)


def cleanup_expired():
    """Delete expired runs, abandoned writes, and stale locks within the private root."""
    root = _root()
    now = time.time()
    removed = 0
    for path in root.iterdir():
        if path.is_symlink():
            continue
        try:
            age = now - path.stat().st_mtime
            if path.is_file() and path.suffix == '.lock':
                if age > _lock_lifetime():
                    path.unlink(missing_ok=True)
            elif path.is_dir() and (re.fullmatch(r'[0-9a-f]{32}', path.name) or path.name.startswith('.writing-')):
                if age > settings.ARTIFACT_TTL_SECONDS and path.resolve().parent == root:
                    shutil.rmtree(path)
                    removed += 1
        except FileNotFoundError:
            pass  # Another request may have cleaned the same expired run.
    return removed


@contextmanager
def run_lock(owner):
    """Atomic file creation prevents concurrent runs for the same browser session."""
    cleanup_expired()
    lock = _root() / f'{_owner_hash(owner)}.lock'
    token = secrets.token_hex(16)
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(token)
        yield
    finally:
        if lock.exists() and not lock.is_symlink() and lock.read_text() == token:
            lock.unlink(missing_ok=True)


def save_result(result, source, owner):
    execution_id = uuid4()
    root = _root()
    metadata = {**result, 'execution_id': str(execution_id), 'matlab_code': source,
                'owner': _owner_hash(owner), 'created': time.time(), 'figures': []}
    total = 0
    if len(result['figures']) > MAX_FIGURES:
        raise ValueError('Too many figure artifacts')
    with tempfile.TemporaryDirectory(prefix='.writing-', dir=root) as temporary:
        directory = Path(temporary)
        for index, figure in enumerate(result['figures'], 1):
            data = figure['data']
            total += len(data)
            if not isinstance(data, bytes) or len(data) > MAX_FIGURE_BYTES or total > MAX_TOTAL_FIGURE_BYTES:
                raise ValueError('Invalid figure artifact size')
            if not data.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('Invalid figure artifact')
            name = f'figure-{index:03d}.png'
            (directory / name).write_bytes(data)
            metadata['figures'].append({'name': name, 'content_type': 'image/png'})
        (directory / 'result.json').write_text(json.dumps(metadata), encoding='utf-8')
        directory.rename(root / execution_id.hex)
    return metadata


def load_result(execution_id, owner):
    directory = _directory(execution_id)
    manifest = directory / 'result.json'
    if manifest.is_symlink() or manifest.stat().st_size > 2 * 1024 * 1024:
        raise FileNotFoundError('Result unavailable')
    try:
        metadata = json.loads(manifest.read_text(encoding='utf-8'))
        if not secrets.compare_digest(metadata['owner'], _owner_hash(owner)):
            raise FileNotFoundError('Result unavailable')
        if time.time() - metadata['created'] > settings.ARTIFACT_TTL_SECONDS:
            shutil.rmtree(directory)
            raise FileNotFoundError('Result unavailable')
        if metadata['execution_id'] != str(UUID(str(execution_id))):
            raise FileNotFoundError('Result unavailable')
        return metadata
    except (ValueError, TypeError, KeyError) as exc:
        raise FileNotFoundError('Result unavailable') from exc


def figure_path(metadata, index):
    if type(index) is not int or index < 0 or index >= len(metadata['figures']):
        raise FileNotFoundError('Figure unavailable')
    path = _directory(metadata['execution_id']) / f'figure-{index + 1:03d}.png'
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FIGURE_BYTES:
        raise FileNotFoundError('Figure unavailable')
    return path


def read_figure(metadata, index):
    return {**metadata['figures'][index], 'data': figure_path(metadata, index).read_bytes()}


def selected_figure_indices(metadata, values=None):
    """Validate query values against stored figures and return their original order.

    Omitted selections retain the existing full-collection download behavior.
    An explicitly supplied selection must contain at least one unique index.
    """
    count = len(metadata['figures'])
    if values is None:
        values = [str(index) for index in range(count)]
    if not values:
        raise ValueError('Select at least one figure for a combined export.')
    if len(values) > count:
        raise ValueError('The figure selection is invalid.')
    indices = []
    for value in values:
        if (not isinstance(value, str) or len(value) > len(str(count - 1))
                or not re.fullmatch(r'0|[1-9][0-9]*', value)):
            raise ValueError('The figure selection is invalid.')
        index = int(value)
        if index >= count or index in indices:
            raise ValueError('The figure selection is invalid.')
        indices.append(index)
    return sorted(indices)
