"""Dashboard roles.

Staff    : orders, stock, products, reviews, support inbox, party quotes.
Manager  : everything Staff has, plus money (revenue, refunds, analytics), promotions, content and delivery settings.
Owner    : everything, plus integrations (API keys), store settings, staff accounts and the audit log.
"""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

LEVEL = {"staff": 1, "manager": 2, "owner": 3}


def level_of(user) -> int:
    if not user.is_authenticated or not user.is_dashboard_user:
        return 0
    if user.is_owner:
        return 3
    return LEVEL.get(user.role, 0)


def can(user, role: str) -> bool:
    return level_of(user) >= LEVEL[role]


def dash(role="staff"):
    """Require a signed-in dashboard user with at least ``role``."""

    def deco(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path(), "/accounts/login/")
            if not can(request.user, role):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        wrapper.dash_role = role
        return wrapper

    return deco


# Sidebar: (section, [(label, url name, args, role, icon)])
NAV = [
    ("", [("Home", "dashboard:home", (), "staff", "home")]),
    (
        "Sell",
        [
            ("Orders", "dashboard:orders", (), "staff", "bag"),
            ("Quick stock", "dashboard:stock", (), "staff", "box"),
            ("Products", "dashboard:products", (), "staff", "tag"),
            ("Categories", "dashboard:crud_list", ("categories",), "manager", "grid"),
            ("Brands", "dashboard:crud_list", ("brands",), "manager", "star"),
            ("Customers", "dashboard:customers", (), "manager", "user"),
            ("Subscriptions", "dashboard:subscriptions", (), "manager", "repeat"),
            ("Party quotes", "dashboard:bulk_quotes", (), "staff", "truck"),
        ],
    ),
    (
        "Grow",
        [
            ("Hero slider", "dashboard:hero", (), "manager", "image"),
            ("Coupons", "dashboard:crud_list", ("coupons",), "manager", "ticket"),
            ("Campaigns", "dashboard:crud_list", ("campaigns",), "manager", "flag"),
            ("Combos", "dashboard:crud_list", ("combos",), "manager", "gift"),
            ("Bulk prices", "dashboard:crud_list", ("bulk-prices",), "manager", "stack"),
            ("Analytics", "dashboard:analytics", (), "manager", "chart"),
            ("Insights", "dashboard:insights", (), "manager", "bulb"),
            ("Competitor watch", "dashboard:competitors", (), "manager", "eye"),
        ],
    ),
    (
        "Care",
        [
            ("Support inbox", "dashboard:support", (), "staff", "chat"),
            ("Reviews", "dashboard:reviews", (), "staff", "star"),
            ("Thandu guarantee", "dashboard:thandu", (), "manager", "snow"),
            ("Help articles", "dashboard:crud_list", ("faq",), "manager", "help"),
            ("Pages", "dashboard:crud_list", ("pages",), "manager", "file"),
        ],
    ),
    (
        "Settings",
        [
            ("Store", "dashboard:store_settings", (), "owner", "store"),
            ("Delivery", "dashboard:delivery_settings", (), "manager", "map"),
            ("Integrations", "dashboard:integrations", (), "owner", "plug"),
            ("Emails", "dashboard:email_settings", (), "manager", "mail"),
            ("Staff", "dashboard:staff", (), "owner", "users"),
            ("Audit log", "dashboard:audit", (), "owner", "shield"),
        ],
    ),
]
