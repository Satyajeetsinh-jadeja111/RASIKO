import json

import pytest

from apps.support.models import ChatSession, FaqArticle, Ticket


@pytest.mark.django_db
def test_faq_bot_answers_without_claude(client):
    FaqArticle.objects.create(
        topic="delivery",
        question="What are your delivery timings?",
        answer="We deliver from 8 AM to 11 PM.",
        keywords="time hours timing",
    )
    r = client.post("/help/chat/send/", json.dumps({"text": "delivery timings?"}), content_type="application/json")
    data = json.loads(r.content)
    assert r.status_code == 200 and any("8 AM" in m["text"] for m in data["messages"])


@pytest.mark.django_db
def test_handoff_creates_ticket_and_staff_reply_emails(client, staff_user, mailoutbox=None):
    client.post("/help/chat/send/", json.dumps({"text": "My order is late"}), content_type="application/json")
    r = client.post("/help/chat/handoff/", json.dumps({"email": "guest@example.com"}), content_type="application/json")
    assert json.loads(r.content)["mode"] == "human"
    t = Ticket.objects.get()
    staff = client.__class__()
    staff.force_login(staff_user)
    staff.post(f"/manage/support/{t.public_id}/", {"action": "reply", "text": "On the way!"})
    t.refresh_from_db()
    assert t.state == "waiting"
    r = client.get("/help/chat/poll/?after=0")
    assert any(m["role"] == "staff" and m["text"] == "On the way!" for m in json.loads(r.content)["messages"])
    assert ChatSession.objects.get().mode == "human"
