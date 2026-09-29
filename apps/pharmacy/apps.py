from django.apps import AppConfig

class PharmacyConfig(AppConfig):
    name = 'apps.pharmacy'

    def ready(self):
        from . import signals  # noqa
