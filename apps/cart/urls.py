from django.urls import path

from . import views

app_name = "cart"

urlpatterns = [
    path("", views.detail, name="detail"),
    path("drawer/", views.drawer, name="drawer"),
    path("update/", views.update, name="update"),
    path("coupon/", views.apply_coupon, name="coupon"),
    path("coins/", views.toggle_coins, name="coins"),
]
