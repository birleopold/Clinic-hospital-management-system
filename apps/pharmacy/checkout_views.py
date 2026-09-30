from decimal import Decimal
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction, IntegrityError
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from common.facility_scope import filter_by_facility, filter_by_patient_facility, user_staff_facility_id
from apps.demographics.models import Patient
from apps.inventory.models import InventoryItem
from apps.operations.models import PackageUnit
from .models import MedicineProfile, MedicineBarcode, PharmacyPolicy, DispensingBasket, PrescriptionItem
from . import checkout_services as services
from .services import usable_batches


def can_read(user):
    if not user.is_superuser and user.role not in ('admin','pharmacy','clinician','store','manager'):
        raise PermissionDenied


def baskets_for(user):
    services.require_dispenser(user)
    return filter_by_patient_facility(DispensingBasket.objects.all(),user)


class ProfileForm(forms.ModelForm):
    class Meta:
        model=MedicineProfile
        exclude=['item']


class BarcodeForm(forms.ModelForm):
    class Meta:
        model=MedicineBarcode
        fields=['code','package','active']


@login_required
def catalog(request):
    can_read(request.user)
    q=request.GET.get('q','').strip()[:100]
    items=InventoryItem.objects.select_related('medicine').order_by('name','pk')
    if q:items=items.filter(Q(code__icontains=q)|Q(name__icontains=q)|Q(medicine__generic_name__icontains=q)|Q(medicine__ingredients__icontains=q)|Q(barcodes__code=q)).distinct()
    page=Paginator(items,25).get_page(request.GET.get('page'))
    return render(request,'pharmacy/catalog.html',{'page':page,'q':q})


@login_required
def catalog_detail(request,pk):
    can_read(request.user)
    item=get_object_or_404(InventoryItem,pk=pk)
    profile=MedicineProfile.objects.filter(item=item).first() or MedicineProfile(item=item)
    editing=request.method=='POST'
    if editing and not request.user.is_superuser:raise PermissionDenied('The shared catalog is maintained by a system administrator.')
    form=ProfileForm(request.POST if editing and request.POST.get('action')=='profile' else None,instance=profile)
    barcode=MedicineBarcode(item=item)
    barcode_form=BarcodeForm(request.POST if editing and request.POST.get('action')=='barcode' else None,instance=barcode,prefix='barcode')
    barcode_form.fields['package'].queryset=PackageUnit.objects.filter(item=item)
    if editing and request.POST.get('action')=='deactivate':
        alias=get_object_or_404(MedicineBarcode,pk=request.POST.get('barcode_id'),item=item)
        alias.active=False;alias._history_user=request.user;alias.save(update_fields=['active'])
        return redirect('pharmacy-catalog-detail',pk=pk)
    if editing:
        chosen=barcode_form if request.POST.get('action')=='barcode' else form
        if chosen.is_valid():
            try:
                with transaction.atomic():
                    obj=chosen.save(commit=False);obj._history_user=request.user;obj.save()
                messages.success(request,'Catalog saved. Open baskets will recheck changes before dispensing.')
                return redirect('pharmacy-catalog-detail',pk=pk)
            except IntegrityError:chosen.add_error(None,'This entry changed or its code already exists. Reload and try again.')
    return render(request,'pharmacy/catalog_detail.html',{'item':item,'profile':profile,'form':form,'barcode_form':barcode_form,'barcodes':item.barcodes.select_related('package').order_by('code'),'editable':request.user.is_superuser})


@login_required
def policy(request):
    if not (request.user.is_superuser or request.user.role in ('admin','manager')):raise PermissionDenied
    fid=user_staff_facility_id(request.user)
    if not fid:raise PermissionDenied('Assign a facility before editing its dispensing policy.')
    obj=PharmacyPolicy.objects.filter(facility_id=fid).first() or PharmacyPolicy(facility_id=fid)
    class PolicyForm(forms.ModelForm):
        class Meta:
            model=PharmacyPolicy
            fields=['allow_retail']
    form=PolicyForm(request.POST or None,instance=obj)
    if request.method=='POST' and form.is_valid():
        obj=form.save(commit=False);obj._history_user=request.user;obj.save()
        messages.success(request,'Facility dispensing policy saved.')
        return redirect('pharmacy-policy')
    return render(request,'operations/workflow_form.html',{'form':form,'title':'Facility pharmacy policy','help':'The default requires a prescription. Enable retail only after approving which catalog medicines may be supplied without a prescription. This does not authorize price overrides or credit.'})


@login_required
def patient_lookup(request):
    services.require_dispenser(request.user)
    qs=filter_by_facility(Patient.objects.filter(merged_into__isnull=True),request.user)
    q=request.GET.get('q','').strip()[:100]
    if q:qs=qs.filter(Q(first_name__icontains=q)|Q(last_name__icontains=q)|Q(phone__icontains=q)|Q(medical_record_id__icontains=q))
    return JsonResponse({'results':[{'id':p.pk,'label':f'{p} · {p.medical_record_id}'} for p in qs.order_by('first_name','pk')[:30]]})


@login_required
def baskets(request):
    qs=baskets_for(request.user).select_related('patient','created_by').order_by('-updated_at','-pk')
    status=request.GET.get('status','open')
    if status in ('open','held','completed','cancelled'):qs=qs.filter(status=status)
    elif status!='all':status='open';qs=qs.filter(status=status)
    class NewBasketForm(forms.Form):
        patient=forms.ModelChoiceField(queryset=filter_by_facility(Patient.objects.filter(merged_into__isnull=True),request.user),widget=forms.Select(attrs={'data-lookup':'/pharmacy/baskets/patients/'}))
    initial={}
    patient_id=request.GET.get('patient','')
    if patient_id.isdigit() and filter_by_facility(Patient.objects.all(),request.user).filter(pk=patient_id).exists():initial['patient']=patient_id
    form=NewBasketForm(request.POST or None,initial=initial)
    field=form.fields['patient'];selected=request.POST.get('patient') or initial.get('patient')
    ids=list(field.queryset.order_by('pk').values_list('pk',flat=True)[:30])
    if str(selected or '').isdigit():ids.append(int(selected))
    field.widget.choices=[('','Choose a patient')]+[(p.pk,f'{p} · {p.medical_record_id}') for p in field.queryset.filter(pk__in=ids)]
    if request.method=='POST' and form.is_valid():
        try:
            basket=services.create_basket(form.cleaned_data['patient'].pk,request.user)
            return redirect('pharmacy-basket',pk=basket.pk)
        except ValidationError as exc:form.add_error(None,exc)
    return render(request,'pharmacy/baskets.html',{'page':Paginator(qs,25).get_page(request.GET.get('page')),'form':form,'status':status})


@login_required
def basket_detail(request,pk):
    basket=get_object_or_404(baskets_for(request.user).select_related('patient','invoice'),pk=pk)
    class AddForm(forms.Form):
        code=forms.CharField(max_length=100,label='Scan barcode or enter inventory code',widget=forms.TextInput(attrs={'autofocus':True,'autocomplete':'off'}))
        packs=forms.DecimalField(min_value=Decimal('.01'),max_digits=10,decimal_places=2,initial=1,label='Quantity of scanned packages / base units')
        prescription_item=forms.ModelChoiceField(queryset=PrescriptionItem.objects.filter(prescription__patient=basket.patient).select_related('prescription').order_by('-pk'),required=False,label='Matching prescription line')
        instructions=forms.CharField(required=False,max_length=2000,widget=forms.Textarea(attrs={'rows':2}),help_text='Additional pharmacist instructions; original prescription directions are retained separately.')
        revision=forms.IntegerField(widget=forms.HiddenInput(),initial=basket.revision)
    form=AddForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            pi=form.cleaned_data['prescription_item']
            services.add_item(pk,request.user,form.cleaned_data['revision'],form.cleaned_data['code'],form.cleaned_data['packs'],pi.pk if pi else None,form.cleaned_data['instructions'])
            messages.success(request,'Medicine added. Review the basket before dispensing.')
            return redirect('pharmacy-basket',pk=pk)
        except ValidationError as exc:form.add_error(None,exc)
    lines=list(basket.lines.filter(removed=False).select_related('item','prescription_item').prefetch_related('allocations__dispense__batch').order_by('pk'))
    stock={row['item_id']:row['total'] for row in usable_batches().filter(item_id__in=[l.item_id for l in lines],location__facility_id=basket.patient.facility_id).values('item_id').annotate(total=Sum('quantity_on_hand'))}
    for line in lines:line.available=stock.get(line.item_id,0)
    return render(request,'pharmacy/basket.html',{'basket':basket,'patient':basket.patient,'lines':lines,'form':form,'estimated_total':sum((l.total for l in lines),Decimal('0'))})


@login_required
@require_POST
def basket_action(request,pk):
    get_object_or_404(baskets_for(request.user),pk=pk)
    try:
        try:revision=int(request.POST.get('revision',''))
        except (ValueError,TypeError):raise ValidationError('Reload the basket before continuing.')
        action=request.POST.get('action')
        if action=='checkout':
            if request.POST.get('reviewed')!='on':raise ValidationError('Confirm patient, medicines, quantities and instructions before dispensing.')
            services.checkout(pk,request.user,revision,request.POST.get('checkout_key'))
            messages.success(request,'Dispensed once and invoice prepared. Cashier records payment separately.')
        else:
            line_id=request.POST.get('line_id','')
            services.change_basket(pk,request.user,revision,action,int(line_id) if line_id.isdigit() else None)
    except ValidationError as exc:messages.error(request,'; '.join(exc.messages))
    return redirect('pharmacy-basket',pk=pk)


@login_required
def labels(request,pk):
    basket=get_object_or_404(baskets_for(request.user).select_related('patient'),pk=pk,status='completed')
    lines=basket.lines.filter(removed=False).prefetch_related('allocations__dispense__batch').order_by('pk')
    return render(request,'pharmacy/basket_labels.html',{'basket':basket,'lines':lines})
