from django.urls import path

from . import views

app_name = "support"
urlpatterns = [
    path("", views.help_center, name="help"),
    path("chat/poll/", views.chat_poll, name="chat_poll"),
    path("chat/send/", views.chat_send, name="chat_send"),
    path("chat/handoff/", views.chat_handoff, name="chat_handoff"),
    path("chat/verify/", views.chat_verify_order, name="chat_verify"),
    path("tickets/", views.my_tickets, name="tickets"),
    path("tickets/<uuid:public_id>/", views.ticket_detail, name="ticket"),
]
