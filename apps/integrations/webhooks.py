import secrets
import os
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from apps.operations.models import SmsDelivery


@csrf_exempt
@require_POST
def sms_delivery(request):
    expected = os.getenv("SMS_CALLBACK_TOKEN", "")
    supplied = request.GET.get("token", "")
    if len(expected) < 32 or not secrets.compare_digest(expected, supplied):
        return JsonResponse({"detail": "Unauthorized"}, status=403)
    reference = request.POST.get("id", "")
    state = request.POST.get("status", "")
    if state not in ("Success", "Failed", "Rejected", "Buffered", "Submitted"):
        return JsonResponse({"detail": "Invalid status"}, status=400)
    # Monotonic terminal delivery states; unknown message references are ignored.
    SmsDelivery.objects.filter(
        provider_reference=reference, status__in=["accepted", "dispatching"]
    ).update(
        status=(
            "delivered"
            if state == "Success"
            else "failed" if state in ("Failed", "Rejected") else "accepted"
        )
    )
    return JsonResponse({"ok": True})
