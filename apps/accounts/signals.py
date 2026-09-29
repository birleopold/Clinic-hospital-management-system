from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver


@receiver(user_logged_in)
def set_session_expiry_on_login(sender, request, user, **kwargs):
    try:
        remember_val = (request.POST.get('remember') or '').strip().lower()
        remember = remember_val in ('1', 'true', 'on', 'yes')
    except Exception:
        remember = False

    if remember:
        # Use a 30-day persistent session by default, overrideable via REMEMBER_ME_AGE
        age = getattr(settings, 'REMEMBER_ME_AGE', 60 * 60 * 24 * 30)
        request.session.set_expiry(age)
    else:
        # Expire when the browser closes
        request.session.set_expiry(0)
