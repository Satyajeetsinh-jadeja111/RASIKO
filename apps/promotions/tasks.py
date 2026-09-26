from celery import shared_task
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import StoreSettings
from apps.notifications import services as notify

from .models import CoinLedger


@shared_task
def birthday_coins():
    """Give birthday coins once a year, on the day."""
    amount = StoreSettings.load().birthday_coins
    if not amount:
        return 0
    today = timezone.localdate()
    given = 0
    for user in User.objects.filter(is_active=True, birthday__month=today.month, birthday__day=today.day):
        if CoinLedger.objects.filter(
            user=user, reason=CoinLedger.Reason.BIRTHDAY, created_at__year=today.year
        ).exists():
            continue
        CoinLedger.objects.create(user=user, delta=amount, reason=CoinLedger.Reason.BIRTHDAY, note="Happy birthday!")
        notify.send_email(user.email, "coins_bonus", {"user": user, "coins": amount, "reason": "your birthday"})
        given += 1
    return given
