"""
Facility-based row scoping for multi-branch readiness.

Users with a StaffProfile.facility set only see rows for that facility.
Superusers and users without an assigned facility see all rows (legacy / admin).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from django.db.models import QuerySet

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser


def is_superuser(user: Optional['AbstractBaseUser']) -> bool:
    return bool(user and user.is_authenticated and getattr(user, 'is_superuser', False))


def user_staff_facility_id(user: Optional['AbstractBaseUser']) -> Optional[int]:
    if not user or not user.is_authenticated:
        return None
    profile = getattr(user, 'staff_profile', None)
    if profile and profile.facility_id:
        return int(profile.facility_id)
    return None


def filter_by_facility(qs: QuerySet, user, field: str = 'facility_id') -> QuerySet:
    if is_superuser(user):
        return qs
    fid = user_staff_facility_id(user)
    if fid is None:
        return qs
    return qs.filter(**{field: fid})


def filter_by_patient_facility(qs: QuerySet, user, prefix: str = 'patient__') -> QuerySet:
    if is_superuser(user):
        return qs
    fid = user_staff_facility_id(user)
    if fid is None:
        return qs
    return qs.filter(**{f'{prefix}facility_id': fid})


def filter_by_encounter_facility(qs: QuerySet, user, prefix: str = 'encounter__') -> QuerySet:
    if is_superuser(user):
        return qs
    fid = user_staff_facility_id(user)
    if fid is None:
        return qs
    return qs.filter(**{f'{prefix}facility_id': fid})


def assign_facility_for_patient(user, patient) -> None:
    """Set patient.facility from staff profile when missing (in-memory update)."""
    fid = user_staff_facility_id(user)
    if fid and patient.facility_id is None:
        patient.facility_id = fid
