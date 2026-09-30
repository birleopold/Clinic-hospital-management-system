import hashlib
import hmac
import json
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.http import JsonResponse, HttpResponseForbidden
from django.utils import timezone
from apps.operations.models import LoginThrottle


class AccessSafeguardsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def process_exception(self, request, exception):
        from django.db import IntegrityError
        if isinstance(exception, IntegrityError) and 'Patient identity was merged' in str(exception):
            return JsonResponse({'detail':'Patient identity changed during this action. Reload its canonical record before retrying.'},status=409)

    def __call__(self, request):
        if (
            request.path.startswith("/admin/")
            and request.user.is_authenticated
            and not request.user.is_superuser
        ):
            return HttpResponseForbidden(
                "Django administration is restricted to system superusers. Use the facility-scoped suite."
            )
        if request.method == "POST" and request.path.rstrip("/") in (
            "/accounts/login",
            "/api/auth/token",
        ):
            username = request.POST.get("username", "")
            if request.content_type == "application/json":
                try:
                    username = str(json.loads(request.body).get("username", ""))
                except (ValueError, TypeError):
                    username = ""
            ip = request.META.get("REMOTE_ADDR", "unknown")
            for label, limit, seconds in [
                (ip, 120, 60),
                (ip + "|" + username.casefold(), 10, 900),
            ]:
                key = hmac.new(
                    settings.SECRET_KEY.encode(), label.encode(), hashlib.sha256
                ).hexdigest()
                with transaction.atomic():
                    now = timezone.now()
                    LoginThrottle.objects.get_or_create(
                        key=key, defaults={"window_start": now}
                    )
                    row = LoginThrottle.objects.select_for_update().get(key=key)
                    if now >= row.window_start + timedelta(seconds=seconds):
                        row.window_start = now
                        row.attempts = 0
                    if row.attempts >= limit:
                        response = JsonResponse(
                            {"detail": "Too many login attempts. Try again later."},
                            status=429,
                        )
                        response["Retry-After"] = str(
                            max(
                                1,
                                int(
                                    (
                                        row.window_start
                                        + timedelta(seconds=seconds)
                                        - now
                                    ).total_seconds()
                                ),
                            )
                        )
                        return response
                    row.attempts += 1
                    row.save()
        response = self.get_response(request)
        if request.user.is_authenticated or request.path.startswith("/portal/"):
            response["Cache-Control"] = "private, no-store"
        return response
