from django.conf import settings
from django.contrib import messages
from django.core.mail import send_mail
from django.http import HttpResponse
from django.shortcuts import redirect
from django.shortcuts import render


def accessibility_statement(request):
    """Seite für die Barrierefreiheitserklärung."""
    return render(request, 'accessibility_statement.html')


def accessibility_feedback(request):
    """Seite für Barrierefreiheits-Feedback."""
    if request.method == 'POST':
        # Verarbeitung des Feedback-Formulars
        name = request.POST.get('name', '')
        email = request.POST.get('email', '')
        url = request.POST.get('url', '')
        barrier_type = request.POST.get('barrier_type', '')
        description = request.POST.get('description', '')
        assistive_tech = request.POST.get('assistive_tech', '')

        # Validierung
        if not url or not barrier_type or not description:
            messages.error(request, 'Bitte füllen Sie alle Pflichtfelder aus.')
            return render(request, 'accessibility_feedback.html')

        # E-Mail senden
        subject = f'Barriere gemeldet: {barrier_type}'
        message = f"""
        Name: {name}
        E-Mail: {email}
        Betroffene Seite: {url}
        Art der Barriere: {barrier_type}
        Hilfstechnologie: {assistive_tech}

        Beschreibung:
        {description}
        """

        try:
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                ['accessibility@example.com'],
                fail_silently=False,
            )
            messages.success(request, 'Vielen Dank für Ihre Nachricht. Wir werden uns innerhalb von 2 Wochen bei Ihnen melden.')
            return redirect('accessibility_feedback')
        except Exception as e:
            messages.error(request, 'Es gab einen Fehler beim Senden Ihrer Nachricht. Bitte versuchen Sie es später erneut.')

    return render(request, 'accessibility_feedback.html')
