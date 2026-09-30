"""Provider adapters. Credentials come only from the environment; payloads are not logged."""

import base64
import hashlib
import json
import os
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from apps.operations.models import SmsDelivery


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Provider redirects are disabled")


def http(method, url, headers, payload=None, form=False):
    data = None
    if payload is not None:
        data = (urlencode(payload) if form else json.dumps(payload)).encode()
    headers = {**headers, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = (
            "application/x-www-form-urlencoded" if form else "application/json"
        )
    with build_opener(NoRedirect()).open(
        Request(url, data=data, headers=headers, method=method), timeout=30
    ) as response:
        body = response.read(1024 * 1024)
        return json.loads(body) if body else {}


def required(name):
    value = os.environ.get(name)
    if not value:
        raise ImproperlyConfigured(f"{name} is required")
    return value


class MTNCollection:
    def __init__(self):
        self.environment = required("MTN_TARGET_ENVIRONMENT")
        self.base = (
            "https://sandbox.momodeveloper.mtn.com"
            if self.environment == "sandbox"
            else "https://proxy.momoapi.mtn.com"
        )
        self.subscription = required("MTN_COLLECTION_SUBSCRIPTION_KEY")
        self.user = required("MTN_API_USER")
        self.key = required("MTN_API_KEY")

    def headers(self):
        basic = base64.b64encode(f"{self.user}:{self.key}".encode()).decode()
        token = http(
            "POST",
            self.base + "/collection/token/",
            {
                "Authorization": "Basic " + basic,
                "Ocp-Apim-Subscription-Key": self.subscription,
            },
        )["access_token"]
        return {
            "Authorization": "Bearer " + token,
            "Ocp-Apim-Subscription-Key": self.subscription,
            "X-Target-Environment": self.environment,
        }

    def request(self, intent):
        if self.environment == "sandbox" and intent.currency != "EUR":
            raise ValueError(
                "MTN sandbox requires EUR; do not relabel a live UGX invoice as EUR."
            )
        return http(
            "POST",
            self.base + "/collection/v1_0/requesttopay",
            {**self.headers(), "X-Reference-Id": str(intent.reference)},
            {
                "amount": str(intent.amount),
                "currency": intent.currency,
                "externalId": str(intent.reference),
                "payer": {"partyIdType": "MSISDN", "partyId": intent.phone.lstrip("+")},
                "payerMessage": "Clinic payment",
                "payeeNote": "Clinic payment",
            },
        )

    def status(self, intent):
        return http(
            "GET",
            self.base + "/collection/v1_0/requesttopay/" + str(intent.reference),
            self.headers(),
        )


class AfricasTalkingSMS:
    # Durable local dispatch keys prevent repeat sends. Ambiguous attempts require manual reconciliation.
    supports_idempotency = True

    def send(self, to_e164, body, *, idempotency_key):
        username = required("AT_USERNAME")
        key = required("AT_API_KEY")
        digest = hashlib.sha256((to_e164 + "\n" + body).encode()).hexdigest()
        with transaction.atomic():
            delivery, created = SmsDelivery.objects.get_or_create(
                key=idempotency_key, defaults={"payload_hash": digest}
            )
            delivery = SmsDelivery.objects.select_for_update().get(pk=delivery.pk)
            if delivery.payload_hash != digest:
                raise ValueError("Dispatch key payload mismatch")
            if not created:
                if delivery.status in ("accepted", "delivered"):
                    return {"ok": True, "ref": delivery.provider_reference}
                raise ValueError(
                    "Ambiguous/failed delivery requires provider reconciliation; automatic resend refused"
                )
        url = (
            "https://api.sandbox.africastalking.com/version1/messaging"
            if username == "sandbox"
            else "https://api.africastalking.com/version1/messaging"
        )
        payload = {"username": username, "to": to_e164, "message": body}
        if os.environ.get("AT_SENDER_ID"):
            payload["from"] = os.environ["AT_SENDER_ID"]
        try:
            response = http("POST", url, {"apiKey": key}, payload, form=True)
            recipients = response["SMSMessageData"]["Recipients"]
            if len(recipients) != 1 or recipients[0].get("statusCode") != 101:
                raise ValueError("Provider did not accept message")
            ref = recipients[0]["messageId"]
            SmsDelivery.objects.filter(pk=delivery.pk).update(
                status="accepted", provider_reference=ref
            )
            return {"ok": True, "ref": ref}
        except Exception:
            SmsDelivery.objects.filter(pk=delivery.pk).update(status="unknown")
            raise
