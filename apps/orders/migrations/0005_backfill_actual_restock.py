from django.db import migrations
from django.db.models import Sum


def backfill(apps, schema_editor):
    movements = apps.get_model("inventory", "StockMovement")
    lines = apps.get_model("orders", "OrderLine")
    groups = movements.objects.filter(reason__in=["refund", "cancel"], order_id__isnull=False, delta__gt=0).values("order_id", "variant_id").annotate(bottles=Sum("delta"))
    for group in groups.iterator():
        remaining = group["bottles"]
        for line in lines.objects.filter(order_id=group["order_id"], variant_id=group["variant_id"]).order_by("pk"):
            count = min(line.qty, remaining // (line.units_per_box or 1))
            lines.objects.filter(pk=line.pk).update(restocked_qty=count)
            remaining -= count * (line.units_per_box or 1)


class Migration(migrations.Migration):
    dependencies = [("orders", "0004_orderline_restocked_qty"), ("inventory", "0002_initial")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
