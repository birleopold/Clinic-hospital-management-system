from django import template

register = template.Library()

@register.filter(name='get_item')
def get_item(d, key):
    try:
        return d.get(key, '')
    except Exception:
        return ''
