from datetime import datetime, timedelta
from decimal import Decimal
from django.db.models import Sum, F
from django.utils.timezone import make_aware
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from common.exports import csv_response, xlsx_response
from common.permissions import RolePermission

from apps.billing.models import Payment, InvoiceLine, Invoice
from apps.demographics.models import Patient


def _range_from_request(request):
    date_str = request.query_params.get('date')
    start_str = request.query_params.get('start')
    end_str = request.query_params.get('end')
    if date_str:
        d = datetime.strptime(date_str, '%Y-%m-%d')
        start = make_aware(datetime(d.year, d.month, d.day, 0, 0, 0))
        end = make_aware(datetime(d.year, d.month, d.day, 23, 59, 59))
        return start, end
    if start_str and end_str:
        s = datetime.strptime(start_str, '%Y-%m-%d')
        e = datetime.strptime(end_str, '%Y-%m-%d')
        start = make_aware(datetime(s.year, s.month, s.day, 0, 0, 0))
        end = make_aware(datetime(e.year, e.month, e.day, 23, 59, 59))
        return start, end
    # default today
    today = datetime.now()
    start = make_aware(datetime(today.year, today.month, today.day, 0, 0, 0))
    end = make_aware(datetime(today.year, today.month, today.day, 23, 59, 59))
    return start, end


class DailyRevenueView(APIView):
    permission_classes = [RolePermission]
    role_map = {
        'GET': ['admin','manager','cashier']
    }
    def get(self, request):
        start, end = _range_from_request(request)
        total = Payment.objects.filter(paid_at__range=(start, end)).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        export = request.query_params.get('export')
        payload = {'start': start.isoformat(), 'end': end.isoformat(), 'total_revenue': str(total)}
        if export == 'csv':
            headers = ['start','end','total_revenue']
            rows = [payload]
            return csv_response('daily_revenue.csv', headers, rows)
        if export in ('xls','xlsx'):
            headers = ['start','end','total_revenue']
            rows = [payload]
            return xlsx_response('daily_revenue.xlsx', headers, rows)
        return Response(payload)

class PatientVolumesView(APIView):
    permission_classes = [RolePermission]
    role_map = {
        'GET': ['admin','manager']
    }
    def get(self, request):
        start, end = _range_from_request(request)
        total = Patient.objects.filter(created_at__range=(start, end)).count()
        export = request.query_params.get('export')
        payload = {'start': start.isoformat(), 'end': end.isoformat(), 'new_patients': total}
        if export == 'csv':
            headers = ['start','end','new_patients']
            rows = [payload]
            return csv_response('patient_volumes.csv', headers, rows)
        if export in ('xls','xlsx'):
            headers = ['start','end','new_patients']
            rows = [payload]
            return xlsx_response('patient_volumes.xlsx', headers, rows)
        return Response(payload)

class ServiceMixView(APIView):
    permission_classes = [RolePermission]
    role_map = {
        'GET': ['admin','manager','cashier']
    }
    def get(self, request):
        start, end = _range_from_request(request)
        qs = InvoiceLine.objects.filter(created_at__range=(start, end)).values('code').annotate(
            total_amount=Sum('line_total'),
            total_qty=Sum('quantity'),
        ).order_by('-total_amount')
        rows = [
            {
                'code': r['code'],
                'total_amount': str(r['total_amount'] or Decimal('0.00')),
                'total_qty': str(r['total_qty'] or Decimal('0.00')),
            }
            for r in qs
        ]
        export = request.query_params.get('export')
        if export == 'csv':
            headers = ['code','total_amount','total_qty']
            return csv_response('service_mix.csv', headers, rows)
        if export in ('xls','xlsx'):
            headers = ['code','total_amount','total_qty']
            return xlsx_response('service_mix.xlsx', headers, rows)
        return Response({'start': start.isoformat(), 'end': end.isoformat(), 'service_mix': rows})


class RawInvoicesView(APIView):
    permission_classes = [RolePermission]
    role_map = {
        'GET': ['admin','manager','cashier']
    }

    def get(self, request):
        start, end = _range_from_request(request)
        status_filter = request.query_params.get('status')
        qs = Invoice.objects.filter(created_at__range=(start, end)).select_related('patient').order_by('-id')
        if status_filter:
            qs = qs.filter(status=status_filter)
        rows = [
            {
                'id': inv.id,
                'patient_id': inv.patient_id,
                'patient': str(inv.patient),
                'total_amount': str(inv.total_amount or Decimal('0.00')),
                'paid_amount': str(inv.paid_amount or Decimal('0.00')),
                'status': inv.status,
                'created_at': inv.created_at.isoformat(),
            }
            for inv in qs
        ]
        export = request.query_params.get('export')
        headers = ['id','patient_id','patient','total_amount','paid_amount','status','created_at']
        if export == 'csv':
            return csv_response('raw_invoices.csv', headers, rows)
        if export in ('xls','xlsx'):
            return xlsx_response('raw_invoices.xlsx', headers, rows)
        return Response({'start': start.isoformat(), 'end': end.isoformat(), 'count': len(rows), 'rows': rows})


class RawPaymentsView(APIView):
    permission_classes = [RolePermission]
    role_map = {
        'GET': ['admin','manager','cashier']
    }

    def get(self, request):
        start, end = _range_from_request(request)
        qs = Payment.objects.filter(paid_at__range=(start, end)).select_related('invoice__patient').order_by('-paid_at')
        rows = [
            {
                'id': p.id,
                'invoice_id': p.invoice_id,
                'patient_id': getattr(p.invoice, 'patient_id', None),
                'patient': str(getattr(p.invoice, 'patient', '')),
                'amount': str(p.amount or Decimal('0.00')),
                'method': p.method,
                'paid_at': p.paid_at.isoformat(),
            }
            for p in qs
        ]
        export = request.query_params.get('export')
        headers = ['id','invoice_id','patient_id','patient','amount','method','paid_at']
        if export == 'csv':
            return csv_response('raw_payments.csv', headers, rows)
        if export in ('xls','xlsx'):
            return xlsx_response('raw_payments.xlsx', headers, rows)
        return Response({'start': start.isoformat(), 'end': end.isoformat(), 'count': len(rows), 'rows': rows})
