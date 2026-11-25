from io import BytesIO
import json
import secrets

from django.conf import settings
from django.http import FileResponse, Http404, JsonResponse
from django.http.multipartparser import MultiPartParserError
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST, require_safe

from . import artifacts, exports, workflow


_STATUS_CODES = {
    'empty_source': 400, 'invalid_request': 400, 'source_too_large': 413,
    'unsupported_content': 415, 'translation_failed': 502, 'execution_failed': 422,
    'timeout': 504, 'busy': 409, 'storage': 503,
}


@require_safe
def user_guide(request):
    return render(request, 'core/public/guide.html', {
        'artifact_ttl_seconds': settings.ARTIFACT_TTL_SECONDS,
        'execution_timeout_seconds': settings.EXECUTION_TIMEOUT_SECONDS,
    })


@require_safe
def privacy_policy(request):
    return render(request, 'core/public/privacy.html', {
        'artifact_ttl_seconds': settings.ARTIFACT_TTL_SECONDS,
        'session_cookie_name': settings.SESSION_COOKIE_NAME,
        'csrf_cookie_name': settings.CSRF_COOKIE_NAME,
        'session_cookie_age_seconds': settings.SESSION_COOKIE_AGE,
    })


def _owner(request):
    if 'plottwist_owner' not in request.session:
        request.session['plottwist_owner'] = secrets.token_urlsafe(32)
    return request.session['plottwist_owner']


def _presentation(result):
    public = {key: value for key, value in result.items() if key not in {'owner', 'created', 'matlab_code'}}
    execution_id = public['execution_id']
    public['matlab_download_url'] = (
        reverse('core:download_matlab', args=[execution_id]) if execution_id else None
    )
    public['figures'] = [
        {**figure, 'index': index, 'url': reverse('core:figure', args=[execution_id, index])}
        for index, figure in enumerate(public['figures'])
    ] if execution_id else []
    return public


def _result_response(request, result, source=''):
    public = _presentation(result)
    status = _STATUS_CODES.get(public['error_code'], 200)
    if 'application/json' in request.headers.get('Accept', ''):
        html = render_to_string('core/results.html', {'result': public}, request=request)
        response = JsonResponse({**public, 'html': html}, status=status)
    else:
        response = render(request, 'core/home.html', {
            'result': public, 'matlab_code': source, 'max_source_bytes': workflow.MAX_SOURCE_BYTES,
        }, status=status)
    response['Cache-Control'] = 'private, no-store'
    return response


@require_GET
def home(request):
    _owner(request)
    result = workflow.empty_result()
    source = None
    execution_id = request.session.get('plottwist_last_run')
    if execution_id:
        try:
            result = artifacts.load_result(execution_id, request.session['plottwist_owner'])
            source = result['matlab_code']
        except (OSError, ValueError):
            request.session.pop('plottwist_last_run', None)
    response = render(request, 'core/home.html', {
        'result': _presentation(result), 'matlab_code': source,
        'max_source_bytes': workflow.MAX_SOURCE_BYTES,
    })
    response['Cache-Control'] = 'private, no-store'
    return response


@require_POST
def run(request):
    try:
        if int(request.META.get('CONTENT_LENGTH') or 0) > 128 * 1024:
            return _result_response(request, workflow.empty_result(
                error='The request is too large.', error_code='source_too_large',
            ))
        if request.content_type == 'application/json':
            payload = json.loads(request.body.decode('utf-8'))
            if not isinstance(payload, dict):
                raise ValueError('Invalid request')
            source = payload.get('matlab_code')
        elif request.content_type in {'application/x-www-form-urlencoded', 'multipart/form-data'}:
            source = request.POST.get('matlab_code')
        else:
            return _result_response(request, workflow.empty_result(
                error='Submit MATLAB source using the workspace form or JSON.',
                error_code='unsupported_content',
            ))
    except (ValueError, UnicodeDecodeError, MultiPartParserError):
        return _result_response(request, workflow.empty_result(
            error='The request could not be read. Check the MATLAB input.', error_code='invalid_request',
        ))
    invalid = workflow.validate_source(source)
    if invalid:
        return _result_response(request, invalid, source if isinstance(source, str) else '')

    owner = _owner(request)
    result = workflow.empty_result()
    try:
        with artifacts.run_lock(owner):
            result = workflow.run_matlab(source)
            if result['python_code']:
                result = artifacts.save_result(result, source, owner)
                request.session['plottwist_last_run'] = result['execution_id']
    except FileExistsError:
        result = workflow.empty_result(error='A run is already in progress. Please wait.', error_code='busy')
    except (OSError, ValueError):
        result.update(
            success=False, stage='storage', error='Temporary results could not be stored. Try again.',
            error_code='storage', figures=[], execution_id=None,
        )
    return _result_response(request, result, source)


def _stored_result(request, execution_id):
    try:
        return artifacts.load_result(execution_id, request.session.get('plottwist_owner'))
    except (OSError, ValueError) as exc:
        raise Http404('This result is unavailable or has expired. Run the code again.') from exc


@require_GET
def figure(request, execution_id, index):
    result = _stored_result(request, execution_id)
    try:
        path = artifacts.figure_path(result, index)
        response = FileResponse(path.open('rb'), content_type='image/png')
    except OSError as exc:
        raise Http404('This figure is unavailable.') from exc
    response['Cache-Control'] = 'private, no-store'
    return response


@require_GET
def download(request, execution_id, kind, format, index=0):
    result = _stored_result(request, execution_id)
    if kind == 'combined':
        values = (request.GET.getlist('indices')
                  if 'indices' in request.GET or 'selection' in request.GET else None)
        try:
            indices = artifacts.selected_figure_indices(result, values)
        except ValueError as exc:
            return JsonResponse({'error': str(exc)}, status=400)
    try:
        if kind == 'python':
            artifact = exports.export_python(result['python_code'])
        elif kind == 'matlab':
            artifact = exports.export_matlab(result['matlab_code'])
        elif kind == 'figure':
            selected = artifacts.read_figure(result, index)
            artifact = exports.export_figure([selected], format=format)
            extension = artifact['name'].rsplit('.', 1)[1]
            artifact['name'] = f'figure-{index + 1:03d}.{extension}'
        else:
            figures = [artifacts.read_figure(result, i) for i in indices]
            artifact = exports.export_figures(figures, format=format)
    except (FileNotFoundError, IndexError) as exc:
        raise Http404('This figure is unavailable.') from exc
    except (ValueError, TypeError):
        return JsonResponse({'error': 'The requested export is not available.'}, status=400)
    except Exception:
        return JsonResponse({'error': 'The download could not be generated. Try again.'}, status=500)
    response = FileResponse(
        BytesIO(artifact['data']), as_attachment=True,
        filename=artifact['name'], content_type=artifact['content_type'],
    )
    response['Cache-Control'] = 'private, no-store'
    return response
