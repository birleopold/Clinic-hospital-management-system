"""Concrete SMS and MoMo adapters (no-op and simple log-to-console sandbox)."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class NoOpSmsBackend:
    """Does not send; returns success. Use in development."""

    def send(self, to_e164: str, body: str, **kwargs: Any) -> dict:
        return {'ok': True, 'provider': 'noop', 'to': to_e164, 'ref': ''}


class LogSmsBackend:
    """Logs the payload at INFO; does not send externally."""

    def send(self, to_e164: str, body: str, **kwargs: Any) -> dict:
        logger.info('SMS sandbox to=%s len=%s', to_e164, len(body))
        return {'ok': True, 'provider': 'log', 'to': to_e164, 'ref': 'log-only'}


class NoOpMoMoBackend:
    """No payment request; returns a structured not-implemented response."""

    def request_collection(
        self,
        amount: str,
        currency: str,
        external_id: str,
        payer_phone_e164: str,
        **kwargs: Any,
    ) -> dict:
        return {
            'ok': False,
            'provider': 'noop',
            'external_id': external_id,
            'detail': 'MoMo backend not configured',
        }


class SandboxMoMoBackend:
    """Simulates acceptance without calling a gateway (for demos)."""

    def request_collection(
        self,
        amount: str,
        currency: str,
        external_id: str,
        payer_phone_e164: str,
        **kwargs: Any,
    ) -> dict:
        logger.info(
            'MoMo sandbox collection external_id=%s amount=%s %s payer=%s',
            external_id,
            amount,
            currency,
            payer_phone_e164,
        )
        return {
            'ok': True,
            'provider': 'sandbox',
            'external_id': external_id,
            'ref': f'SANDBOX-{external_id}',
        }
