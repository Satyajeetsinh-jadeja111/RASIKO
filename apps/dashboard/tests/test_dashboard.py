import csv
import io

import pytest

from apps.core.models import AuditLog, Integration
from apps.orders.services import set_status
from conftest import dash_client

A = "/manage/"


@pytest.mark.django_db
class TestAccess:
    def test_anonymous_redirected(self, client):
        r = client.get(A)
        assert r.status_code == 302 and "/accounts/login/" in r["Location"]

    def test_customer_forbidden(self, client, customer):
        client.force_login(customer)
        assert client.get(A).status_code == 403

    def test_owner_needs_2fa(self, client, owner):
        client.force_login(owner)
        r = client.get(A)
        assert r.status_code == 302 and "/accounts/2fa/" in r["Location"]

    @pytest.mark.parametrize(
        "url,code",
        [
            ("", 200),
            ("orders/", 200),
            ("stock/", 200),
            ("products/", 200),
            ("support/", 200),
            ("analytics/", 403),
            ("settings/integrations/", 403),
            ("c/coupons/", 403),
            ("settings/staff/", 403),
            ("customers/", 403),
            ("products/export/", 403),
        ],
    )
    def test_staff_limits(self, client, staff_user, url, code):
        client.force_login(staff_user)  # staff do not need 2FA
        assert client.get(A + url).status_code == code

    @pytest.mark.parametrize(
        "url,code",
        [
            ("analytics/", 200),
            ("settings/integrations/", 403),
            ("settings/staff/", 403),
            ("settings/audit/", 403),
            ("c/coupons/", 200),
        ],
    )
    def test_manager_limits(self, client, manager, url, code):
        assert dash_client(client, manager).get(A + url).status_code == code


@pytest.mark.django_db
class TestIntegrationsPage:
    def test_save_encrypts_masks_and_audits(self, client, owner):
        c = dash_client(client, owner)
        r = c.post(
            A + "settings/integrations/claude/",
            {
                "api_key": "sk-ant-secret-value-9876",
                "model": "claude-haiku-4-5-20251001",
                "insights_summary": "no",
                "enabled": "on",
                "action": "save",
            },
        )
        assert r.status_code == 302
        row = Integration.objects.get(slug="claude")
        assert row.enabled and "sk-ant" not in row.data_encrypted
        page = c.get(A + "settings/integrations/").content.decode()
        assert "sk-ant-secret-value-9876" not in page and "•••• 9876" in page
        log = AuditLog.objects.get(action="integration.update")
        assert "sk-ant" not in str(log.changes) and "api_key" in log.changes["fields_changed"]

    def test_cannot_enable_without_keys(self, client, owner):
        c = dash_client(client, owner)
        c.post(A + "settings/integrations/stripe/", {"publishable_key": "pk_test", "enabled": "on", "action": "save"})
        assert not Integration.objects.get(slug="stripe").enabled

    def test_remove_keys(self, client, owner):
        c = dash_client(client, owner)
        c.post(
            A + "settings/integrations/sms/",
            {"provider": "msg91", "api_key": "k", "sender_id": "RSK", "enabled": "on", "action": "save"},
        )
        c.post(A + "settings/integrations/sms/", {"action": "clear"})
        row = Integration.objects.get(slug="sms")
        assert not row.enabled and row.data_encrypted == ""


@pytest.mark.django_db
class TestOrdersAndStock:
    def test_staff_moves_order_but_cannot_refund(self, client, staff_user, place):
        o = place(qty=3)
        client.force_login(staff_user)
        client.post(A + f"orders/{o.number}/status/", {"status": "confirmed"})
        o.refresh_from_db()
        assert o.status == "confirmed"
        r = client.post(A + f"orders/{o.number}/refund/", {"amount": "10", "reason": "x", "method": "upi"})
        assert r.status_code == 403

    def test_delivery_code_required_for_staff(self, client, staff_user, place):
        o = place(qty=3)
        for s in ["confirmed", "packed", "out_for_delivery"]:
            o = set_status(o, s)
        o.delivery_otp = "4321"
        o.save()
        client.force_login(staff_user)
        client.post(A + f"orders/{o.number}/status/", {"status": "delivered", "otp": "0000"})
        o.refresh_from_db()
        assert o.status == "out_for_delivery"
        client.post(A + f"orders/{o.number}/status/", {"status": "delivered", "otp": "4321"})
        o.refresh_from_db()
        assert o.status == "delivered"

    def test_manager_manual_refund(self, client, manager, staff_user, place):
        o = place(qty=3)
        for s in ["confirmed", "packed", "out_for_delivery", "delivered"]:
            o = set_status(o, s)
        c = dash_client(client, manager)
        c.post(
            A + f"orders/{o.number}/refund/", {"amount": "25", "reason": "Warm", "method": "upi", "reference": "UPI1"}
        )
        o.refresh_from_db()
        assert str(o.refunded_total) == "25.00"

    def test_quick_stock(self, client, staff_user, variant):
        client.force_login(staff_user)
        r = client.post(A + f"stock/{variant.pk}/", {"action": "set_qty", "qty": "33", "reason": "manual"})
        variant.refresh_from_db()
        assert r.status_code == 200 and variant.stock_qty == 33
        client.post(A + f"stock/{variant.pk}/", {"action": "toggle_oos"})
        variant.refresh_from_db()
        assert variant.manual_out_of_stock and not variant.in_stock
        r = client.post(A + f"stock/{variant.pk}/", {"action": "set_qty", "qty": "-2"})
        assert "whole number" in r.content.decode()


@pytest.mark.django_db
def test_csv_export_blocks_formulas(client, manager, variant):
    variant.product.short_description = '=HYPERLINK("http://evil")'
    variant.product.save()
    c = dash_client(client, manager)
    body = c.get(A + "products/export/").content.decode("utf-8-sig")
    row = list(csv.DictReader(io.StringIO(body)))[0]
    assert row["short_description"].startswith("'=")


@pytest.mark.django_db
def test_csv_import_dry_run_and_save(client, manager, variant):
    c = dash_client(client, manager)
    data = (
        "sku,product_name,brand,variant_label,mrp,price,stock_qty,units_per_box,volume_ml\n"
        "ML-500,Mango Lassi,Gir Dairy,500 ml,60,45,30,24,500\n"
        "KC-200,Kokum Sharbat,Rasiko,200 ml,30,25,12,24,200\n"
    )
    f = io.BytesIO(data.encode())
    f.name = "p.csv"
    r = c.post(A + "products/import/", {"file": f, "dry_run": "1"})
    assert "look fine" in r.content.decode()
    variant.refresh_from_db()
    assert variant.price == 50
    f = io.BytesIO(data.encode())
    f.name = "p.csv"
    c.post(A + "products/import/", {"file": f})
    variant.refresh_from_db()
    assert variant.price == 45 and variant.previous_price == 50 and variant.stock_qty == 30
    from apps.catalog.models import ProductVariant

    assert ProductVariant.objects.get(sku="KC-200").stock_qty == 12


@pytest.mark.django_db
def test_every_dashboard_page_renders_for_owner(client, owner, place):
    o = place(qty=3)
    c = dash_client(client, owner)
    urls = [
        "",
        "orders/",
        f"orders/{o.number}/",
        f"orders/{o.number}/packing-slip/",
        "party-quotes/",
        "subscriptions/",
        "thandu/",
        "products/",
        "products/new/",
        "stock/",
        "stock/history/",
        "slider/",
        "slider/new/",
        "customers/",
        "reviews/",
        "support/",
        "competitors/",
        "analytics/",
        "analytics/delivery/",
        "insights/",
        "settings/store/",
        "settings/delivery/",
        "settings/integrations/",
        "settings/emails/",
        "settings/staff/",
        "settings/audit/",
        "c/categories/",
        "c/coupons/new/",
    ]
    for u in urls:
        assert c.get(A + u).status_code == 200, u
    for fmt in ("csv", "xlsx", "pdf"):
        assert c.get(A + f"analytics/?report=products&export={fmt}").status_code == 200
