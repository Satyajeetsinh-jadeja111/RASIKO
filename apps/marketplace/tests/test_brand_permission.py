import pytest
from django.core.exceptions import ValidationError

from apps.accounts.models import User
from apps.catalog.models import Brand
from apps.marketplace.forms import SellerVerificationForm, TeamForm
from apps.marketplace.models import Head, Seller, SellerTeam

pytestmark = pytest.mark.django_db


def test_independent_multi_brand_and_head_restriction(owner):
    seller = Seller.objects.create(name="Independent", owner=owner)
    first = Brand.objects.create(name="First", slug="first")
    second = Brand.objects.create(name="Second", slug="second")
    a = SellerTeam.objects.create(seller=seller, brand=first)
    b = SellerTeam.objects.create(seller=seller, brand=second)
    head = Head.objects.create(user=owner)
    head.brands.add(first)
    a.head = head
    with pytest.raises(ValidationError, match="admin permission"):
        a.save()
    seller.allow_multiple_brands = True
    seller.save()
    a.save()
    seller.allow_multiple_brands = False
    with pytest.raises(ValidationError, match="Deactivate extra"):
        seller.save()
    b.active = False
    b.save()
    seller.save()
    with pytest.raises(ValidationError, match="admin permission"):
        b.active = True
        b.save()


def test_managed_seller_needs_permission_and_heads_can_share_brand(owner):
    seller = Seller.objects.create(name="Managed", owner=owner)
    brand = Brand.objects.create(name="Shared", slug="shared")
    other = Brand.objects.create(name="Other", slug="other")
    head = Head.objects.create(user=owner)
    user = User.objects.create_user(email="another-head@example.test", role="head")
    another = Head.objects.create(user=user)
    head.brands.add(brand)
    another.brands.add(brand)
    assert brand.heads.count() == 2
    SellerTeam.objects.create(seller=seller, brand=brand, head=head)
    form = TeamForm(
        owner, data={"seller": seller.pk, "brand": other.pk, "delivery_fee": "0", "estimated_minutes": "60"}
    )
    assert not form.is_valid()
    assert "admin permission" in str(form.errors)
    with pytest.raises(ValidationError, match="admin permission"):
        SellerTeam.objects.create(seller=seller, brand=other)
    seller.allow_multiple_brands = True
    seller.save()
    SellerTeam.objects.create(seller=seller, brand=other)
    assert "allow_multiple_brands" in SellerVerificationForm().fields
