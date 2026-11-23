from django.contrib.staticfiles.apps import StaticFilesConfig as DjangoStaticFilesConfig


class StaticFilesConfig(DjangoStaticFilesConfig):
    # Tailwind's build source has imports resolved by the standalone CLI.
    ignore_patterns = [*DjangoStaticFilesConfig.ignore_patterns, 'css/input.css']
