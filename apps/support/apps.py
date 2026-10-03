from django.apps import AppConfig


class SupportConfig(AppConfig):
    name = "apps.support"

    def ready(self):
        from . import signals  # noqa: F401
