import time

from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect


class StaffSessionMiddleware:
    """Dashboard users are signed out after inactivity; Owner/Manager must pass 2FA to open the dashboard."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.is_dashboard_user:
            now = int(time.time())
            last = request.session.get("staff_last_seen", now)
            if now - last > settings.STAFF_IDLE_TIMEOUT_SECONDS:
                logout(request)
                return redirect(f"/accounts/login/?next={request.path}")
            request.session["staff_last_seen"] = now
            if request.path.startswith("/" + settings.ADMIN_URL) or request.path.startswith(
                "/" + settings.DJANGO_ADMIN_URL
            ):
                if user.requires_2fa and not user.is_verified():
                    from django_otp.plugins.otp_totp.models import TOTPDevice

                    has = TOTPDevice.objects.filter(user=user, confirmed=True).exists()
                    return redirect(
                        ("/accounts/2fa/verify/" if has else "/accounts/2fa/setup/") + f"?next={request.path}"
                    )
        return self.get_response(request)
