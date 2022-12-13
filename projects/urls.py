from . import views
from django.urls import path


app_name = 'projects'
urlpatterns = [
    path(
        '',
        views.FindView.as_view(),
        name="find",
    ),
    path(
        '<uuid:id>/',
        views.SignInView.as_view(),
        name="sign-in",
    ),
    path(
        'qr/<uuid:id>/',
        views.QRCode.as_view(),
        name="qr",
    )
]
