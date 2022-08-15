from . import views
from django.urls import path


app_name = 'licenses'
urlpatterns = [
    path(
        '',
        views.ListLicensesView.as_view(),
        name='licenses',
    ),
    path(
        'create/',
        views.CreateLicenseView.as_view(),
        name='create',
    ),
    path(
        '<int:pk>/',
        views.DetailsLicensesView.as_view(),
        name='details',
    )
]
