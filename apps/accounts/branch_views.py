from django import forms
from django.contrib.auth.decorators import login_required
from django.shortcuts import render,redirect
from common.branch_access import facilities
from common.mfa import record


@login_required
def select(request):
    class Form(forms.Form):
        facility=forms.ModelChoiceField(queryset=facilities(request.user),required=not request.user.is_superuser,empty_label='All facilities (system administrator)' if request.user.is_superuser else None)
    form=Form(request.POST or None)
    if request.method=='POST' and form.is_valid():
        facility=form.cleaned_data['facility']
        request.session['active_facility_id']=facility.pk if facility else None
        record(request.user,'facility_selected',f'Facility {facility.pk}' if facility else 'All authorized facilities')
        return redirect('suite-home')
    return render(request,'operations/workflow_form.html',{'form':form,'title':'Select working facility','help':'Selection applies to this browser session and is checked on every request. It does not change your employment, role or clinical duty assignment.'})
