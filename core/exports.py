"""In-memory downloads from PNG artifacts and Python text; never execute code."""

from collections.abc import Mapping
from io import BytesIO

from PIL import Image


_CONTENT_TYPES = {
    'png': 'image/png',
    'pdf': 'application/pdf',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}
_MAX_IMAGE_PIXELS = 4_000_000


def _check_figures(figures):
    if figures is None or not figures:
        raise ValueError('At least one figure is required for export.')
    if not isinstance(figures, (list, tuple)):
        raise TypeError('Figures must be an ordered list or tuple of PNG artifacts.')


def _check_format(format, supported):
    if not isinstance(format, str):
        raise TypeError('The export format must be a string.')
    format = format.strip().lower()
    if format not in supported:
        raise ValueError(f'Unsupported export format: {format!r}.')
    return format


def _load_png(figure):
    if not isinstance(figure, Mapping):
        raise TypeError('A figure must be a PNG artifact dictionary.')
    data = figure.get('data')
    if not isinstance(data, bytes) or not data:
        raise ValueError('The figure contains no PNG bytes.')
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format != 'PNG':
                raise ValueError('The figure must contain a PNG image.')
            if image.width * image.height > _MAX_IMAGE_PIXELS:
                raise ValueError('The figure exceeds the 4-million-pixel image limit.')
            image.verify()
        # Verification checks structure/CRC; decoding also detects broken pixels.
        with Image.open(BytesIO(data)) as image:
            image.load()
            return data, image.copy()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError('The figure contains invalid or oversized PNG image data.') from exc


def _pdf(figures):
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.figure import Figure

    output = BytesIO()
    with PdfPages(output, metadata={'Title': 'plottwist charts', 'Author': 'plottwist'}) as pdf:
        for artifact in figures:
            _, image = _load_png(artifact)
            try:
                width, height = image.width / 100, image.height / 100
                # Tight image-shaped pages, bounded by A4 in either orientation.
                bounds = (297 / 25.4, 210 / 25.4) if width > height else (210 / 25.4, 297 / 25.4)
                scale = min(1, bounds[0] / width, bounds[1] / height)
                figure = Figure(figsize=(width * scale, height * scale), facecolor='white')
                try:
                    axes = figure.add_axes([0, 0, 1, 1])
                    axes.imshow(image, aspect='equal', interpolation='none')
                    axes.set_axis_off()
                    pdf.savefig(figure, dpi=100, bbox_inches=None, pad_inches=0)
                finally:
                    figure.clear()
            finally:
                image.close()
    return output.getvalue()


def _docx(figures):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches, Mm, Pt

    document = Document()
    document.core_properties.title = 'plottwist charts'
    document.core_properties.author = 'plottwist'
    section = document.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    section.top_margin = section.bottom_margin = Inches(0.75)
    section.left_margin = section.right_margin = Inches(0.75)
    width_available = section.page_width - section.left_margin - section.right_margin
    # Reserve space for the inline image's baseline so a tall chart cannot spill.
    height_available = section.page_height - section.top_margin - section.bottom_margin - Inches(0.2)
    for index, artifact in enumerate(figures):
        data, image = _load_png(artifact)
        try:
            scale = min(width_available / image.width, height_available / image.height)
            paragraph = document.add_paragraph()
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph.paragraph_format.space_before = Pt(0)
            paragraph.paragraph_format.space_after = Pt(0)
            paragraph.paragraph_format.line_spacing = 1
            paragraph.paragraph_format.page_break_before = index > 0
            paragraph.add_run().add_picture(
                BytesIO(data), width=int(image.width * scale), height=int(image.height * scale),
            )
        finally:
            image.close()
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def export_figure(figures, index=0, format='png') -> dict:
    """Export a selected figure by zero-based index as PNG, PDF, or DOCX.

    Return {name, content_type, data}, with immutable file bytes. PNG exports
    return the original bytes; source filenames do not control download names.
    """
    _check_figures(figures)
    if type(index) is not int:
        raise TypeError('The figure index must be an integer.')
    if index < 0 or index >= len(figures):
        raise IndexError(f'Figure index must be between 0 and {len(figures) - 1}.')
    format = _check_format(format, {'png', 'pdf', 'docx'})
    if format == 'png':
        data, image = _load_png(figures[index])
        image.close()
    else:
        data = (_pdf if format == 'pdf' else _docx)([figures[index]])
    return {
        'name': f'figure-{index + 1:03d}.{format}',
        'content_type': _CONTENT_TYPES[format],
        'data': data,
    }


def export_figures(figures, format='pdf') -> dict:
    """Export figures in input order, one chart per PDF or DOCX page."""
    _check_figures(figures)
    format = _check_format(format, {'pdf', 'docx'})
    data = (_pdf if format == 'pdf' else _docx)(figures)
    return {'name': f'charts.{format}', 'content_type': _CONTENT_TYPES[format], 'data': data}


def export_python(source: str) -> dict:
    """Export source verbatim as UTF-8 generated.py; no parsing or execution."""
    if not isinstance(source, str):
        raise TypeError('Python source must be a string.')
    if not source.strip():
        raise ValueError('Python source is empty.')
    try:
        data = source.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise ValueError('Python source must be valid UTF-8 text.') from exc
    return {'name': 'generated.py', 'content_type': 'text/x-python; charset=utf-8', 'data': data}
