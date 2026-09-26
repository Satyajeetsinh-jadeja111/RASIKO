from django.utils.translation import gettext_lazy as _

LANDINGS = {
    "cold-drinks-delivery-rajkot": {
        "title": _("Cold drinks delivery in Rajkot"),
        "intro": _(
            "Chilled soft drinks, soda and energy drinks delivered across Rajkot in 30 to 60 minutes. "
            "Cash on Delivery available, free delivery above ₹499."
        ),
        "category": "soft-drinks",
    },
    "juice-home-delivery-rajkot": {
        "title": _("Juice home delivery in Rajkot"),
        "intro": _("Mango ras, kokum, orange and more juices delivered chilled to your door anywhere in Rajkot."),
        "category": "juices",
    },
    "lassi-chaas-delivery-rajkot": {
        "title": _("Lassi & chaas delivery in Rajkot"),
        "intro": _("Fresh lassi, chaas and flavoured milk from trusted brands, delivered in under an hour."),
        "category": "milk-lassi",
    },
    "party-drinks-rajkot": {
        "title": _("Party & wedding drinks supply in Rajkot"),
        "intro": _("Crates and cases for weddings, functions, offices and shops with bulk prices."),
        "category": None,
    },
}
