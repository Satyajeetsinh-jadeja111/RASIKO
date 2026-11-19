from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.marketplace import batches, invoices, monitoring, operations
from apps.marketplace.models import LedgerEntry, SellerCase, Settlement
from apps.marketplace.settlements import prepare_reversals, reconcile_transfer
from apps.marketplace.tests.test_marketplace import market as market_fixture
from apps.payments.models import Refund
from conftest import dash_client

market = market_fixture

pytestmark = pytest.mark.django_db


def test_batch_fefo_expiry_and_cancellation(market, variant, place):
    _, team, _ = market
    batch = batches.receive(
        team.seller.owner, variant, "OPEN", timezone.localdate() + timedelta(days=2), 20, opening=True
    )
    order = place(qty=3)
    batch.refresh_from_db()
    assert batch.remaining == 14
    f = order.fulfillments.get()
    operations.cancel_fulfillment(team.seller.owner, f, "Customer cancelled before pickup")
    operations.cancel_fulfillment(team.seller.owner, f, "Duplicate request")
    batch.refresh_from_db()
    variant.refresh_from_db()
    assert batch.remaining == variant.stock_qty == 20
    batch.expires_on = timezone.localdate() - timedelta(days=1)
    batch.save()
    assert variant.available_qty == 0


def test_batch_expiry_blocks_dispatch(market, variant, place):
    from apps.marketplace.dispatch import mark_ready

    _, team, _ = market
    batch = batches.receive(team.seller.owner, variant, "EXP", timezone.localdate(), 20, opening=True)
    f = place().fulfillments.get()
    batch.expires_on = timezone.localdate() - timedelta(days=1)
    batch.save()
    with pytest.raises(ValidationError):
        mark_ready(team.seller.owner, f)


def test_invoice_snapshot_and_supplier_gate(market, place):
    _, team, territory = market
    f = place().fulfillments.get()
    with pytest.raises(ValidationError):
        invoices.issue(f)
    seller = team.seller
    seller.legal_name = "Sample seller"
    seller.business_address = "Rajkot, Gujarat"
    seller.state_code = "24"
    seller.signatory = "Sample owner"
    seller.save()
    territory.state_code = "24"
    territory.save()
    invoice = invoices.issue(f)
    assert invoices.issue(f).pk == invoice.pk
    seller.legal_name = "Changed supplier"
    seller.save()
    assert invoice.snapshot["seller"]["name"] == "Sample seller"
    assert len(invoice.number) <= 16
    assert invoices.pdf(invoice).startswith(b"%PDF")


def test_transferred_refund_reversal_allocates_only_excess(market, place):
    f = place().fulfillments.get()
    row = Settlement.objects.create(
        fulfillment=f, amount=f.total - Decimal("10"), provider_id="tr_test", status="transferred"
    )
    for amount in ("10", "20"):
        refund = Refund.objects.create(order=f.order, amount=amount, reason="Return", method="cash", status="succeeded")
        LedgerEntry.objects.create(
            fulfillment=f, kind="refund", amount=-Decimal(amount), key=f"refund:{refund.pk}:{f.pk}"
        )
    prepare_reversals(row)
    prepare_reversals(row)
    assert list(row.reversals.values_list("amount", flat=True)) == [Decimal("20")]


def test_provider_confirmation_required_for_bank_settlement(market, place):
    _, team, _ = market
    f = place().fulfillments.get()
    f.order.payment_method = "razorpay"
    f.order.save()
    from apps.payments.models import Payment

    Payment.objects.create(
        order=f.order, gateway="razorpay", gateway_payment_id="pay_test", amount=f.order.total, status="succeeded"
    )
    team.seller.linked_account_id = "acc_test"
    team.seller.save()
    row = Settlement.objects.create(fulfillment=f, amount=f.total, provider_id="tr_test", status="transferred")
    client = Mock()
    client.transfer.return_value = {
        "id": "tr_test",
        "recipient": "acc_test",
        "source": "pay_test",
        "amount": int(f.total * 100),
        "currency": "INR",
        "settlement_status": "pending",
    }
    reconcile_transfer(row.pk, client)
    row.refresh_from_db()
    assert row.status == "transferred"
    client.transfer.return_value.update(settlement_status="settled", recipient_settlement_id="setl_test")
    reconcile_transfer(row.pk, client)
    reconcile_transfer(row.pk, client)
    row.refresh_from_db()
    assert row.status == "settled"
    assert f.ledger.filter(kind="settlement").count() == 1


def test_support_scope_and_new_templates(market, place, customer, owner, client):
    head, team, _ = market
    f = place().fulfillments.get()
    case = SellerCase.objects.create(fulfillment=f, created_by=customer, subject="Wrong box")
    client = dash_client(client, head.user)
    for url in ["/partners/alerts/", "/partners/cases/", f"/partners/cases/{case.pk}/", "/partners/"]:
        assert client.get(url).status_code == 200
    assert client.get(f"/partners/business/{team.seller_id}/").status_code == 404
    client = dash_client(client, owner)
    assert client.get("/partners/operations-settings/").status_code == 200


def test_retention_keeps_financial_records(market, place):
    f = place().fulfillments.get()
    LedgerEntry.objects.create(fulfillment=f, kind="sale", amount=f.total, key="retention-sale")
    monitoring.scan()
    monitoring.retain()
    assert LedgerEntry.objects.filter(key="retention-sale").exists()


def test_onboarding_ambiguous_response_never_recreates(market):
    import requests

    from apps.marketplace.onboarding import _step

    _, team, _ = market
    create = Mock(side_effect=requests.Timeout())
    with pytest.raises(ValidationError):
        _step(team.seller, "account", create)
    with pytest.raises(ValidationError):
        _step(team.seller, "account", create)
    assert create.call_count == 1
    assert team.seller.onboarding_operations.get().status == "uncertain"


def test_onboarding_activation_requires_configured_bank(market):
    from apps.marketplace.models import OnboardingOperation
    from apps.marketplace.onboarding import refresh

    _, team, _ = market
    seller = team.seller
    seller.linked_account_id = "acc_test"
    seller.save()
    OnboardingOperation.objects.create(seller=seller, step="product", status="succeeded", provider_id="prod_test")
    client = Mock()
    client.account.return_value = {"id": "acc_test", "status": "created"}
    client.product.return_value = {"account_id": "acc_test", "product_name": "route", "activation_status": "activated"}
    refresh(seller.pk, client)
    seller.refresh_from_db()
    assert not seller.payments_ready
    OnboardingOperation.objects.create(seller=seller, step="configure", status="succeeded", provider_id="prod_test")
    refresh(seller.pk, client)
    seller.refresh_from_db()
    assert seller.payments_ready
    client.product.return_value["account_id"] = "acc_other"
    with pytest.raises(ValidationError):
        refresh(seller.pk, client)


def test_uncertain_reversal_recovers_without_duplicate(market, place, settings):
    from apps.marketplace.models import MarketplaceSettings, TransferReversal
    from apps.marketplace.settlements import submit_reversal

    settings.MARKETPLACE_ROUTE_APPROVED = True
    cfg = MarketplaceSettings.load()
    cfg.payouts_enabled = True
    cfg.save()
    f = place().fulfillments.get()
    row = Settlement.objects.create(fulfillment=f, amount=f.total, provider_id="tr_test", status="transferred")
    refund = Refund.objects.create(order=f.order, amount="10", reason="Return", method="cash", status="succeeded")
    reversal = TransferReversal.objects.create(
        settlement=row, refund=refund, amount="10", attempts=1, status="uncertain"
    )
    client = Mock()
    client.reversals.return_value = []
    submit_reversal(reversal.pk, client)
    client.reverse.assert_not_called()
    client.reversals.return_value = [
        {
            "id": "rev_test",
            "transfer_id": "tr_test",
            "amount": 1000,
            "currency": "INR",
            "notes": {"rasiko_reversal": str(reversal.key)},
        }
    ]
    submit_reversal(reversal.pk, client)
    reversal.refresh_from_db()
    assert reversal.status == "succeeded"
    assert f.ledger.filter(kind="transfer_reversal").count() == 1


def test_failed_jobs_remain_alerted_until_success():
    from types import SimpleNamespace

    from apps.marketplace.models import OperationalAlert
    from apps.marketplace.signals import record_failed_job, resolve_failed_job

    record_failed_job(task_id="sample-job", exception=ValueError("Do not store private payload"))
    monitoring.scan()
    alert = OperationalAlert.objects.get(key="job:sample-job")
    assert alert.resolved_at is None
    assert alert.kind == "failed_job"
    resolve_failed_job(sender=SimpleNamespace(request=SimpleNamespace(id="sample-job")))
    alert.refresh_from_db()
    assert alert.resolved_at is not None


def test_product_photos_are_scoped_and_reencoded(market, variant, client):
    import io

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    from apps.accounts.models import User

    _, team, _ = market
    client = dash_client(client, team.seller.owner)
    original = io.BytesIO()
    Image.new("RGB", (32, 32), "green").save(original, "PNG")
    response = client.post(
        f"/partners/products/{variant.product_id}/photo/",
        {
            "image": SimpleUploadedFile("photo.png", original.getvalue(), content_type="image/png"),
            "alt": "Sample product",
        },
    )
    assert response.status_code == 302
    photo = variant.product.images.get()
    assert photo.image.name.endswith(".webp")
    assert photo.responsive_images
    other = User.objects.create_user(email="other-seller@example.test", password="Other-Seller-123!", role="seller")
    client = dash_client(client, other)
    assert client.get(f"/partners/products/{variant.product_id}/photo/").status_code == 404
