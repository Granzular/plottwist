from django.core.management.base import BaseCommand

from core.artifacts import cleanup_expired


class Command(BaseCommand):
    help = 'Remove expired private execution artifacts and abandoned run locks.'

    def handle(self, *args, **options):
        removed = cleanup_expired()
        self.stdout.write(f'Removed {removed} expired artifact directories.')
