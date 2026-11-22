"""Compose the independent services and prepare safe, stage-specific results."""

import logging
import re

from .execution import MAX_SOURCE_BYTES, execute_python
from .translation import translate_matlab


logger = logging.getLogger(__name__)
_PRIVATE_DIAGNOSTIC = re.compile(
    r'Traceback|File "|[A-Za-z]:[\\/]|(?<!\w)/[^\s/]+/|'
    r'(?:API[_ -]?KEY|SECRET[_ -]?KEY|AUTHORIZATION)\s*[:=]|gsk_[A-Za-z0-9]{20,}',
    re.IGNORECASE,
)


def empty_result(stage='validation', error=None, error_code=None):
    return {
        'success': False, 'stage': stage, 'error': error, 'error_code': error_code,
        'python_code': '', 'warnings': [], 'figures': [], 'stdout': '',
        'stderr': '', 'execution_time': None, 'execution_id': None,
    }


def safe_text(text):
    """Omit private diagnostic lines; never send raw execution tracebacks."""
    return '\n'.join(
        '[Private diagnostic omitted]' if _PRIVATE_DIAGNOSTIC.search(line) else line
        for line in str(text or '').split('\n')
    )


def validate_source(source):
    if not isinstance(source, str):
        return empty_result(error='The MATLAB source must be text.', error_code='invalid_request')
    if not source.strip():
        return empty_result(error='Enter MATLAB source code to run.', error_code='empty_source')
    try:
        size = len(source.encode('utf-8'))
    except UnicodeEncodeError:
        return empty_result(error='The MATLAB source must be valid UTF-8.', error_code='invalid_request')
    if size > MAX_SOURCE_BYTES:
        return empty_result(error='MATLAB source exceeds the 64 KiB limit.', error_code='source_too_large')
    return None


def run_matlab(source):
    invalid = validate_source(source)
    if invalid:
        return invalid
    result = empty_result('translation')
    try:
        translation = translate_matlab(source)
    except Exception as exc:
        logger.warning('Translation stage failed (%s)', type(exc).__name__)
        result.update(error='Translation is unavailable. Try again later.', error_code='translation_failed')
        return result
    result['warnings'] = [safe_text(warning) for warning in translation['warnings']]
    if not translation['success']:
        error = safe_text(translation['error'])
        result.update(error=error, error_code='timeout' if 'timed out' in error.lower() else 'translation_failed')
        return result

    result.update(stage='execution', python_code=translation['python_code'])
    try:
        execution = execute_python(result['python_code'])
    except Exception as exc:
        logger.warning('Execution stage failed (%s)', type(exc).__name__)
        result.update(error='Python execution could not complete. Try again.', error_code='execution_failed')
        return result
    result.update(
        success=execution['success'], figures=execution['figures'],
        stdout=safe_text(execution['stdout']),
        stderr='' if 'Traceback' in execution['stderr'] else safe_text(execution['stderr']),
        execution_time=execution['execution_time'],
    )
    if execution['success']:
        result['stage'] = 'complete'
    else:
        error = safe_text(execution['error']).split('\n')[0][:600]
        if '[Private diagnostic omitted]' in error:
            error = 'Python execution failed. Check the generated Python source.'
        result.update(error=error, error_code='timeout' if 'timeout' in error.lower() else 'execution_failed')
    return result
