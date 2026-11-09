from django.urls import path

from . import api

urlpatterns = [
    path("rider/login/", api.Login.as_view()),
    path("rider/register/", api.Register.as_view()),
    path("rider/logout/", api.Logout.as_view()),
    path("rider/heartbeat/", api.Heartbeat.as_view()),
    path("rider/device/", api.Device.as_view()),
    path("rider/offers/", api.Offers.as_view()),
    path("rider/offers/<int:pk>/accept/", api.Accept.as_view()),
    path("rider/offers/<int:pk>/decline/", api.Decline.as_view()),
    path("rider/deliveries/", api.Deliveries.as_view()),
    path("rider/deliveries/<int:pk>/<str:action>/", api.Action.as_view()),
]
