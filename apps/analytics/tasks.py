from celery import shared_task
from django.utils import timezone

from apps.notifications import services as notify

from . import insights, reports


@shared_task
def daily_insights():
    return insights.build(30).pk


def _summary(days, key, title):
    p = reports.Period.last_days(days)
    k = reports.kpis(p)
    data = {
        "Orders": k["orders"],
        "Sales": f"₹{k['revenue']:,.2f}",
        "Average order": f"₹{k['aov']:,.2f}",
        "New customers": k["new_customers"],
        "Cancelled": k["cancelled"],
        "Refunds": f"₹{k['refunds']:,.2f}",
        "Delivery fees minus cost": f"₹{k['delivery_net']:,.2f}",
    }
    top = reports.top_products(p, 5)
    if top:
        data["Top sellers"] = ", ".join(f"{t['variant__product__name']} ({t['qty']})" for t in top)
    latest = insights.InsightReport.objects.first()
    from apps.notifications.models import NotificationSettings

    s = NotificationSettings.load()
    if s.recipients() and s.is_on(key):
        notify.send_email(
            s.recipients(),
            "admin_summary",
            {
                "title": title,
                "data": data,
                "insights": (latest.actions[:5] if latest else []),
                "subject_vars": {"title": title},
            },
        )


@shared_task
def daily_summary():
    _summary(1, "daily_summary", f"Daily summary {timezone.localdate():%d %b}")


@shared_task
def weekly_summary():
    _summary(7, "weekly_summary", f"Weekly summary to {timezone.localdate():%d %b}")
