from django.urls import path

from . import crud
from .permissions import dash
from .views import analytics, catalog, home, orders, people, settings

app_name = "dashboard"


def _crud(view):
    """Generic editors check their own role per table; this only requires a dashboard user."""
    return dash("staff")(view)


urlpatterns = [
    path("", home.home, name="home"),
    # Orders
    path("orders/", orders.order_list, name="orders"),
    path("orders/<str:number>/", orders.order_detail, name="order"),
    path("orders/<str:number>/status/", orders.order_status, name="order_status"),
    path("orders/<str:number>/note/", orders.order_note, name="order_note"),
    path("orders/<str:number>/refund/", orders.order_refund, name="order_refund"),
    path("orders/<str:number>/invoice/", orders.order_invoice, name="order_invoice"),
    path("orders/<str:number>/packing-slip/", orders.packing_slip, name="packing_slip"),
    path("party-quotes/", orders.bulk_quotes, name="bulk_quotes"),
    path("subscriptions/", orders.subscriptions, name="subscriptions"),
    path("thandu/", orders.thandu, name="thandu"),
    # Catalogue and stock
    path("products/", catalog.product_list, name="products"),
    path("products/new/", catalog.product_edit, name="product_new"),
    path("products/export/", catalog.products_export, name="products_export"),
    path("products/import/", catalog.products_import, name="products_import"),
    path("products/<int:pk>/", catalog.product_edit, name="product_edit"),
    path("stock/", catalog.stock, name="stock"),
    path("stock/<int:pk>/", catalog.stock_update, name="stock_update"),
    path("stock/history/", catalog.movements, name="movements"),
    path("slider/", catalog.hero, name="hero"),
    path("slider/new/", catalog.hero_edit, name="hero_new"),
    path("slider/<int:pk>/", catalog.hero_edit, name="hero_edit"),
    path("slider/<int:pk>/delete/", catalog.hero_delete, name="hero_delete"),
    # People
    path("customers/", people.customers, name="customers"),
    path("customers/<int:pk>/", people.customer, name="customer"),
    path("reviews/", people.reviews, name="reviews"),
    path("support/", people.support, name="support"),
    path("support/<uuid:public_id>/", people.support_ticket, name="support_ticket"),
    path("competitors/", people.competitors, name="competitors"),
    # Analytics
    path("analytics/", analytics.analytics, name="analytics"),
    path("analytics/delivery/", analytics.delivery_economics, name="delivery_economics"),
    path("insights/", analytics.insights, name="insights"),
    path("insights/refresh/", analytics.insights_refresh, name="insights_refresh"),
    # Settings
    path("settings/store/", settings.store_settings, name="store_settings"),
    path("settings/delivery/", settings.delivery_settings, name="delivery_settings"),
    path("settings/integrations/", settings.integrations, name="integrations"),
    path("settings/integrations/<slug:slug>/", settings.integration_save, name="integration_save"),
    path("settings/emails/", settings.email_settings, name="email_settings"),
    path("settings/staff/", settings.staff, name="staff"),
    path("settings/audit/", settings.audit_log, name="audit"),
    # Simple tables
    path("c/<slug:slug>/", _crud(crud.crud_list), name="crud_list"),
    path("c/<slug:slug>/new/", _crud(crud.crud_edit), name="crud_new"),
    path("c/<slug:slug>/<int:pk>/", _crud(crud.crud_edit), name="crud_edit"),
    path("c/<slug:slug>/<int:pk>/delete/", _crud(crud.crud_delete), name="crud_delete"),
]
