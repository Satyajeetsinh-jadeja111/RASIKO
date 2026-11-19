from django.urls import path

from . import extended_views as extra
from . import shops, views

app_name = "marketplace"
urlpatterns = [
    path("shops/<int:pk>/", shops.workspace, name="shop"),
    path("shops/<int:pk>/brands/", shops.request_brand, name="shop_brand"),
    path("products/<int:pk>/photo/", extra.product_photo, name="product_photo"),
    path("onboarding/<int:pk>/recover/", extra.recover_onboarding, name="recover_onboarding"),
    path("onboarding/<int:pk>/resume/", extra.resume_onboarding, name="resume_onboarding"),
    path("business/<int:pk>/", extra.business, name="business"),
    path("onboarding/<int:pk>/", extra.onboard, name="onboard"),
    path("onboarding/<int:pk>/refresh/", extra.refresh_onboarding, name="refresh_onboarding"),
    path("batches/<int:pk>/", extra.batch_receive, name="batch_receive"),
    path("operations/<str:action>/<int:pk>/", extra.operate, name="operate"),
    path("operations-settings/", extra.operations_settings, name="operations_settings"),
    path("alerts/", extra.alerts, name="alerts"),
    path("cases/", extra.cases, name="cases"),
    path("cases/new/<int:pk>/", extra.case_create, name="case_create"),
    path("cases/<int:pk>/", extra.case_detail, name="case"),
    path("invoices/<int:pk>/", extra.invoice, name="invoice"),
    path("invoices/<int:pk>/issue/", extra.issue_invoice, name="issue_invoice"),
    path("policies/", extra.policies, name="policies"),
    path("apply/", views.apply_seller, name="apply"),
    path("products/import/", views.import_catalog, name="import_catalog"),
    path("products/<int:pk>/translations/<str:language>/", views.translation_edit, name="translation"),
    path("products/", views.products, name="products"),
    path("products/new/", views.product_edit, name="product_add"),
    path("products/<int:pk>/", views.product_edit, name="product_edit"),
    path("products/<int:product_id>/variants/new/", views.variant_edit, name="variant_add"),
    path("products/<int:product_id>/variants/<int:pk>/", views.variant_edit, name="variant_edit"),
    path("stock/<int:pk>/", views.adjust_stock, name="stock"),
    path("sellers/<int:pk>/verify/", views.verify_seller, name="verify_seller"),
    path("", views.dashboard, name="dashboard"),
    path("setup/<str:kind>/", views.setup, name="setup"),
    path("action/<str:kind>/<int:pk>/", views.action, name="action"),
    path("export/", views.export, name="export"),
]
