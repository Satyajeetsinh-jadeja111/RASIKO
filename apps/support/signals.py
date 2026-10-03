from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import FaqArticle


@receiver(post_save, sender=FaqArticle)
def refresh_search(sender, instance, raw=False, **kwargs):
    """Keep the help chat's search index in step with edits made in the dashboard."""
    if not raw:
        from .ai import update_faq_vector

        update_faq_vector(instance)
