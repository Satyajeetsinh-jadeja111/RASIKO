import hashlib
import secrets
from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core import audit

from .access import is_admin, require_head, require_team, require_territory, seller_can_manage_rider
from .models import (
    DispatchOffer,
    FeePolicy,
    Fulfillment,
    HeadCampaign,
    LedgerEntry,
    MarketplaceSettings,
    Notice,
    RiderAccount,
    RiderEvent,
    RiderInvitation,
    SellerTeam,
    Settlement,
    TerritoryAssignment,
    TerritoryRequest,
)


def notice(seller, title, message):
    row = Notice.objects.create(seller=seller, title=title, message=message)
    from .tasks import email_notice

    transaction.on_commit(lambda: email_notice.delay(row.pk))
    return row


def effective_policy(team):
    cfg = MarketplaceSettings.load()
    operational = team.active and team.seller.status == "active" and team.seller.verified
    if team.head_id:
        operational = (
            operational
            and team.head.active
            and team.head.user.is_active
            and team.head.brands.filter(pk=team.brand_id).exists()
        )
    return {
        "operational": bool(operational),
        "online": bool(
            operational
            and (cfg.online_override if cfg.online_override is not None else team.online_enabled)
            and team.seller.payments_ready
            and team.seller.linked_account_id
        ),
        "cod": bool(operational and (cfg.cod_override if cfg.cod_override is not None else team.cod_enabled)),
        "fast": False,
        "head_id": team.head_id,
    }


@transaction.atomic
def assign_territory(actor, team, territory, effective_at=None):
    team = SellerTeam.objects.select_for_update(of=("self",)).get(pk=team.pk)
    require_territory(actor, team, territory)
    type(territory).objects.select_for_update(of=("self",)).get(pk=territory.pk)
    if (
        TerritoryAssignment.objects.filter(brand=team.brand, territory=territory, active=True)
        .exclude(team=team)
        .exists()
    ):
        raise ValidationError("This brand already has a seller in that area.")
    assignment, _ = TerritoryAssignment.objects.get_or_create(
        team=team,
        territory=territory,
        active=True,
        defaults={"brand": team.brand, "effective_at": effective_at or timezone.now()},
    )
    audit.log(None, "marketplace.territory.assigned", assignment, user=actor)
    notice(team.seller, "Territory assigned", str(territory))
    return assignment


@transaction.atomic
def decide_territory(actor, request_id, approve, reason):
    req = (
        TerritoryRequest.objects.select_for_update(of=("self",))
        .select_related("team__head", "territory")
        .get(pk=request_id)
    )
    require_team(actor, req.team, manage=True)
    if req.status != "pending" or not reason.strip():
        raise ValidationError("A pending request and decision reason are required.")
    if approve:
        assign_territory(actor, req.team, req.territory)
    req.status = "approved" if approve else "rejected"
    req.decided_by, req.decision_reason, req.effective_at = actor, reason[:300], timezone.now()
    req.save()
    audit.log(None, "marketplace.territory.decided", req, user=actor)
    return req


@transaction.atomic
def set_team_status(actor, team, active, reason):
    team = SellerTeam.objects.select_for_update(of=("self",)).get(pk=team.pk)
    require_team(actor, team, manage=True)
    if not active and not reason.strip():
        raise ValidationError("Suspension/removal requires a reason.")
    if not active and team.fulfillments.exclude(status__in=["delivered", "cancelled"]).exists():
        raise ValidationError("Resolve active orders before removing this team.")
    team.active, team.reason = active, reason[:300]
    team.save(update_fields=["active", "reason", "updated_at"])
    if not active:
        team.assignments.filter(active=True).update(active=False)
        DispatchOffer.objects.filter(fulfillment__team=team, status="pending").update(status="expired")
    audit.log(None, "marketplace.team.status", team, changes={"active": active, "reason": reason[:300]}, user=actor)
    notice(team.seller, "Team status changed", reason or "Team activated")


@transaction.atomic
def set_online(actor, team, enabled):
    require_team(actor, team, manage=True)
    if enabled:
        from apps.payments.gateways import online_gateway

        if online_gateway() != "razorpay" or not team.seller.payments_ready or not team.seller.linked_account_id:
            raise ValidationError(
                "Approved Razorpay linked-account onboarding and an enabled Razorpay gateway are required."
            )
    team.online_enabled = enabled
    team.save(update_fields=["online_enabled", "updated_at"])
    audit.log(None, "marketplace.team.online", team, changes={"enabled": enabled}, user=actor)
    notice(team.seller, "Payment availability changed", "Online enabled" if enabled else "COD only")


@transaction.atomic
def schedule_fee(actor, percent, enabled, effective_at):
    if not is_admin(actor):
        raise PermissionDenied
    if effective_at < timezone.now() + timedelta(days=7):
        raise ValidationError("Give sellers at least seven days' notice.")
    policy = FeePolicy(percent=percent, enabled=enabled, effective_at=effective_at, created_by=actor)
    policy.full_clean()
    policy.save()
    from .models import Seller

    for seller in Seller.objects.filter(status="active"):
        notice(
            seller,
            "Platform fee change",
            f"{percent if enabled else 0}% from {effective_at.isoformat()}. Existing orders are unchanged.",
        )
    audit.log(None, "marketplace.fee.scheduled", policy, user=actor)
    return policy


@transaction.atomic
def create_campaign(actor, head, coupon, teams, territories=()):
    require_head(actor, head)
    teams, territories = list(teams), list(territories)
    if not teams or any(t.head_id != head.pk or not head.brands.filter(pk=t.brand_id).exists() for t in teams):
        raise PermissionDenied("Select only this Head's teams.")
    if any(not head.territories.filter(pk=t.pk).exists() for t in territories):
        raise PermissionDenied
    campaign = HeadCampaign.objects.create(head=head, coupon=coupon)
    campaign.teams.set(teams)
    campaign.territories.set(territories)
    for seller_id in {t.seller_id for t in teams}:
        from .models import Seller

        notice(
            Seller.objects.get(pk=seller_id),
            "Seller-funded offer",
            f"{coupon.code}: {coupon.label}. Discount deducted from eligible sales.",
        )
    audit.log(None, "marketplace.campaign.created", campaign, user=actor)
    return campaign


@transaction.atomic
def invite_rider(actor, seller, email):
    if not seller_can_manage_rider(actor, RiderAccount(seller=seller)):
        raise PermissionDenied
    token = secrets.token_urlsafe(32)
    invitation = RiderInvitation.objects.create(
        seller=seller,
        email=email.strip().lower(),
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=timezone.now() + timedelta(days=2),
        created_by=actor,
    )
    audit.log(None, "marketplace.rider.invited", invitation, user=actor)
    return invitation, token


@transaction.atomic
def accept_invitation(user, token):
    invitation = RiderInvitation.objects.select_for_update(of=("self",)).get(
        token_hash=hashlib.sha256(token.encode()).hexdigest()
    )
    if (
        invitation.accepted_at
        or invitation.expires_at <= timezone.now()
        or invitation.email != user.email.lower()
        or not user.is_active
    ):
        raise ValidationError("Invalid or expired invitation.")
    if user.role not in ("customer", "rider") or RiderAccount.objects.filter(user=user).exists():
        raise ValidationError("Account cannot be registered as this seller's rider.")
    rider = RiderAccount.objects.create(user=user, seller=invitation.seller)
    user.role = "rider"
    user.save(update_fields=["role"])
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["accepted_at"])
    RiderEvent.objects.create(rider=rider, kind="registered")
    return rider


@transaction.atomic
def suspend_rider(actor, rider, reason):
    rider = RiderAccount.objects.select_for_update(of=("self",)).select_related("seller").get(pk=rider.pk)
    if not seller_can_manage_rider(actor, rider):
        raise PermissionDenied
    if not reason.strip():
        raise ValidationError("A suspension/removal reason is required.")
    if rider.deliveries.filter(active=True).exists():
        raise ValidationError("Resolve or reassign the active delivery first.")
    rider.active, rider.online, rider.reason = False, False, reason[:300]
    rider.save()
    rider.offers.filter(status="pending").update(status="expired")
    RiderEvent.objects.create(rider=rider, kind="suspended", details={"reason": reason[:300], "by": actor.pk})
    audit.log(None, "marketplace.rider.suspended", rider, changes={"reason": reason[:300]}, user=actor)


def record_sale(f):
    for kind, amount in [
        ("sale", f.subtotal + f.delivery_fee),
        ("discount", -f.discount),
        ("platform_fee", -f.platform_fee),
    ]:
        LedgerEntry.objects.get_or_create(
            key=f"{f.pk}:{kind}", defaults={"fulfillment": f, "kind": kind, "amount": amount}
        )
    if f.order.payment_method != "cod":
        from django.db.models import Sum

        from .settlements import seller_balance

        refunded = -(f.ledger.filter(kind="refund").aggregate(n=Sum("amount"))["n"] or 0)
        Settlement.objects.get_or_create(
            fulfillment=f,
            defaults={
                "amount": seller_balance(f, refunded),
                "status": "eligible",
            },
        )


@transaction.atomic
def acknowledge_cod(actor, fulfillment):
    f = (
        Fulfillment.objects.select_for_update(of=("self",))
        .select_related("team__seller", "order")
        .get(pk=fulfillment.pk)
    )
    if not is_admin(actor) and actor.pk != f.team.seller.owner_id:
        raise PermissionDenied
    if f.status != "delivered" or f.order.payment_method != "cod":
        raise ValidationError("Only delivered COD collections can be remitted.")
    entry, _ = LedgerEntry.objects.get_or_create(
        key=f"{f.pk}:cod_remitted", defaults={"fulfillment": f, "kind": "cod_remitted", "amount": f.total}
    )
    audit.log(None, "marketplace.cod.remitted", entry, user=actor)
    return entry


def new_delivery_code():
    code = f"{secrets.randbelow(1000000):06}"
    return code, make_password(code)
