"""Read-only admin inspection for records maintained by guarded workflows."""
from django.contrib import admin


class WorkflowReadOnlyMixin:
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields) + tuple(self.readonly_fields)


class WorkflowReadOnlyAdmin(WorkflowReadOnlyMixin, admin.ModelAdmin):
    actions = None


class WorkflowReadOnlyInline(WorkflowReadOnlyMixin, admin.TabularInline):
    extra = 0
    can_delete = False
