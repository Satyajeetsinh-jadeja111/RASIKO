from django.shortcuts import render

from .models import StoreSettings

PERMISSIONS_POLICY = 'camera=(), microphone=(), geolocation=(self), payment=(self "https://js.stripe.com"), usb=()'
LAUNCH_BYPASS_PREFIXES = ("/static/", "/media/", "/healthz", "/payments/webhooks/", "/robots.txt")


class PermissionsPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        return response


class LaunchModeMiddleware:
    """Muhurat mode: before the go-live time, customers see a 'coming soon' page. Staff see the site."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings

        path = request.path
        if (
            path.startswith(LAUNCH_BYPASS_PREFIXES)
            or path.startswith("/" + settings.ADMIN_URL)
            or path.startswith("/" + settings.DJANGO_ADMIN_URL)
            or path.startswith("/accounts/")
        ):
            return self.get_response(request)
        store = StoreSettings.load()
        if not store.is_launched:
            user = getattr(request, "user", None)
            if not (user and user.is_authenticated and user.is_staff):
                return render(request, "storefront/coming_soon.html", {"store": store}, status=503)
        return self.get_response(request)
