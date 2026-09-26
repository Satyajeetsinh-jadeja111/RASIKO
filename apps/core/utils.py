from django.shortcuts import resolve_url
from django.utils.http import url_has_allowed_host_and_scheme


def safe_next(request, default):
    """Return ?next= / POST next only if it points to this site (no open redirects)."""
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, {request.get_host()}, require_https=request.is_secure()):
        return nxt
    return resolve_url(default)
