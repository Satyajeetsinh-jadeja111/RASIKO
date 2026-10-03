from .models import AuditLog


def client_ip(request):
    if request is None:
        return None
    # Nginx sets X-Real-IP; never trust a client-supplied X-Forwarded-For chain blindly.
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR")


def log(request, action, obj=None, summary="", changes=None, user=None):
    """Write one audit log row. ``changes`` must never contain secrets."""
    return AuditLog.objects.create(
        user=user or (request.user if request is not None and request.user.is_authenticated else None),
        action=action,
        object_type=obj.__class__.__name__ if obj is not None else "",
        object_id=str(getattr(obj, "pk", "") or ""),
        summary=summary[:300],
        changes=changes or {},
        ip=client_ip(request),
    )
