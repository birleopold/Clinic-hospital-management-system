from django.core.exceptions import ValidationError
from django.http import JsonResponse

class WorkflowValidationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        return self.get_response(request)
    def process_exception(self, request, exception):
        if isinstance(exception, ValidationError):
            return JsonResponse({'detail': exception.messages}, status=400)
