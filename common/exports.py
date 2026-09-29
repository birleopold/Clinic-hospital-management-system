import csv
from io import StringIO, BytesIO
from typing import List, Sequence, Dict
from django.http import HttpResponse


def csv_response(filename: str, headers: List[str], rows: Sequence[Dict]) -> HttpResponse:
    sio = StringIO()
    writer = csv.DictWriter(sio, fieldnames=headers)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, '') for k in headers})
    output = sio.getvalue()
    resp = HttpResponse(output, content_type='text/csv')
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp


def xlsx_response(filename: str, headers: List[str], rows: Sequence[Dict]) -> HttpResponse:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = 'Report'
    ws.append(headers)
    for row in rows:
        ws.append([row.get(k, '') for k in headers])
    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    resp = HttpResponse(
        bio.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp

def pdf_response_from_template(template_name, context, filename):
    from django.template.loader import render_to_string
    try:
        from xhtml2pdf import pisa
    except Exception:
        return HttpResponse('PDF generator not installed', status=500)
    html = render_to_string(template_name, context)
    bio = BytesIO()
    result = pisa.CreatePDF(src=html, dest=bio)
    if result.err:
        return HttpResponse('Error generating PDF', status=500)
    bio.seek(0)
    resp = HttpResponse(bio.getvalue(), content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp
