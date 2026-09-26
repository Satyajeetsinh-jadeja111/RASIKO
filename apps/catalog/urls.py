from django.urls import path

from . import views

app_name = "storefront"

urlpatterns = [
    path("", views.home, name="home"),
    path("c/<slug:slug>/", views.category, name="category"),
    path("brands/", views.brands, name="brands"),
    path("brands/<slug:slug>/", views.brand, name="brand"),
    path("p/<slug:slug>/", views.product, name="product"),
    path("search/", views.search, name="search"),
    path("search/suggest/", views.suggest, name="suggest"),
    path("offers/", views.offers, name="offers"),
    path("pages/<slug:slug>/", views.page, name="page"),
    path("wishlist/", views.wishlist, name="wishlist"),
    path("wishlist/<int:pk>/toggle/", views.wishlist_toggle, name="wishlist_toggle"),
    path("stock-alert/<int:pk>/", views.back_in_stock, name="back_in_stock"),
    path("rajkot/<slug:slug>/", views.local_landing, name="landing"),
]
