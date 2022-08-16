from . import views
from django.urls import path
from django.views.generic.base import TemplateView


app_name = 'registration'
urlpatterns = [
    path('register/', views.RegisterView.as_view(), name='register'),
    path(
        'created/',
        TemplateView.as_view(template_name='registration/user_created.html'),
        name='user_created'),
    path(
        'application/',
        views.PrintRegistrationView.as_view(),
        name='print_registration'
    ),
    path(
        'application/file',
        views.RegistrationFilledFormFile.as_view(),
        name='registration_filled_file'
    ),
    path(
        'application/plain_file',
        views.RegistrationPlainFormFile.as_view(),
        name='registration_plain_file'
    ),
    path(
        'edit/',
        views.EditProfileView.as_view(),
        name='user_data'
    ),

]
