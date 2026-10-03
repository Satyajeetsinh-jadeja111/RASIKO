from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.images import RandomUploadPath
from apps.core.models import TimeStamped


class Review(TimeStamped):
    class State(models.TextChoices):
        PENDING = "pending", _("Waiting for approval")
        APPROVED = "approved", _("Approved")
        HIDDEN = "hidden", _("Hidden")

    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="reviews")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews")
    order_line = models.OneToOneField("orders.OrderLine", on_delete=models.CASCADE, related_name="review")
    stars = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    title = models.CharField(max_length=80)
    body = models.TextField(max_length=1500, blank=True)
    state = models.CharField(max_length=10, choices=State.choices, default=State.PENDING, db_index=True)
    flagged = models.BooleanField(default=False, help_text=_("Matched the bad-word filter"))
    reply = models.TextField(blank=True)
    replied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.stars}★ {self.product}"


class ReviewPhoto(models.Model):
    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to=RandomUploadPath("reviews"))
