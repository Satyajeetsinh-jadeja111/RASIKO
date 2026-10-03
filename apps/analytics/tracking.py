import logging

from .models import ProductView

log = logging.getLogger(__name__)


def track(request, step, product=None):
    """Record a funnel step (view / cart / checkout / order) for the abandonment funnel. Never raises."""
    try:
        if not request.session.session_key:
            request.session.save()
        ProductView.objects.create(step=step, session_key=request.session.session_key or "", product=product)
    except Exception:  # noqa: BLE001
        log.debug("funnel tracking skipped", exc_info=True)
