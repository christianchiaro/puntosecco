from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("chi-siamo/", views.about, name="about"),
    path("orario/", views.orario, name="orario"),
]
