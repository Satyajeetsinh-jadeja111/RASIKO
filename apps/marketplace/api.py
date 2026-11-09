import hashlib
import secrets
from datetime import timedelta
from decimal import InvalidOperation

from django.contrib.auth import authenticate
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, SessionAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from . import dispatch
from .models import DispatchOffer, Fulfillment, MarketplaceSettings, RiderAccount, RiderDevice, RiderToken
from .services import accept_invitation


class RiderAuthentication(BaseAuthentication):
    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        digest = hashlib.sha256(header[7:].encode()).hexdigest()
        token = (
            RiderToken.objects.select_related("rider__user")
            .filter(digest=digest, expires_at__gt=timezone.now(), rider__active=True, rider__user__is_active=True)
            .first()
        )
        if token is None:
            raise AuthenticationFailed("Expired or invalid rider token.")
        return token.rider.user, token

    def authenticate_header(self, request):
        return "Bearer"


class LoginThrottle(AnonRateThrottle):
    rate = "5/min"


class RiderView(APIView):
    authentication_classes = [RiderAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not MarketplaceSettings.load().enabled:
            raise PermissionDenied

    def handle_exception(self, exc):
        if isinstance(exc, ObjectDoesNotExist):
            return Response({"error": "Not found."}, status=404)
        if isinstance(exc, (ValidationError, ValueError, InvalidOperation)):
            return Response(
                {"error": " ".join(exc.messages) if isinstance(exc, ValidationError) else "Invalid request."},
                status=400,
            )
        return super().handle_exception(exc)

    def rider(self, request):
        return RiderAccount.objects.get(user=request.user, active=True, user__is_active=True, seller__status="active")


class Login(RiderView):
    authentication_classes = []
    permission_classes = []
    throttle_classes = [LoginThrottle]

    def post(self, request):
        user = authenticate(
            request=request._request,
            username=str(request.data.get("email", "")).strip(),
            password=request.data.get("password", ""),
        )
        if user is None:
            raise AuthenticationFailed("Invalid email or password.")
        if request.data.get("invitation"):
            accept_invitation(user, request.data["invitation"])
        rider = RiderAccount.objects.filter(user=user, active=True).first()
        if not rider:
            raise AuthenticationFailed("A seller invitation is required.")
        token = secrets.token_urlsafe(48)
        RiderToken.objects.create(
            rider=rider,
            digest=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=timezone.now() + timedelta(days=30),
        )
        return Response({"token": token, "name": user.display_name, "seller": rider.seller.name})


class Logout(RiderView):
    def post(self, request):
        if isinstance(request.auth, RiderToken):
            request.auth.delete()
        dispatch.heartbeat(request.user, online=False)
        return Response({"ok": True})


class Heartbeat(RiderView):
    def post(self, request):
        if not isinstance(request.data.get("online"), bool) or not isinstance(request.data.get("consent", False), bool):
            raise ValidationError("Availability and consent must be booleans.")
        rider = dispatch.heartbeat(
            request.user,
            online=request.data["online"],
            consent=request.data.get("consent", False),
            lat=request.data.get("lat"),
            lng=request.data.get("lng"),
        )
        return Response({"online": rider.online, "last_seen": rider.last_seen, "heartbeat_seconds": 30})


class Offers(RiderView):
    def get(self, request):
        rider = self.rider(request)
        offers = rider.offers.filter(
            status="pending", expires_at__gt=timezone.now(), fulfillment__status="ready"
        ).select_related("fulfillment__team__brand", "fulfillment__territory")
        return Response(
            [
                {
                    "id": o.pk,
                    "fulfillment": o.fulfillment_id,
                    "brand": o.fulfillment.team.brand.name,
                    "area": o.fulfillment.territory.name if o.fulfillment.territory else "",
                    "expires_at": o.expires_at,
                }
                for o in offers
            ]
        )


class Accept(RiderView):
    def post(self, request, pk):
        f = dispatch.accept_offer(request.user, pk)
        return Response({"fulfillment": f.pk, "status": f.status})


class Decline(RiderView):
    def post(self, request, pk):
        self.rider(request)
        changed = DispatchOffer.objects.filter(pk=pk, rider__user=request.user, status="pending").update(
            status="declined"
        )
        return Response({"ok": bool(changed)})


class Deliveries(RiderView):
    def get(self, request):
        rider = self.rider(request)
        rows = (
            Fulfillment.objects.filter(delivery_assignment__rider=rider)
            .select_related("order", "team__seller", "team__brand")
            .order_by("-created_at")[:100]
        )
        return Response(
            [
                {
                    "id": f.pk,
                    "status": f.status,
                    "seller": f.team.seller.name,
                    "brand": f.team.brand.name,
                    "recipient": f.order.ship_name,
                    "address": f.order.ship_address if f.status != "delivered" else "",
                    "phone": f.order.ship_phone if f.status != "delivered" else "",
                    "lat": str(f.order.ship_lat),
                    "lng": str(f.order.ship_lng),
                    "cod": str(f.total) if f.order.payment_method == "cod" else "0.00",
                }
                for f in rows
            ]
        )


class Action(RiderView):
    def post(self, request, pk, action):
        f = dispatch.delivery_action(request.user, pk, action, str(request.data.get("otp", "")))
        if f is None:
            return Response({"error": "Invalid code or too many attempts. Contact the seller."}, status=400)
        return Response({"status": f.status})


class Device(RiderView):
    def post(self, request):
        rider = self.rider(request)
        token, platform = request.data.get("token"), request.data.get("platform")
        if not isinstance(token, str) or len(token) > 4096 or not token or platform not in ("android", "ios"):
            raise ValidationError("A device token and platform are required.")
        RiderDevice.objects.filter(token=token).exclude(rider=rider).delete()
        RiderDevice.objects.update_or_create(rider=rider, token=token, defaults={"platform": platform, "active": True})
        return Response({"ok": True})


class Register(Login):
    def post(self, request):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.password_validation import validate_password
        from django.db import transaction

        from .models import RiderInvitation

        with transaction.atomic():
            token = str(request.data.get("invitation", ""))
            email = str(request.data.get("email", "")).strip().lower()
            invitation = RiderInvitation.objects.select_for_update().get(
                token_hash=hashlib.sha256(token.encode()).hexdigest()
            )
            if invitation.accepted_at or invitation.expires_at <= timezone.now() or invitation.email != email:
                raise ValidationError("Invalid invitation.")
            if get_user_model().objects.filter(email__iexact=email).exists():
                raise ValidationError("Account exists. Sign in with your invitation instead.")
            password = request.data.get("password", "")
            user = get_user_model()(email=email)
            validate_password(password, user=user)
            user = get_user_model().objects.create_user(email=email, password=password)
            rider = accept_invitation(user, token)
            secret = secrets.token_urlsafe(48)
            RiderToken.objects.create(
                rider=rider,
                digest=hashlib.sha256(secret.encode()).hexdigest(),
                expires_at=timezone.now() + timedelta(days=30),
            )
        return Response({"token": secret, "name": user.display_name, "seller": rider.seller.name}, status=201)
