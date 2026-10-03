from django.urls import path

from . import views

app_name = "reviews"
urlpatterns = [path("write/<int:line_id>/", views.write, name="write")]
