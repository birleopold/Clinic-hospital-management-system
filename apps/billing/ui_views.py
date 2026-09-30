from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponseForbidden, HttpResponse
from django.db.models import F, ExpressionWrapper, DecimalField
from django.db import transaction
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Invoice, Payment, ClinicConfig, CashSession
from common.exports import pdf_response_from_template, csv_response, xlsx_response
from common.facility_scope import filter_by_patient_facility


def brand_image_context(brand):
    if not brand or not brand.logo:return {}
    import base64
    from PIL import Image
    with brand.logo.open('rb') as image_file:
        kind=Image.open(image_file).format
        image_file.seek(0)
        return {'brand_logo':base64.b64encode(image_file.read()).decode('ascii'),'brand_logo_mime':'image/png' if kind=='PNG' else 'image/jpeg'}


@login_required
def cashier_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','cashier')):
        return HttpResponseForbidden('Not allowed')

    ready_invoices = (
        filter_by_patient_facility(Invoice.objects.all(), user)
        .filter(status=Invoice.READY)
        .filter(**({'patient_id': int(request.GET['patient'])} if request.GET.get('patient','').isdigit() else {}))
        .annotate(balance=ExpressionWrapper(F('total_amount') - F('paid_amount'), output_field=DecimalField(max_digits=12, decimal_places=2)))
        .select_related('patient')
        .order_by('-created_at')
    )

    import uuid
    ready_invoices=list(ready_invoices)
    for invoice in ready_invoices: invoice.payment_key=uuid.uuid4()
    session = CashSession.objects.filter(opened_by=user, close_time__isnull=True).first()
    recent_payments = (
        filter_by_patient_facility(Payment.objects.all(), user, prefix='invoice__patient__')
        .filter(cash_session=session)
        .order_by('-paid_at')[:10]
        if session else []
    )
    context = {
        'invoices': ready_invoices,
        'session': session,
        'recent_payments': recent_payments,
    }
    return render(request, 'cashier/index.html', context)


@login_required
def invoice_print_view(request, invoice_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','cashier')):
        return HttpResponseForbidden('Not allowed')
    invoice = get_object_or_404(
        filter_by_patient_facility(Invoice.objects.all(), user).select_related('patient'),
        pk=invoice_id,
    )
    cfg = ClinicConfig.get_solo()
    from apps.accounts.models import FacilityConfiguration
    brand=FacilityConfiguration.objects.filter(facility_id=invoice.patient.facility_id).first()
    template = 'billing/invoice_a4.html' if (brand.receipt_paper if brand else cfg.receipt_paper) == ClinicConfig.A4 else 'billing/invoice_80mm.html'
    balance = (invoice.total_amount or Decimal('0')) - (invoice.paid_amount or Decimal('0'))
    ctx = {
        'config': cfg,
        'facility_brand':brand,
        **brand_image_context(brand),

        'invoice': invoice,
        'lines': invoice.lines.all(),
        'balance': balance,
    }
    if request.GET.get('format') == 'pdf':
        return pdf_response_from_template(template, ctx, f'invoice_{invoice.id}.pdf')
    return render(request, template, ctx)


@login_required
def receipt_print_view(request, payment_id: int):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','cashier')):
        return HttpResponseForbidden('Not allowed')
    payment = get_object_or_404(
        filter_by_patient_facility(Payment.objects.all(), user, prefix='invoice__patient__').select_related(
            'invoice', 'invoice__patient'
        ),
        pk=payment_id,
    )
    cfg = ClinicConfig.get_solo()
    from apps.accounts.models import FacilityConfiguration
    brand=FacilityConfiguration.objects.filter(facility_id=payment.invoice.patient.facility_id).first()
    template = 'billing/receipt_a4.html' if (brand.receipt_paper if brand else cfg.receipt_paper) == ClinicConfig.A4 else 'billing/receipt_80mm.html'
    ctx = {
        'config': cfg,
        'facility_brand':brand,
        **brand_image_context(brand),

        'payment': payment,
        'invoice': payment.invoice,
        'lines': payment.invoice.lines.all(),
    }
    if request.GET.get('format') == 'pdf':
        return pdf_response_from_template(template, ctx, f'receipt_{payment.id}.pdf')
    return render(request, template, ctx)


@login_required
@transaction.atomic
def cash_session_open_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','cashier')):
        return HttpResponseForbidden('Not allowed')
    if request.method != 'POST':
        return HttpResponseForbidden('Invalid method')
    get_user_model().objects.select_for_update().get(pk=user.pk)
    if CashSession.objects.filter(opened_by=user, close_time__isnull=True).exists():
        return redirect('cashier')
    try:
        opening_float = Decimal(request.POST.get('opening_float') or '0')
    except Exception:
        opening_float = Decimal('0')
    if not opening_float.is_finite() or opening_float < 0 or opening_float > Decimal('9999999999.99'):
        return HttpResponse('Invalid opening float', status=400)
    CashSession.objects.create(opened_by=user, opening_float=opening_float, expected_cash=opening_float)
    return redirect('cashier')


@login_required
@transaction.atomic
def cash_session_close_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','cashier')):
        return HttpResponseForbidden('Not allowed')
    if request.method != 'POST':
        return HttpResponseForbidden('Invalid method')
    get_user_model().objects.select_for_update().get(pk=user.pk)
    session = CashSession.objects.select_for_update().filter(opened_by=user, close_time__isnull=True).first()
    if not session:
        return redirect('cashier')
    try:
        counted_cash = Decimal(request.POST.get('counted_cash') or '0')
    except Exception:
        counted_cash = Decimal('0')
    if not counted_cash.is_finite() or counted_cash < 0 or counted_cash > Decimal('9999999999.99'):
        return HttpResponse('Invalid counted cash', status=400)
    notes = request.POST.get('notes','')
    session.counted_cash = counted_cash
    session.discrepancy = (counted_cash or Decimal('0')) - (session.expected_cash or Decimal('0'))
    if session.discrepancy and not notes.strip():
        return HttpResponse('Explain the cash discrepancy before closing the shift.', status=400)
    session.close_time = timezone.now()
    session.notes = notes
    session.save(update_fields=['counted_cash','discrepancy','close_time','notes'])
    return redirect('cashier')


@login_required
def cash_session_report_view(request, session_id: int = None):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','cashier')):
        return HttpResponseForbidden('Not allowed')
    if session_id:
        sessions = CashSession.objects.all()
        if not user.is_superuser:
            sessions = sessions.filter(opened_by=user)
        session = get_object_or_404(sessions, pk=session_id)
    else:
        session = CashSession.objects.filter(opened_by=user).order_by('-open_time').first()
        if not session:
            return redirect('cashier')

    payments = (
        filter_by_patient_facility(Payment.objects.all(), user, prefix='invoice__patient__')
        .filter(cash_session=session)
        .select_related('invoice', 'invoice__patient')
        .order_by('paid_at')
    )
    rows = [
        {
            'id': p.id,
            'time': p.paid_at.strftime('%Y-%m-%d %H:%M'),
            'invoice': p.invoice_id,
            'patient': str(p.invoice.patient),
            'amount': f"{p.amount}",
        }
        for p in payments
    ]
    headers = ['id', 'time', 'invoice', 'patient', 'amount']

    exp = request.GET.get('export')
    if exp == 'csv':
        return csv_response(f'session_{session.id}_report.csv', headers, rows)
    if exp == 'xlsx':
        return xlsx_response(f'session_{session.id}_report.xlsx', headers, rows)

    totals = sum((p.amount for p in payments), start=Decimal('0'))
    context = {
        'session': session,
        'payments': payments,
        'total_amount': totals,
    }
    if request.GET.get('format') == 'pdf':
        return pdf_response_from_template('cashier/session_report.html', context, f'session_{session.id}_report.pdf')
    return render(request, 'cashier/session_report.html', context)


@login_required
def cashbook_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','cashier')):
        return HttpResponseForbidden('Not allowed')
    start = request.GET.get('start')
    end = request.GET.get('end')
    qs = filter_by_patient_facility(Payment.objects.all(), user, prefix='invoice__patient__').select_related(
        'invoice', 'invoice__patient'
    ).order_by('-paid_at')
    from django.utils.dateparse import parse_datetime, parse_date
    from datetime import datetime, time
    sdt = edt = None
    if start:
        d = parse_date(start)
        if d:
            sdt = timezone.make_aware(datetime.combine(d, time.min))
            qs = qs.filter(paid_at__gte=sdt)
    if end:
        d = parse_date(end)
        if d:
            edt = timezone.make_aware(datetime.combine(d, time.max))
            qs = qs.filter(paid_at__lte=edt)

    rows = [
        {
            'id': p.id,
            'time': p.paid_at.strftime('%Y-%m-%d %H:%M'),
            'invoice': p.invoice_id,
            'patient': str(p.invoice.patient),
            'amount': f"{p.amount}",
            'cashier': str(p.cash_session.opened_by) if p.cash_session_id else '',
            'session': p.cash_session_id or '',
        }
        for p in qs
    ]
    headers = ['id', 'time', 'invoice', 'patient', 'amount', 'cashier', 'session']
    exp = request.GET.get('export')
    if exp == 'csv':
        return csv_response('cashbook.csv', headers, rows)
    if exp == 'xlsx':
        return xlsx_response('cashbook.xlsx', headers, rows)

    total_amount = sum((p.amount for p in qs), start=Decimal('0'))
    context = {
        'payments': qs[:200],
        'total_amount': total_amount,
        'start': start or '',
        'end': end or '',
    }
    return render(request, 'cashier/cashbook.html', context)


@login_required
def settings_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','manager')):
        return HttpResponseForbidden('Not allowed')
    cfg = ClinicConfig.get_solo()
    if request.method == 'POST':
        # Update near_expiry_days only (simple settings)
        try:
            ned = int(request.POST.get('near_expiry_days') or cfg.near_expiry_days or 30)
        except Exception:
            ned = cfg.near_expiry_days or 30
        if ned < 1:
            ned = 1
        if ned > 3650:
            ned = 3650
        if cfg.near_expiry_days != ned:
            cfg.near_expiry_days = ned
            cfg.save(update_fields=['near_expiry_days'])
        if request.headers.get('HX-Request'):
            return HttpResponse(status=204)
        return redirect('billing-settings')
    return render(request, 'billing/settings.html', { 'config': cfg })
