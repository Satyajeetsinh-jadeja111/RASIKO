from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Product
from .search import update_search_vector


@receiver(post_save, sender=Product)
def refresh_search(sender, instance, **kwargs):
    update_search_vector(instance)
