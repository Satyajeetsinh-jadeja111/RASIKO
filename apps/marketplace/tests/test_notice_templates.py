"""Exercise the actual email renderers so incomplete source snapshots fail early."""

import pytest

from apps.notifications.services import render_email

pytestmark = pytest.mark.django_db


def test_partner_notice_renders_html_and_plain_text():
    html, text = render_email("partner_notice", {"title": "Area approved", "message": "<script>unsafe</script>"})
    assert "Area approved" in html
    assert "&lt;script&gt;unsafe&lt;/script&gt;" in html
    assert "<script>unsafe</script>" not in html
    assert "/partners/" in text
    assert "Area approved" in text


def test_delivery_code_renders_in_both_email_formats():
    html, text = render_email("marketplace_delivery", {"code": "123456", "brand": "Test brand"})
    for rendered in (html, text):
        assert "123456" in rendered
        assert "Test brand" in rendered
