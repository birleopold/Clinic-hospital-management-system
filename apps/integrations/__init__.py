"""
Integration backends: SMS and mobile money (MoMo).

Configure via Django settings (defaults are no-op safe for dev).

    INTEGRATIONS_SMS_BACKEND = "apps.integrations.backends.NoOpSmsBackend"
    INTEGRATIONS_MOMO_BACKEND = "apps.integrations.backends.NoOpMoMoBackend"
"""

from importlib import import_module

from django.conf import settings


def _load(path: str):
    mod_path, _, cls_name = path.rpartition('.')
    module = import_module(mod_path)
    return getattr(module, cls_name)


def get_sms_backend():
    path = getattr(
        settings,
        'INTEGRATIONS_SMS_BACKEND',
        'apps.integrations.backends.NoOpSmsBackend',
    )
    return _load(path)()


def get_momo_backend():
    path = getattr(
        settings,
        'INTEGRATIONS_MOMO_BACKEND',
        'apps.integrations.backends.NoOpMoMoBackend',
    )
    return _load(path)()
