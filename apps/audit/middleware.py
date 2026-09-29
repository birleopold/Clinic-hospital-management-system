import logging
import time
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)
from .models import AuditEvent


class RequestAuditMiddleware(MiddlewareMixin):
    def process_request(self, request):
        request._audit_start = time.monotonic()

    def process_response(self, request, response):
        try:
            start = getattr(request, "_audit_start", None)
            duration_ms = int((time.monotonic() - start) * 1000) if start else 0
            user = getattr(request, "user", None)
            role = getattr(user, "role", "") if getattr(user, "is_authenticated", False) else ""
            remote_addr = request.META.get("REMOTE_ADDR", "")
            ua = request.META.get("HTTP_USER_AGENT", "")
            AuditEvent.objects.create(
                user=user if getattr(user, "is_authenticated", False) else None,
                role=role or "",
                method=request.method,
                path=request.get_full_path()[:512],
                status_code=getattr(response, "status_code", 0) or 0,
                remote_addr=remote_addr,
                user_agent=ua,
                duration_ms=duration_ms,
            )
        except Exception:
            logger.exception('Failed to persist audit event for %s', getattr(request, 'path', ''))
        return response
