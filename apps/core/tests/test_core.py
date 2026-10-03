import pytest
from django.test import RequestFactory

from apps.core import crypto
from apps.core.integrations import REGISTRY, get_config, is_enabled
from apps.core.models import Integration
from apps.core.utils import safe_next


def test_crypto_roundtrip_and_mask():
    token = crypto.encrypt_json({"api_key": "sk-live-123456"})
    assert "sk-live" not in token
    assert crypto.decrypt_json(token) == {"api_key": "sk-live-123456"}
    assert crypto.mask("sk-live-123456") == "•••• 3456"


@pytest.mark.django_db
class TestIntegrations:
    def test_all_paid_services_off_by_default(self):
        assert set(REGISTRY) >= {"razorpay", "stripe", "whatsapp", "claude", "sms", "smtp", "s3"}
        assert not any(is_enabled(s) for s in REGISTRY)

    def test_blank_secret_keeps_saved_value(self):
        row = Integration.objects.create(slug="claude", enabled=True)
        row.update_values({"api_key": "sk-ant-first", "model": "m"})
        row.save()
        changed = row.update_values({"api_key": "", "model": "m2"})
        row.save()
        assert changed == ["model"] and row.config()["api_key"] == "sk-ant-first"
        assert get_config("claude")["model"] == "m2"

    def test_disabled_returns_none(self):
        row = Integration.objects.create(slug="sms", enabled=False)
        row.update_values({"provider": "msg91", "api_key": "k", "sender_id": "RASIKO"})
        row.save()
        assert get_config("sms") is None
        assert row.missing_required() == []


@pytest.mark.parametrize(
    "nxt,expected", [("https://evil.example/", "/"), ("//evil.example/", "/"), ("/cart/", "/cart/")]
)
def test_safe_next_blocks_other_sites(nxt, expected, settings):
    settings.ALLOWED_HOSTS = ["rasiko.in"]
    req = RequestFactory().get("/", {"next": nxt}, HTTP_HOST="rasiko.in")
    assert safe_next(req, "/") == expected
