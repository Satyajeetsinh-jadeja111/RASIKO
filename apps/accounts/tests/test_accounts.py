import pytest

from apps.accounts.models import OneTimeCode, User


@pytest.mark.django_db
def test_signup_login_logout(client):
    r = client.post(
        "/accounts/signup/",
        {"first_name": "Ravi", "email": "Ravi@Example.com", "phone": "98765 43210", "password1": "Chaas-Glass-2026!"},
    )
    assert r.status_code == 302
    u = User.objects.get(email="ravi@example.com")
    assert u.phone == "9876543210" and u.role == "customer" and u.referral_code
    client.post("/accounts/logout/")
    r = client.post("/accounts/login/", {"username": "ravi@example.com", "password": "Chaas-Glass-2026!"})
    assert r.status_code == 302


@pytest.mark.django_db
def test_login_rejects_open_redirect(client, customer):
    r = client.post(
        "/accounts/login/?next=https://evil.example/",
        {"username": customer.email, "password": "Kesar-Lassi-2026!", "next": "https://evil.example/"},
    )
    assert r["Location"] == "/"


@pytest.mark.django_db
def test_owner_login_goes_to_2fa(client, owner):
    r = client.post("/accounts/login/", {"username": owner.email, "password": "Staff-Pass-2026!!"})
    assert "/accounts/2fa/setup/" in r["Location"]


@pytest.mark.django_db
def test_one_time_code():
    code = OneTimeCode.issue(OneTimeCode.Purpose.PHONE_VERIFY, "9876543210")
    assert not OneTimeCode.verify(
        OneTimeCode.Purpose.PHONE_VERIFY, "9876543210", "000000" if code != "000000" else "111111"
    )
    assert OneTimeCode.verify(OneTimeCode.Purpose.PHONE_VERIFY, "9876543210", code)
    assert not OneTimeCode.verify(OneTimeCode.Purpose.PHONE_VERIFY, "9876543210", code)  # single use


@pytest.mark.django_db
def test_customer_sees_only_own_order(client, place, customer):
    o = place(qty=3)
    other = User.objects.create_user(email="x@example.com", password="Another-Pass-2026!")
    client.force_login(other)
    assert client.get(o.get_absolute_url()).status_code == 404
    client.force_login(customer)
    assert client.get(o.get_absolute_url()).status_code == 200
