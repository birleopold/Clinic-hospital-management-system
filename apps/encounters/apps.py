from django.apps import AppConfig

class EncountersConfig(AppConfig):
    name = 'apps.encounters'

    def ready(self):
        from . import signals  # noqa
