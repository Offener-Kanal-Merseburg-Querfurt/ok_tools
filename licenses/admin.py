from .models import Category
from .models import LicenseRequest
from django.contrib import admin


admin.site.register(LicenseRequest)

admin.site.register(Category)
