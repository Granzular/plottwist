"""Trusted subprocess bootstrap. Run only through core.execution.execute_python."""

import io
import json
from pathlib import Path
import sys
import traceback


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    # The parent supplies fixed artifact limits; the worker imports no Django,
    # translation service, or application settings.
    max_figures, max_figure_bytes, max_total_bytes = map(int, sys.argv[1:4])
    error = None
    figure_names = []
    figures = []
    try:
        import matplotlib
        matplotlib.use('Agg', force=True)
        import matplotlib.pyplot as plt
        from matplotlib.figure import Figure

        original_init = Figure.__init__

        def track_figure(figure, *args, **kwargs):
            if len(figures) >= max_figures:
                raise RuntimeError(f'Execution exceeded the {max_figures}-figure limit.')
            original_init(figure, *args, **kwargs)
            figures.append(figure)

        # Track creation rather than numeric figure labels or last-active order.
        # References also retain plots closed by submitted code before capture.
        Figure.__init__ = track_figure
        source = Path('source.py').read_text(encoding='utf-8')
        try:
            exec(compile(source, 'source.py', 'exec'), {'__name__': '__main__'})
        except BaseException as exc:
            error = f'{type(exc).__name__}: {str(exc)[:2000]}'
            traceback.print_exc()

        total_bytes = 0
        for index, figure in enumerate(figures, start=1):
            width, height = figure.get_size_inches() * figure.dpi
            if width * height > 4_000_000:
                raise RuntimeError('A figure exceeds the 4-million-pixel rendering limit.')
            with io.BytesIO() as image:
                figure.savefig(image, format='png')
                data = image.getvalue()
            total_bytes += len(data)
            if len(data) > max_figure_bytes or total_bytes > max_total_bytes:
                raise RuntimeError('Generated PNG artifacts exceed the size limit.')
            name = f'figure-{index:03d}.png'
            Path(name).write_bytes(data)
            figure_names.append(name)
        plt.close('all')
    except BaseException as exc:
        error = f'{type(exc).__name__}: {str(exc)[:2000]}'
        traceback.print_exc()
    Path('result.json').write_text(
        json.dumps({'figures': figure_names, 'error': error}), encoding='utf-8',
    )
    return 1 if error else 0


if __name__ == '__main__':
    sys.exit(main())
