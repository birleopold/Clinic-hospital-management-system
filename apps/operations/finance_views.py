import uuid
from datetime import timedelta
from decimal import Decimal
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q, F, Sum, DecimalField, ExpressionWrapper, Exists, OuterRef
from django.db import transaction, IntegrityError
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from apps.accounts.models import Facility
from apps.billing.models import Invoice, CashSession, Payment
from apps.billing.payment_services import collect_cash
from apps.pharmacy.models import Dispense, BasketLine, DispensingBasket
from apps.inventory.models import InventoryItem, Batch, StockMovement
from common.facility_scope import filter_by_facility, filter_by_patient_facility, user_staff_facility_id
from .models import MedicineReturn, Refund, PriceOverride, ReplenishmentRule, StockLocation
from . import finance_services as services
from .finance_reports import invoice_reconciliation, session_reconciliation, dispense_reconciliation, replenishment_rows


def return_scope(user):return filter_by_patient_facility(MedicineReturn.objects.all(),user,prefix='dispense__patient__')
def price_scope(user):return filter_by_patient_facility(PriceOverride.objects.all(),user,prefix='line__basket__patient__')
def refund_scope(user):return filter_by_patient_facility(Refund.objects.all(),user,prefix='payment__invoice__patient__')


class DecisionForm(forms.Form):
    decision=forms.ChoiceField(choices=[('approve','Approve'),('reject','Reject')])
    reason=forms.CharField(max_length=250,widget=forms.Textarea(attrs={'rows':2}))


@login_required
def finance(request):
    services.role(request.user,('admin','manager','cashier'))
    invoices=filter_by_patient_facility(Invoice.objects.exclude(status=Invoice.CANCELLED),request.user).select_related('patient').annotate(balance=ExpressionWrapper(F('total_amount')-F('paid_amount'),output_field=DecimalField(max_digits=12,decimal_places=2)))
    mode=request.GET.get('mode','outstanding')
    if mode=='outstanding':invoices=invoices.filter(balance__gt=0)
    elif mode=='overpaid':invoices=invoices.filter(balance__lt=0)
    elif mode!='all':mode='outstanding';invoices=invoices.filter(balance__gt=0)
    aging=[];today=timezone.localdate()
    for title,low,high in [('0–30 days',0,30),('31–60 days',31,60),('61–90 days',61,90),('Over 90 days',91,None)]:
        qs=invoices.filter(balance__gt=0,created_at__date__lte=today-timedelta(days=low))
        if high is not None:qs=qs.filter(created_at__date__gte=today-timedelta(days=high))
        aging.append((title,qs.aggregate(s=Sum('balance'))['s'] or 0))
    page=Paginator(invoices.order_by('created_at','pk'),25).get_page(request.GET.get('page'))
    for invoice in page:invoice.reconciliation=invoice_reconciliation(invoice)
    refunds=refund_scope(request.user).filter(status='requested').select_related('payment__invoice__patient','authorization').order_by('created_at')[:25]
    sessions=CashSession.objects.all()
    if not request.user.is_superuser:
        fid=user_staff_facility_id(request.user)
        if not fid:sessions=sessions.none()
        else:
            outside=Payment.objects.filter(cash_session_id=OuterRef('pk')).exclude(invoice__patient__facility_id=fid)
            outside_refund=Refund.objects.filter(cash_session_id=OuterRef('pk')).exclude(payment__invoice__patient__facility_id=fid)
            sessions=sessions.filter(opened_by__staff_profile__facility_id=fid).annotate(outside=Exists(outside),outside_refund=Exists(outside_refund)).filter(outside=False,outside_refund=False)
        if request.user.role=='cashier':sessions=sessions.filter(opened_by=request.user)
    sessions=list(sessions.order_by('-open_time')[:20])
    for session in sessions:session.reconciliation=session_reconciliation(session)
    return render(request,'operations/finance.html',{'page':page,'aging':aging,'mode':mode,'refunds':refunds,'sessions':sessions})


@login_required
def invoice_detail(request,pk):
    services.role(request.user,('admin','manager','cashier'))
    invoice=get_object_or_404(filter_by_patient_facility(Invoice.objects.all(),request.user).select_related('patient'),pk=pk)
    class PaymentForm(forms.Form):
        amount=forms.DecimalField(min_value=Decimal('.01'),max_digits=12,decimal_places=2)
        idempotency_key=forms.UUIDField(widget=forms.HiddenInput(),initial=uuid.uuid4)
        notes=forms.CharField(required=False,max_length=1000)
    form=PaymentForm(request.POST or None,initial={'amount':max(Decimal('0'),invoice.total_amount-invoice.paid_amount)})
    if request.method=='POST' and form.is_valid():
        try:payment,created=collect_cash(pk,request.user,form.cleaned_data['amount'],form.cleaned_data['idempotency_key'],form.cleaned_data['notes'])
        except (ValidationError,IntegrityError) as exc:form.add_error(None,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'Payment key conflict. Review recorded payments before retrying.')
        else:
            messages.success(request,'Payment recorded.' if created else 'Existing payment returned; no duplicate collection.')
            return redirect('receipt-print',payment_id=payment.pk)
    basket=DispensingBasket.objects.filter(invoice=invoice).first()
    return render(request,'operations/invoice_detail.html',{'invoice':invoice,'patient':invoice.patient,'form':form,'basket':basket,'reconciliation':invoice_reconciliation(invoice),'payments':invoice.payments.select_related('cash_session').order_by('pk'),'refunds':refund_scope(request.user).filter(payment__invoice=invoice).select_related('payment'),'lines':invoice.lines.order_by('pk')})


@login_required
def returns(request):
    services.role(request.user,('admin','pharmacy','manager','cashier'))
    class ReturnForm(forms.ModelForm):
        class Meta:
            model=MedicineReturn
            fields=['dispense','quantity','disposition','reason','inspection']
    form=ReturnForm(request.POST or None)
    form.fields['dispense'].queryset=filter_by_patient_facility(Dispense.objects.all(),request.user).order_by('-pk')
    selected=request.POST.get('dispense') or request.GET.get('dispense','')
    ids=list(form.fields['dispense'].queryset.values_list('pk',flat=True)[:30])
    if str(selected).isdigit():ids.append(int(selected));form.initial['dispense']=selected
    form.fields['dispense'].widget.choices=[('','Choose an original dispense')]+[(d.pk,f'#{d.pk} · {d.patient} · {d.item_code} × {d.quantity}') for d in form.fields['dispense'].queryset.filter(pk__in=ids).select_related('patient')]
    if request.method=='POST' and form.is_valid():
        try:
            data=form.cleaned_data
            obj=services.request_return(data['dispense'].pk,request.user,data['quantity'],data['disposition'],data['reason'],data['inspection'])
            return redirect('suite-return-detail',pk=obj.pk)
        except ValidationError as exc:form.add_error(None,'; '.join(exc.messages))
    page=Paginator(return_scope(request.user).select_related('dispense__patient').order_by('-pk'),25).get_page(request.GET.get('page'))
    return render(request,'operations/returns.html',{'form':form,'page':page})


@login_required
def return_detail(request,pk):
    services.role(request.user,('admin','pharmacy','manager','cashier'))
    obj=get_object_or_404(return_scope(request.user).select_related('dispense__patient','returned_batch','credit_line'),pk=pk)
    form=DecisionForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:services.review_return(pk,request.user,'post' if form.cleaned_data['decision']=='approve' else 'reject',form.cleaned_data['reason'])
        except ValidationError as exc:form.add_error(None,'; '.join(exc.messages))
        else:return redirect('suite-return-detail',pk=pk)
    return render(request,'operations/return_detail.html',{'record':obj,'patient':obj.dispense.patient,'form':form,'reconciliation':dispense_reconciliation(obj.dispense),'refund_links':obj.refund_links.select_related('refund__payment')})


@login_required
def refund_detail(request,pk):
    services.role(request.user,('admin','manager','cashier'))
    obj=get_object_or_404(refund_scope(request.user).select_related('payment__invoice__patient','authorization'),pk=pk)
    class RefundForm(forms.Form):
        action=forms.ChoiceField(choices=[('authorize','Authorize only'),('pay','Record cash handout')])
        reason=forms.CharField(max_length=250)
    form=RefundForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            if form.cleaned_data['action']=='authorize':services.authorize_refund(pk,request.user,form.cleaned_data['reason'])
            else:services.disburse_refund(pk,request.user)
        except ValidationError as exc:form.add_error(None,'; '.join(exc.messages))
        else:return redirect('suite-refund-detail',pk=pk)
    return render(request,'operations/refund_detail.html',{'record':obj,'patient':obj.payment.invoice.patient,'form':form})


@login_required
def price_reviews(request):
    services.role(request.user,('admin','pharmacy','manager'))
    page=Paginator(price_scope(request.user).select_related('line__basket__patient','line__item','created_by').order_by('-pk'),25).get_page(request.GET.get('page'))
    return render(request,'operations/price_reviews.html',{'page':page})


@login_required
def price_request(request,line_id):
    services.role(request.user,('admin','pharmacy'))
    line=get_object_or_404(filter_by_patient_facility(BasketLine.objects.all(),request.user,prefix='basket__patient__').select_related('basket__patient'),pk=line_id)
    class PriceForm(forms.Form):
        requested_price=forms.DecimalField(min_value=0,max_digits=12,decimal_places=2)
        reason=forms.CharField(max_length=250,widget=forms.Textarea(attrs={'rows':2}))
    form=PriceForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:obj=services.request_price(line_id,request.user,**form.cleaned_data)
        except ValidationError as exc:form.add_error(None,'; '.join(exc.messages))
        else:return redirect('suite-price-review',pk=obj.pk)
    return render(request,'operations/workflow_form.html',{'form':form,'patient':line.basket.patient,'title':f'Request price exception · {line.item}','help':f'Current unit price: {line.unit_price}. A different supervisor must approve. No price changes occur until approval.'})


@login_required
def price_review(request,pk):
    services.role(request.user,('admin','pharmacy','manager'))
    obj=get_object_or_404(price_scope(request.user).select_related('line__basket__patient','line__item','created_by','reviewed_by'),pk=pk)
    form=DecisionForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:services.review_price(pk,request.user,form.cleaned_data['decision'],form.cleaned_data['reason'])
        except ValidationError as exc:form.add_error(None,'; '.join(exc.messages))
        else:return redirect('suite-price-review',pk=pk)
    return render(request,'operations/price_review.html',{'record':obj,'patient':obj.line.basket.patient,'form':form})


@login_required
def replenishment(request):
    services.role(request.user,('admin','manager','store','pharmacy'))
    fid=user_staff_facility_id(request.user)
    if request.user.is_superuser and request.GET.get('facility','').isdigit():fid=int(request.GET['facility'])
    facility=get_object_or_404(Facility,pk=fid) if fid else None
    if not facility:raise PermissionDenied('Select an assigned facility before reviewing replenishment.')
    class RuleForm(forms.ModelForm):
        class Meta:
            model=ReplenishmentRule
            fields=['item','preferred_location','lead_days','review_days','safety_days']
        def clean(self):
            data=super().clean()
            for field in ('lead_days','review_days','safety_days'):
                if data.get(field,0)>365:self.add_error(field,'Use 0–365 days.')
            return data
    form=RuleForm(request.POST or None)
    form.fields['preferred_location'].queryset=StockLocation.objects.filter(facility=facility)
    if request.method=='POST':
        services.role(request.user,('admin','manager','store'))
        if form.is_valid():
            with transaction.atomic():
                Facility.objects.select_for_update().get(pk=facility.pk)
                rule,_=ReplenishmentRule.objects.get_or_create(facility=facility,item=form.cleaned_data['item'])
                for field,value in form.cleaned_data.items():setattr(rule,field,value)
                rule._history_user=request.user;rule.save()
            return redirect(request.path+'?facility='+str(facility.pk))
    q=request.GET.get('q','').strip()[:100]
    items=InventoryItem.objects.filter(Q(batches__location__facility=facility)|Q(replenishmentrule__facility=facility)).distinct().order_by('code')
    if q:items=items.filter(Q(code__icontains=q)|Q(name__icontains=q))
    page=Paginator(items,25).get_page(request.GET.get('page'))
    rows=replenishment_rows(facility,list(page))
    expiry=Batch.objects.filter(location__facility=facility,quantity_on_hand__gt=0,expiry__lte=timezone.localdate()+timedelta(days=90)).select_related('item','location').order_by('expiry','pk')
    expiry_page=Paginator(expiry,25).get_page(request.GET.get('expiry_page'))
    return render(request,'operations/replenishment.html',{'form':form,'page':page,'rows':rows,'expiry_page':expiry_page,'facility':facility,'q':q,'today':timezone.localdate()})


@login_required
def stock_detail(request,pk):
    services.role(request.user,('admin','manager','store','pharmacy'))
    batch=get_object_or_404(filter_by_facility(Batch.objects.all(),request.user,field='location__facility_id').select_related('item','location'),pk=pk)
    page=Paginator(StockMovement.objects.filter(batch=batch).order_by('-created_at','-pk'),50).get_page(request.GET.get('page'))
    return render(request,'operations/stock_detail.html',{'batch':batch,'page':page})
