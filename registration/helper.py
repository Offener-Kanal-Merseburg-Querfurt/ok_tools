from django.urls import reverse_lazy
from django.utils.html import format_html


def toc_href():
    """Avoid circular import of urls and ProfileForm."""
    return format_html(
        '<a href="{}" target="_blank">{}</a>',
        reverse_lazy('toc'),
        'Terms of Condition'
    )
