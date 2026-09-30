import re
from decimal import Decimal, InvalidOperation
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from apps.demographics.models import Patient
from apps.orders.models import Order, OrderResult
from common.facility_scope import filter_by_patient_facility
from .workforce_services import reason_required, staff_at
from .models import DiagnosticTemplate, DiagnosticWorkItem, DiagnosticWorksheet


def diagnostic_role(actor):
    if not actor.is_active or not (actor.is_superuser or actor.role in ('admin','clinician','lab','radiology')):raise PermissionDenied


def order_scope(actor):
    diagnostic_role(actor)
    qs=filter_by_patient_facility(Order.objects.all(),actor)
    from common.service_policy import enabled
    if not enabled(actor,'lab'):qs=qs.exclude(order_type='lab')
    if not enabled(actor,'imaging'):qs=qs.exclude(order_type='imaging')
    if not enabled(actor,'clinical'):qs=qs.exclude(order_type='procedure')
    return qs.filter(order_type='imaging') if actor.role=='radiology' and not actor.is_superuser else qs


def locked_order(pk,actor):
    candidate=order_scope(actor).filter(pk=pk).first()
    if not candidate:raise PermissionDenied
    patient=Patient.objects.select_for_update().get(pk=candidate.patient_id)
    if patient.merged_into_id:raise ValidationError('Patient identity changed; reload.')
    order=Order.objects.select_for_update().get(pk=pk)
    if order.patient_id!=patient.pk:raise ValidationError('Order patient changed; reload.')
    return order


def validate_fields(fields):
    if not isinstance(fields,list) or not 1<=len(fields)<=60:raise ValidationError('Use 1–60 template fields.')
    keys=set()
    for field in fields:
        if not isinstance(field,dict):raise ValidationError('Each template field must be an object.')
        key=field.get('key','');kind=field.get('type','text')
        if not isinstance(key,str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}',key) or key in keys:raise ValidationError('Field keys must be unique lowercase identifiers.')
        keys.add(key)
        if kind not in ('text','number','choice') or not isinstance(field.get('label'),str) or not field['label'].strip() or len(field['label'])>160:raise ValidationError('Each field needs a label and supported type.')
        if not isinstance(field.get('required',False),bool):raise ValidationError('required must be true or false.')
        for name in ('unit','reference'):
            if not isinstance(field.get(name,''),str) or len(field.get(name,''))>250:raise ValidationError('Unit/reference text must be at most 250 characters.')
        if kind=='choice':
            choices=field.get('choices')
            if not isinstance(choices,list) or not 1<=len(choices)<=30 or any(not isinstance(c,str) or not c.strip() or len(c)>120 for c in choices) or len(set(choices))!=len(choices):raise ValidationError('Choice fields need 1–30 distinct text choices.')
    return fields


def clean_answers(fields,answers):
    validate_fields(fields)
    if not isinstance(answers,dict) or set(answers)-{f['key'] for f in fields}:raise ValidationError('Unknown worksheet fields.')
    clean={}
    for field in fields:
        value=answers.get(field['key'],'')
        if not isinstance(value,str):raise ValidationError('Worksheet values must be text.')
        value=value.strip()
        if field.get('required') and not value:raise ValidationError(f"{field['label']} is required.")
        if len(value)>5000:raise ValidationError('A worksheet value is too long.')
        if value and field.get('type')=='number':
            try:
                number=Decimal(value)
                if not number.is_finite() or abs(number)>Decimal('1e15'):raise InvalidOperation
            except InvalidOperation:raise ValidationError(f"{field['label']} must be a finite number.")
        if value and field.get('type')=='choice' and value not in field['choices']:raise ValidationError('Choose a configured option.')
        clean[field['key']]=value
    return clean


@transaction.atomic
def schedule(pk,actor,operator,modality,scheduled_at,preparation_note,revision):
    order=locked_order(pk,actor)
    if order.status!='ordered':raise ValidationError('Only an open order can be scheduled.')
    staff_at(operator,order.patient.facility_id)
    allowed=('admin','clinician','lab','radiology') if order.order_type=='imaging' else ('admin','clinician','lab')
    if operator.role not in allowed:raise ValidationError('Choose a diagnostic operator for this service.')
    item,_=DiagnosticWorkItem.objects.get_or_create(order=order,defaults={'created_by':actor})
    if item.revision!=revision:raise ValidationError('Worklist changed; reload before assigning.')
    if item.started_at:raise ValidationError('Started service assignments are retained. Finish/review the existing work before arranging another service.')
    item.operator=operator;item.modality=modality;item.scheduled_at=scheduled_at;item.preparation_note=preparation_note;item.revision+=1;item._history_user=actor;item.save();return item


@transaction.atomic
def start(pk,actor):
    order=locked_order(pk,actor)
    if order.status!='ordered':raise ValidationError('Order is not open.')
    item=DiagnosticWorkItem.objects.filter(order=order).first()
    if not item or item.operator_id!=actor.pk:raise ValidationError('Only the assigned operator may start the procedure.')
    if not item.started_at:item.started_at=timezone.now();item.revision+=1;item._history_user=actor;item.save()
    return item


@transaction.atomic
def submit(pk,actor,template,answers,key,supersedes=None,specimen=None,critical=False):
    order=locked_order(pk,actor)
    template=DiagnosticTemplate.objects.select_for_update().get(pk=template.pk)
    prior=DiagnosticWorksheet.objects.filter(request_key=key).first()
    clean=clean_answers(template.fields,answers)
    if prior:
        if prior.created_by_id!=actor.pk or prior.result.order_id!=order.pk or prior.template_id!=template.pk or prior.answers!=clean or prior.result.supersedes_id!=getattr(supersedes,'pk',None) or prior.result.specimen_id!=getattr(specimen,'pk',None) or prior.result.critical!=critical:raise ValidationError('Request key was reused for different report details.')
        return prior
    if order.status=='cancelled':raise ValidationError('Cannot report a cancelled order.')
    if order.order_type=='lab' and not specimen:raise ValidationError('Select the received specimen for this laboratory worksheet.')
    if specimen and (specimen.order_id!=order.pk or specimen.status!='received'):raise ValidationError('Choose a received specimen belonging to this order.')
    if specimen and specimen.custody_events.filter(event='disposed').exists():raise ValidationError('A disposed specimen cannot be used for a new worksheet.')
    if template.facility_id!=order.patient.facility_id or template.order_type!=order.order_type or template.status!='published':raise ValidationError('Choose a published matching template in this facility.')
    if supersedes and (supersedes.order_id!=order.pk or not supersedes.approved_at):raise ValidationError('Amend a released result from this order.')
    if supersedes and OrderResult.objects.filter(supersedes=supersedes,approved_at__isnull=False).exists():raise ValidationError('This result was already amended. Select the current amendment.')
    if not supersedes and order.status=='completed':raise ValidationError('Completed orders require a referenced amendment.')
    item=DiagnosticWorkItem.objects.filter(order=order).first()
    if not item or item.operator_id!=actor.pk or not item.started_at:raise ValidationError('The assigned operator must start the procedure before recording its worksheet.')
    if DiagnosticWorksheet.objects.filter(result__order=order,result__approved_at__isnull=True,withdrawn_at__isnull=True).exists():raise ValidationError('A draft worksheet already awaits review. Withdraw it before replacing it.')
    text=f'{template.name} · version {template.version}\n'+ '\n'.join(f"{f['label']}: {clean[f['key']]} {f.get('unit','')}"+(f" [Reference: {f['reference']}]" if f.get('reference') else '') for f in template.fields)
    result=OrderResult.objects.create(order=order,result_text=text,recorded_by=actor,supersedes=supersedes,specimen=specimen,critical=critical)
    sheet=DiagnosticWorksheet.objects.create(result=result,template=template,snapshot={'name':template.name,'version':template.version,'modality':template.modality,'fields':template.fields},answers=clean,request_key=key,created_by=actor)
    item.completed_at=timezone.now();item.revision+=1;item._history_user=actor;item.save();return sheet


@transaction.atomic
def review(pk,actor,decision,reason):
    candidate=DiagnosticWorksheet.objects.select_related('result').get(pk=pk)
    order=locked_order(candidate.result.order_id,actor)
    sheet=DiagnosticWorksheet.objects.select_for_update().get(pk=pk);result=OrderResult.objects.select_for_update().get(pk=sheet.result_id)
    reason_required(reason)
    if decision=='withdraw':
        if actor.pk!=sheet.created_by_id and not (actor.is_superuser or actor.role=='admin'):raise PermissionDenied
        if result.approved_at:raise ValidationError('Released reports require an amendment.')
        if not sheet.withdrawn_at:sheet.withdrawn_at=timezone.now();sheet.withdrawal_reason=reason;sheet._history_user=actor;sheet.save()
        return sheet
    if decision!='release':raise ValidationError('Unknown worksheet decision.')
    if not (actor.is_superuser or actor.role in ('admin','clinician') or (actor.role=='lab' and order.order_type=='lab')):raise PermissionDenied
    if actor.pk==sheet.created_by_id:raise ValidationError('Another qualified reviewer must release this report.')
    if sheet.withdrawn_at or order.status=='cancelled':raise ValidationError('Withdrawn/cancelled reports cannot be released.')
    if result.supersedes_id and OrderResult.objects.filter(supersedes_id=result.supersedes_id,approved_at__isnull=False).exclude(pk=result.pk).exists():raise ValidationError('Another amendment was already released.')
    if not result.approved_at:
        from .models import LabRunEvidence
        evidence=LabRunEvidence.objects.filter(worksheet=sheet).first()
        if evidence:
            from .extension_services import validate_run
            validate_run(evidence)
        result.approved_at=timezone.now();result.approved_by=actor;result._history_user=actor;result.save()
        sheet.review_reason=reason;sheet._history_user=actor;sheet.save()
        order.status='completed';order._history_user=actor;order.save(update_fields=['status'])
    return sheet
