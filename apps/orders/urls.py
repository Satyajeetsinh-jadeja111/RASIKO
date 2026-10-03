from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("checkout/", views.checkout, name="checkout"),
    path("checkout/quote/", views.delivery_quote, name="quote"),
    path("track/", views.track_order, name="track"),
    path("party/", views.bulk_quote, name="bulk"),
    path("subscriptions/", views.subscriptions, name="subscriptions"),
    path("subscriptions/<uuid:public_id>/", views.subscription_action, name="subscription_action"),
    path("<uuid:public_id>/", views.detail, name="detail"),
    path("<uuid:public_id>/thank-you/", views.success, name="success"),
    path("<uuid:public_id>/invoice/", views.invoice, name="invoice"),
    path("<uuid:public_id>/cancel/", views.cancel, name="cancel"),
    path("<uuid:public_id>/reorder/", views.reorder, name="reorder"),
    path("<uuid:public_id>/thandu/", views.thandu, name="thandu"),
]
