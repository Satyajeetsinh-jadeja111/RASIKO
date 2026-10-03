"""Rule-based insights: what is going well, what can be better, and what to do next.

Plain rules on the shop's own numbers, so it works with no paid service. If the Owner switches on the Claude
integration with "insights_summary = yes", a short plain-language summary is added on top.
"""

import logging

from apps.core.integrations import get_config

from . import reports
from .models import InsightReport

logger = logging.getLogger(__name__)


def _r(x):
    return f"₹{x:,.0f}"


def build(period_days=30):
    p = reports.Period.last_days(period_days)
    c = reports.compare(p)
    good, better, actions = [], [], []

    rev = c["revenue"]
    if rev["change"] is not None:
        line = (
            f"Sales {_r(rev['value'])} in the last {period_days} days, {abs(rev['change'])}% "
            f"{'up' if rev['change'] >= 0 else 'down'} from the {period_days} days before."
        )
        (good if rev["change"] >= 0 else better).append(line)
    elif rev["value"]:
        good.append(f"First {period_days} days of sales: {_r(rev['value'])} from {c['orders']['value']} orders.")

    if c["aov"]["change"] is not None:
        if c["aov"]["change"] >= 3:
            good.append(f"Average order grew to {_r(c['aov']['value'])} ({c['aov']['change']}% up).")
        elif c["aov"]["change"] <= -3:
            better.append(f"Average order fell to {_r(c['aov']['value'])} ({abs(c['aov']['change'])}% down).")
            actions.append("Promote a combo or a 'free delivery above' nudge to lift basket size.")

    if c["repeat_rate"]["value"] >= 30:
        good.append(f"{c['repeat_rate']['value']}% of customers ordered more than once.")
    elif c["customers"]["value"] >= 10:
        better.append(f"Only {c['repeat_rate']['value']}% of customers came back for a second order.")
        actions.append(
            "Send a small coupon to customers who ordered once, or start subscriptions for daily items "
            "like milk and chaas."
        )

    if c["cancel_rate"]["value"] > 5:
        better.append(f"{c['cancel_rate']['value']}% of orders were cancelled ({c['cancelled']['value']} orders).")
        actions.append("Check cancel reasons in Orders; most come from out-of-stock items or slow confirmation.")

    slow, total = reports.slow_confirm(p)
    if total and slow / total > 0.1:
        better.append(f"{slow} of {total} orders waited more than 10 minutes to be confirmed.")
        actions.append("Keep the dashboard open with sound on at the counter so new orders ring right away.")

    dn = c["delivery_net"]["value"]
    if c["orders"]["value"] and dn < 0:
        better.append(f"Delivery costs more than it earns: {_r(-dn)} spent beyond fees collected.")
        actions.append(
            "Try the what-if calculator in Analytics: a slightly higher far-distance slab or a higher "
            "free-delivery threshold for far areas."
        )
    elif dn > 0:
        good.append(f"Delivery covered its own cost with {_r(dn)} to spare.")

    top = reports.top_products(p, 3)
    if top:
        names = ", ".join(f"{t['variant__product__name']} {t['variant_label']}" for t in top)
        good.append(f"Best sellers: {names}.")

    for v, days_left, rate in reports.stock_risks(p, 5):
        better.append(f"{v.product.name} {v.label} may run out in about {days_left} days (sells {rate}/day).")
        actions.append(f"Reorder {v.product.name} {v.label} now.")

    idle = reports.not_selling(p, 5)
    if idle:
        better.append("No sales in this period for: " + ", ".join(f"{v.product.name} {v.label}" for v in idle) + ".")
        actions.append("Feature slow items on the home page, bundle them in a combo, or stop restocking them.")

    fun = reports.funnel(p)
    if fun[0]["sessions"] >= 50 and fun[1]["sessions"]:
        checkout, ordered = fun[2]["sessions"], fun[3]["sessions"]
        if checkout and ordered / checkout < 0.6:
            better.append(f"Only {round(ordered * 100 / checkout)}% of shoppers who reached checkout placed the order.")
            actions.append("Check that online payment is switched on and delivery fees are clear before checkout.")

    grid, peak = reports.heatmap(p)
    if peak:
        wd, hr = max(((d, h) for d in range(7) for h in range(24)), key=lambda x: grid[x[0]][x[1]])
        day = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][wd]
        good.append(f"Busiest time: {day} around {hr % 12 or 12} {'AM' if hr < 12 else 'PM'}.")
        actions.append(
            f"Keep extra stock chilled and a second rider ready on {day} around {hr % 12 or 12} "
            f"{'AM' if hr < 12 else 'PM'}."
        )

    report = InsightReport.objects.create(
        period_days=period_days, going_well=good, can_be_better=better, actions=actions[:8]
    )
    _add_ai_summary(report)
    return report


def _add_ai_summary(report):
    cfg = get_config("claude")
    if not cfg or cfg.get("insights_summary") != "yes":
        return
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=cfg["api_key"])
        facts = "\n".join(
            [
                "Going well:",
                *report.going_well,
                "Can be better:",
                *report.can_be_better,
                "Suggested actions:",
                *report.actions,
            ]
        )
        msg = client.messages.create(
            model=cfg.get("model") or "claude-haiku-4-5-20251001",
            max_tokens=400,
            system="You advise the owner of a small cold drinks and beverages shop in Rajkot. Write 4 short, "
            "friendly sentences in plain English: the headline, the biggest risk, and the two most useful "
            "things to do this week. Use only the facts given.",
            messages=[{"role": "user", "content": facts}],
        )
        report.ai_summary = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")[:2000]
        report.save(update_fields=["ai_summary"])
    except Exception:  # noqa: BLE001 - the rule-based report still stands
        logger.exception("Claude insights summary failed")
