from . import views
from django.contrib.auth.decorators import login_required
from django.urls import path


app_name = 'licenses'
urlpatterns = [
    path(
        '',
        login_required(views.ListLicensesView.as_view()),
        name='licenses'
    ),
    path(
        'create/',
        login_required(views.CreateLicenseView.as_view()),
        name='create'
    )
]
