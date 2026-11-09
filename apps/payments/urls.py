from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("pay/<uuid:public_id>/create-order/", views.create_order, name="create_order"),
    path("pay/<uuid:public_id>/verify-payment/", views.verify_payment, name="verify_payment"),
    path("pay/<uuid:public_id>/", views.pay, name="pay"),
    path("pay/<uuid:public_id>/razorpay/", views.razorpay_return, name="razorpay_return"),
    path("pay/<uuid:public_id>/stripe/", views.stripe_return, name="stripe_return"),
    path("pay/<uuid:public_id>/cancel/", views.cancel_payment, name="cancel"),
    path("webhooks/<str:gateway>/", views.webhook, name="webhook"),
]
