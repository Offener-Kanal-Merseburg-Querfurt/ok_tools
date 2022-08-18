"""ok_tools URL Configuration.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include
from django.urls import path
from django.views.generic.base import TemplateView
from registration.views import PasswordResetConfirmView
from registration.views import PasswordResetView


urlpatterns = [
    path('', TemplateView.as_view(template_name='home.html'), name='home'),
    path(
        "profile/reset/<uidb64>/<token>/",
        PasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        'profile/password_reset/',
        PasswordResetView.as_view(),
        name='password_reset'
    ),
    # This includes upstream passsword reset, login/out views.
    path('profile/', include('django.contrib.auth.urls')),
    path('admin/', admin.site.urls),
    path('licenses/', include('licenses.urls')),
    path('profile/', include('registration.urls')),
    path(
        'privacy_policy/',
        TemplateView.as_view(template_name='privacy_policy.html'),
        name='privacy_policy'
    ),
]
