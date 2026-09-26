import pytest

from apps.analytics import insights, reports
from apps.orders.services import set_status


@pytest.mark.django_db
def test_kpis_and_insights(place, staff_user):
    o = place(qty=4)
    set_status(o, "confirmed")
    place(qty=3)
    p = reports.Period.last_days(7)
    k = reports.kpis(p)
    assert k["orders"] == 2 and k["revenue"] > 0 and k["gross_margin"] == (50 - 35) * 7
    assert sum(d["orders"] for d in reports.daily(p)) == 2
    assert reports.top_products(p)[0]["qty"] == 7
    r = insights.build(7)
    assert r.going_well and r.pk
