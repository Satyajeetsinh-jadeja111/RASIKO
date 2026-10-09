import hashlib
import secrets
import uuid
from datetime import timedelta

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, email, password, **extra):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, username=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.update(is_staff=True, is_superuser=True, role=User.Role.OWNER)
        return self._create(email, password, **extra)


class User(AbstractUser):
    class Role(models.TextChoices):
        CUSTOMER = "customer", _("Customer")
        STAFF = "staff", _("Staff")
        MANAGER = "manager", _("Manager")
        OWNER = "owner", _("Owner")

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    email = models.EmailField(_("email"), unique=True)
    phone = models.CharField(max_length=15, blank=True, db_index=True)
    phone_verified = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.CUSTOMER)
    birthday = models.DateField(null=True, blank=True)
    preferred_language = models.CharField(max_length=5, default="en")
    cod_blocked = models.BooleanField(default=False)
    referral_code = models.CharField(max_length=12, unique=True, blank=True)
    referred_by = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="referrals")
    marketing_opt_in = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def save(self, *args, **kwargs):
        self.email = (self.email or "").lower()
        self.username = self.email
        if not self.referral_code:
            self.referral_code = secrets.token_hex(4).upper()
        if self.role != self.Role.CUSTOMER:
            self.is_staff = True
        super().save(*args, **kwargs)

    def __str__(self):
        return self.get_full_name() or self.email

    # Role helpers -------------------------------------------------------------
    @property
    def is_owner(self):
        return self.is_superuser or self.role == self.Role.OWNER

    @property
    def is_manager_or_owner(self):
        return self.is_owner or self.role == self.Role.MANAGER

    @property
    def is_dashboard_user(self):
        return self.is_active and (self.is_superuser or self.role != self.Role.CUSTOMER)

    @property
    def requires_2fa(self):
        return self.is_manager_or_owner

    @property
    def display_name(self):
        return self.first_name or self.email.split("@")[0]


class Address(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="addresses")
    label = models.CharField(max_length=30, default="Home")
    name = models.CharField(max_length=80)
    phone = models.CharField(max_length=15)
    line1 = models.CharField(_("House / flat, building"), max_length=160)
    line2 = models.CharField(_("Area, street, landmark"), max_length=160, blank=True)
    city = models.CharField(max_length=40, default="Rajkot")
    pincode = models.CharField(max_length=6)
    lat = models.DecimalField(max_digits=9, decimal_places=6)
    lng = models.DecimalField(max_digits=9, decimal_places=6)
    is_default = models.BooleanField(default=False)
    # "Removed" by the customer but still linked to past orders, so it is hidden instead of deleted.
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_default", "-created_at"]
        verbose_name_plural = "addresses"

    def __str__(self):
        return f"{self.label}: {self.line1}, {self.pincode}"

    def as_text(self):
        parts = [self.line1, self.line2, f"{self.city} {self.pincode}"]
        return ", ".join(p for p in parts if p)


class OneTimeCode(models.Model):
    """Hashed OTP for phone verification (COD), order tracking and delivery handover checks."""

    class Purpose(models.TextChoices):
        PHONE_VERIFY = "phone", "Phone verification"
        TRACK_ORDER = "track", "Order tracking"

    purpose = models.CharField(max_length=10, choices=Purpose.choices)
    target = models.CharField(max_length=254, db_index=True)  # phone or email
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    MAX_ATTEMPTS = 5

    @staticmethod
    def _hash(code: str, target: str) -> str:
        return hashlib.sha256(f"{target}:{code}".encode()).hexdigest()

    @classmethod
    def issue(cls, purpose, target, minutes=10) -> str:
        code = f"{secrets.randbelow(1_000_000):06d}"
        cls.objects.filter(purpose=purpose, target=target, used=False).update(used=True)
        cls.objects.create(
            purpose=purpose,
            target=target,
            code_hash=cls._hash(code, target),
            expires_at=timezone.now() + timedelta(minutes=minutes),
        )
        return code

    @classmethod
    def verify(cls, purpose, target, code) -> bool:
        otp = cls.objects.filter(purpose=purpose, target=target, used=False).order_by("-created_at").first()
        if not otp or otp.expires_at < timezone.now() or otp.attempts >= cls.MAX_ATTEMPTS:
            return False
        otp.attempts += 1
        ok = secrets.compare_digest(otp.code_hash, cls._hash((code or "").strip(), target))
        otp.used = ok
        otp.save(update_fields=["attempts", "used"])
        return ok
