"""Route onboarding saga. Sensitive input is encrypted, never put in audit records."""

import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core import audit
from apps.core.crypto import decrypt_json

from .models import OnboardingOperation, Seller
from .settlements import RouteClient


class OnboardingClient(RouteClient):
    def v2(self, method, path, data=None):
        response = requests.request(
            method, "https://api.razorpay.com/v2/" + path, auth=self.auth, json=data, timeout=15
        )
        response.raise_for_status()
        return response.json()

    def create_account(self, data):
        return self.v2("POST", "accounts", data)

    def account(self, account_id):
        return self.v2("GET", f"accounts/{account_id}")

    def stakeholders(self, account_id):
        return self.v2("GET", f"accounts/{account_id}/stakeholders").get("items", [])

    def create_stakeholder(self, account_id, data):
        return self.v2("POST", f"accounts/{account_id}/stakeholders", data)

    def product(self, account_id, product_id):
        return self.v2("GET", f"accounts/{account_id}/products/{product_id}")

    def create_product(self, account_id):
        return self.v2("POST", f"accounts/{account_id}/products", {"product_name": "route", "tnc_accepted": True})

    def configure(self, account_id, product_id, data):
        return self.v2(
            "PATCH", f"accounts/{account_id}/products/{product_id}", {"settlements": data, "tnc_accepted": True}
        )


def _step(seller, name, create):
    with transaction.atomic():
        Seller.objects.select_for_update().get(pk=seller.pk)
        operation, _ = OnboardingOperation.objects.get_or_create(seller=seller, step=name)
        if operation.status == "succeeded":
            return operation.provider_id
        retry_config = (
            name == "configure"
            and operation.status == "uncertain"
            and (not operation.last_checked or (timezone.now() - operation.last_checked).total_seconds() >= 300)
        )
        if operation.status in ("submitting", "uncertain") and not retry_config:
            raise ValidationError(
                "A provider operation needs reconciliation. Do not submit a duplicate onboarding request."
            )
        operation.status, operation.last_checked = "submitting", timezone.now()
        operation.attempts += 1
        operation.save()
    try:
        result = create(operation.key)
        if not result.get("id"):
            raise ValueError("Provider response has no identifier")
    except (requests.RequestException, KeyError, ValueError) as exc:
        OnboardingOperation.objects.filter(pk=operation.pk).update(status="uncertain", error=type(exc).__name__)
        raise ValidationError(
            "Provider response is uncertain. Check the linked account in Razorpay before continuing."
        ) from exc
    OnboardingOperation.objects.filter(pk=operation.pk).update(status="succeeded", provider_id=result["id"], error="")
    return result["id"]


def run(seller_id, client=None):
    if not settings.MARKETPLACE_ROUTE_APPROVED:
        raise ValidationError("Owner must confirm Route access before linked-account onboarding.")
    seller = Seller.objects.select_related("owner").get(pk=seller_id)
    data = decrypt_json(seller.onboarding_encrypted)
    if not data.get("consented_at"):
        raise ValidationError("The business must submit onboarding details and accept the provider terms.")
    client = client or OnboardingClient()
    address = {
        "street1": data["street"],
        "city": data["city"],
        "state": data["state"],
        "postal_code": data["postal_code"],
        "country": "IN",
    }
    account_id = seller.linked_account_id or _step(
        seller,
        "account",
        lambda key: client.create_account(
            {
                "email": seller.owner.email,
                "phone": seller.business_phone,
                "type": "route",
                "legal_business_name": seller.legal_name,
                "business_type": data["business_type"],
                "profile": {
                    "category": data["category"],
                    "subcategory": data["subcategory"],
                    "addresses": {"registered": address},
                },
                "legal_info": {"pan": data["business_pan"], **({"gst": seller.gstin} if seller.gstin else {})},
            }
        ),
    )
    Seller.objects.filter(pk=seller.pk).update(
        linked_account_id=account_id, payments_ready=False, onboarding_status="submitted"
    )
    _step(
        seller,
        "stakeholder",
        lambda key: client.create_stakeholder(
            account_id,
            {
                "name": data["stakeholder_name"],
                "email": seller.owner.email,
                "relationship": {"executive": True},
                "phone": {"primary": seller.business_phone},
                "kyc": {"pan": data["stakeholder_pan"]},
                "notes": {"rasiko_operation": str(key)},
            },
        ),
    )
    product_id = _step(seller, "product", lambda key: client.create_product(account_id))
    _step(
        seller,
        "configure",
        lambda key: client.configure(
            account_id,
            product_id,
            {
                "account_number": data["bank_account"],
                "ifsc_code": data["ifsc"],
                "beneficiary_name": data["beneficiary_name"],
            },
        ),
    )
    return refresh(seller.pk, client)


def refresh(seller_id, client=None):
    seller = Seller.objects.get(pk=seller_id)
    operation = seller.onboarding_operations.filter(step="product", status="succeeded").first()
    if not seller.linked_account_id or not operation:
        raise ValidationError("Complete linked-account submission first.")
    client = client or OnboardingClient()
    account = client.account(seller.linked_account_id)
    product = client.product(seller.linked_account_id, operation.provider_id)
    if (
        account.get("id") != seller.linked_account_id
        or product.get("account_id") != seller.linked_account_id
        or product.get("product_name") != "route"
    ):
        raise ValidationError("Provider account does not match this seller.")
    status = product.get("activation_status", "unknown")
    ready = (
        status == "activated"
        and account.get("status") != "suspended"
        and seller.verified
        and seller.onboarding_operations.filter(step="configure", status="succeeded").exists()
    )
    Seller.objects.filter(pk=seller.pk).update(onboarding_status=status, payments_ready=ready)
    return status


def recover(actor, seller, step, provider_id, client=None):
    from .access import is_admin

    if not is_admin(actor):
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied
    if step not in ("account", "stakeholder", "product"):
        raise ValidationError("Unsupported recovery step.")
    client = client or OnboardingClient()
    if step == "account":
        record = client.account(provider_id)
        matches = (
            record.get("id") == provider_id
            and record.get("email", "").lower() == seller.owner.email.lower()
            and record.get("legal_business_name") == seller.legal_name
        )
    elif step == "product":
        record = client.product(seller.linked_account_id, provider_id)
        matches = record.get("account_id") == seller.linked_account_id and record.get("product_name") == "route"
    else:
        records = client.stakeholders(seller.linked_account_id)
        matches = any(
            r.get("id") == provider_id and r.get("email", "").lower() == seller.owner.email.lower() for r in records
        )
    if not matches:
        raise ValidationError("Provider reference does not belong to this seller.")
    with transaction.atomic():
        Seller.objects.select_for_update().get(pk=seller.pk)
        operation = OnboardingOperation.objects.select_for_update().get(seller=seller, step=step)
        if (
            operation.status == "submitting"
            and operation.last_checked
            and (timezone.now() - operation.last_checked).total_seconds() < 300
        ):
            raise ValidationError("Wait for the in-flight request to finish before recovery.")
        operation.status, operation.provider_id = "succeeded", provider_id
        operation.save()
        if step == "account":
            seller.linked_account_id = provider_id
            seller.save(update_fields=["linked_account_id", "updated_at"])
        audit.log(None, "marketplace.onboarding.recovered", operation, user=actor)
