from django.apps import AppConfig


class CrudConfig(AppConfig):
    name = "crud"

    def ready(self):
        from . import checks  # noqa: F401
