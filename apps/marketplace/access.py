"""Central authority checks; submitted identifiers never grant access."""

from django.core.exceptions import PermissionDenied
from django.db.models import F

from .models import Head, SellerTeam


def is_admin(user):
    return user.is_authenticated and user.is_active and user.is_owner


def teams_for(user):
    qs = SellerTeam.objects.select_related("seller", "brand", "head__user")
    if not user.is_authenticated or not user.is_active:
        return qs.none()
    if is_admin(user):
        return qs
    if user.role == "head":
        return qs.filter(head__user=user, head__active=True, head__brands=F("brand")).distinct()
    if user.role == "seller":
        return qs.filter(seller__owner=user)
    return qs.none()


def require_team(user, team, *, manage=False):
    if not teams_for(user).filter(pk=team.pk).exists():
        raise PermissionDenied("This team is outside your authority.")
    if manage and not (is_admin(user) or user.role == "head"):
        raise PermissionDenied("Request changes from your Head or admin.")
    return team


def require_head(user, head):
    if not is_admin(user) and not (user.pk == head.user_id and user.role == "head" and head.active and user.is_active):
        raise PermissionDenied


def require_territory(user, team, territory):
    require_team(user, team, manage=True)
    if team.head_id and not team.head.territories.filter(pk=territory.pk).exists():
        raise PermissionDenied("Territory is outside the Head's jurisdiction.")


def seller_can_manage_rider(user, rider):
    if is_admin(user):
        return True
    if not user.is_authenticated or not user.is_active:
        return False
    if user.role == "seller" and rider.seller.owner_id == user.pk:
        return True
    if user.role == "head":
        return Head.objects.filter(
            user=user, active=True, teams__seller_id=rider.seller_id, teams__active=True
        ).exists()
    return False


def fulfillments_for(user):
    from .models import Fulfillment

    qs = Fulfillment.objects.filter(team__in=teams_for(user))
    if user.role == "head" and not is_admin(user):
        qs = qs.filter(territory__heads__user=user, territory__heads__active=True)
    return qs.distinct()
