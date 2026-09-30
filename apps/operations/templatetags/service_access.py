"""Server-rendered link visibility using the same service catalog as route gates."""
from html.parser import HTMLParser
from django import template
from common.service_policy import can_open
register=template.Library()


class LinkParser(HTMLParser):
    def __init__(self):super().__init__();self.href=None
    def handle_starttag(self,tag,attrs):
        if tag=='a' and self.href is None:self.href=dict(attrs).get('href')


class AccessibleLink(template.Node):
    def __init__(self,nodes):self.nodes=nodes
    def render(self,context):
        rendered=self.nodes.render(context)
        user=context.get('user')
        if not user or not user.is_authenticated:return rendered
        parser=LinkParser();parser.feed(rendered);href=parser.href
        if href and href.startswith('/') and not href.startswith('//') and not can_open(user,href):return ''
        return rendered


@register.tag('accessible_link')
def accessible_link(parser,token):
    nodes=parser.parse(('endaccessible_link',));parser.delete_first_token()
    return AccessibleLink(nodes)
