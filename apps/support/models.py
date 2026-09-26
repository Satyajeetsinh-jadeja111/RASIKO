import uuid

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStamped


class FaqArticle(TimeStamped):
    class Topic(models.TextChoices):
        ORDERS = "orders", _("Orders")
        DELIVERY = "delivery", _("Delivery")
        PAYMENTS = "payments", _("Payments")
        REFUNDS = "refunds", _("Refunds")
        ACCOUNT = "account", _("Account")
        PRODUCTS = "products", _("Products")

    topic = models.CharField(max_length=10, choices=Topic.choices)
    question = models.CharField(max_length=200)
    answer = models.TextField()
    keywords = models.CharField(max_length=300, blank=True, help_text=_("Extra words customers might use"))
    is_published = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    search_vector = SearchVectorField(null=True, editable=False)

    class Meta:
        ordering = ["topic", "sort_order", "question"]
        indexes = [GinIndex(fields=["search_vector"])]

    def __str__(self):
        return self.question


class Ticket(TimeStamped):
    class State(models.TextChoices):
        OPEN = "open", _("Open")
        WAITING = "waiting", _("Waiting for customer")
        CLOSED = "closed", _("Closed")

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    email = models.EmailField()
    name = models.CharField(max_length=80, blank=True)
    subject = models.CharField(max_length=160)
    state = models.CharField(max_length=10, choices=State.choices, default=State.OPEN, db_index=True)
    order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.subject


class ChatSession(TimeStamped):
    class Mode(models.TextChoices):
        BOT = "bot", _("Assistant")
        HUMAN = "human", _("Team")
        CLOSED = "closed", _("Closed")

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    session_key = models.CharField(max_length=64, blank=True, db_index=True)
    language = models.CharField(max_length=5, default="en")
    mode = models.CharField(max_length=6, choices=Mode.choices, default=Mode.BOT)
    ticket = models.OneToOneField(Ticket, null=True, blank=True, on_delete=models.SET_NULL, related_name="chat")
    verified_order_ids = models.JSONField(default=list, blank=True, help_text="Orders proven via OTP in this chat")

    class Meta:
        ordering = ["-updated_at"]


class ChatMessage(models.Model):
    class Role(models.TextChoices):
        USER = "user", _("Customer")
        ASSISTANT = "assistant", _("Assistant")
        STAFF = "staff", _("Rasiko Team")
        SYSTEM = "system", _("System")

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=Role.choices)
    text = models.TextField(max_length=2000)
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
