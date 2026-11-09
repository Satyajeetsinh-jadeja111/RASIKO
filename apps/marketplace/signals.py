from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.catalog.models import Product


@receiver(post_save, sender=Product)
def queue_translations(sender, instance, raw=False, **kwargs):
    if raw:
        return
    from .models import MarketplaceSettings

    if MarketplaceSettings.load().translations_enabled:
        from .translations import translate_product

        transaction.on_commit(lambda: translate_product.delay(instance.pk))


# Store only job identity, never arguments, provider payloads or exception strings.
from celery.signals import task_failure, task_success  # noqa: E402


@task_failure.connect
def record_failed_job(sender=None, task_id=None, **kwargs):
    if not task_id:
        return
    from .models import OperationalAlert

    OperationalAlert.objects.update_or_create(
        key=f"job:{task_id}", defaults={"kind": "failed_job", "resolved_at": None}
    )


@task_success.connect
def resolve_failed_job(sender=None, **kwargs):
    task_id = getattr(getattr(sender, "request", None), "id", None)
    if task_id:
        from django.utils import timezone

        from .models import OperationalAlert

        OperationalAlert.objects.filter(key=f"job:{task_id}", resolved_at=None).update(resolved_at=timezone.now())
