from django.db import migrations
from django.db.models import F


def preserve_operations(apps, schema_editor):
    events = apps.get_model("payments", "WebhookEvent")
    events.objects.exclude(payload__has_key="kind").update(status="processed", processed_at=F("received_at"))
    refunds = apps.get_model("payments", "Refund")
    # Previous releases restocked on submission; never restock those rows twice.
    refunds.objects.filter(restock=True).update(restocked=True)
    refunds.objects.filter(status="pending").update(submission_started_at=F("created_at"), submission_uncertain=True)
    payments = apps.get_model("payments", "Payment")
    payments.objects.filter(gateway_order_id="").update(creation_started_at=F("created_at"), creation_uncertain=True)


class Migration(migrations.Migration):
    dependencies = [("payments", "0002_payment_creation_started_at_and_more")]
    operations = [migrations.RunPython(preserve_operations, migrations.RunPython.noop)]
