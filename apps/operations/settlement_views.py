import uuid
from decimal import Decimal
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from common.exports import csv_response
from common.facility_scope import filter_by_facility, filter_by_patient_facility
from .models import OperatingExpense, ExpenseSettlement, Refund
from apps.billing.models import Payment
from .workforce_services import manager
from . import settlement_services as services


def expenses(user):
    manager(user)
    return filter_by_facility(OperatingExpense.objects.select_related('budget'), user, 'budget__facility_id')


def settlements(user):
    manager(user)
    return filter_by_facility(ExpenseSettlement.objects.select_related('expense__budget', 'created_by', 'reconciled_by'), user, 'expense__budget__facility_id')


@login_required
def detail(request, pk):
    obj = get_object_or_404(expenses(request.user), pk=pk)
    class Form(forms.ModelForm):
        class Meta:
            model = ExpenseSettlement
            fields = ['amount', 'paid_on', 'method', 'account_reference', 'transaction_reference', 'evidence', 'request_key']
            widgets = {'paid_on': forms.DateInput(attrs={'type':'date'}), 'request_key': forms.HiddenInput(), 'evidence':forms.Textarea(attrs={'rows':4})}
        def validate_unique(self):
            # The service handles exact replays and conflicting payloads under
            # the facility lock; normal ModelForm uniqueness rejects a retry.
            exclude = self._get_validation_exclusions()
            exclude.add('request_key')
            try: self.instance.validate_unique(exclude=exclude)
            except ValidationError as exc: self._update_errors(exc)
    used = obj.settlements.exclude(status='rejected').aggregate(total=Sum('amount'))['total'] or Decimal('0')
    form = Form(request.POST or None, initial={'amount':obj.amount-used, 'paid_on':timezone.localdate(), 'request_key':uuid.uuid4()})
    if request.method == 'POST' and form.is_valid():
        try: services.record_settlement(request.user, obj.pk, **form.cleaned_data)
        except ValidationError as exc: form.add_error(None, '; '.join(exc.messages))
        else:
            messages.success(request, 'Disbursement evidence recorded; another supervisor must reconcile it.')
            return redirect('suite-expense-detail', pk=pk)
    rows = obj.settlements.select_related('created_by', 'reconciled_by').order_by('-pk')
    for row in rows: row.can_reconcile = row.status=='pending' and row.created_by_id!=request.user.pk
    return render(request, 'operations/expense_detail.html', {'expense':obj, 'settlements':rows, 'form':form, 'outstanding':obj.amount-used, 'can_record':obj.status=='approved' and used<obj.amount})


@login_required
def review(request, pk):
    get_object_or_404(settlements(request.user), pk=pk)
    if request.method != 'POST': return HttpResponse('Use POST.', status=405)
    try: obj = services.reconcile(request.user, pk, request.POST.get('decision'), request.POST.get('reason','')[:250])
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
        obj = settlements(request.user).get(pk=pk)
    return redirect('suite-expense-detail', pk=obj.expense_id)


@login_required
def report(request):
    manager(request.user)
    class Dates(forms.Form):
        start = forms.DateField(widget=forms.DateInput(attrs={'type':'date'}))
        end = forms.DateField(widget=forms.DateInput(attrs={'type':'date'}))
        source = forms.ChoiceField(required=False, initial='expenses', choices=[('expenses','Expense settlements'),('collections','Patient collections'),('refunds','Disbursed patient refunds')], label='Source records')
        def clean(self):
            data=super().clean()
            if data.get('start') and data.get('end') and data['end']<data['start']:raise forms.ValidationError('End date must be on or after start date.')
            return data
    today=timezone.localdate()
    form=Dates(request.GET or {'start':today.replace(day=1), 'end':today})
    incoming=Payment.objects.none(); outgoing=ExpenseSettlement.objects.none(); refunds=Refund.objects.none()
    if form.is_valid():
        dates={'gte':form.cleaned_data['start'], 'lte':form.cleaned_data['end']}
        incoming=filter_by_patient_facility(Payment.objects.all(),request.user,'invoice__patient__').filter(**{'paid_at__date__'+k:v for k,v in dates.items()})
        outgoing=settlements(request.user).filter(status='confirmed',**{'paid_on__'+k:v for k,v in dates.items()})
        refunds=filter_by_patient_facility(Refund.objects.all(),request.user,'payment__invoice__patient__').filter(status='approved',**{'approved_at__date__'+k:v for k,v in dates.items()})
    def total(qs):return qs.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    collected, paid, returned=total(incoming),total(outgoing),total(refunds)
    source=form.cleaned_data.get('source') or 'expenses' if form.is_valid() else 'expenses'
    source_rows={'expenses':outgoing.order_by('-paid_on','-pk'),
        'collections':incoming.select_related('invoice').order_by('-paid_at','-pk'),
        'refunds':refunds.select_related('payment__invoice').order_by('-approved_at','-pk')}[source]
    page=Paginator(source_rows,25).get_page(request.GET.get('page'))
    if request.GET.get('export')=='csv' and form.is_valid():
        rows=[{'id':row.pk,'expense':row.expense_id,'payee':row.expense.payee,'paid_on':row.paid_on,'method':row.method,'account':row.account_reference,'transaction':row.transaction_reference,'amount':row.amount,'reconciled_by':row.reconciled_by_id} for row in outgoing.order_by('pk')]
        return csv_response('reconciled_expenses.csv',['id','expense','payee','paid_on','method','account','transaction','amount','reconciled_by'],rows)
    query=request.GET.copy();query.pop('page',None);query.pop('export',None)
    return render(request,'operations/expense_report.html',{'form':form,'page':page,'source':source,'pagination_query':query.urlencode(),'collected':collected,'settled':paid,'refunds':returned,'net':collected-returned-paid,'pending':settlements(request.user).filter(status='pending').count()})
