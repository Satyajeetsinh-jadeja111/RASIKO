from django.conf import settings
from django.urls import reverse

from .permissions import NAV, can


def dashboard(request):
    if not request.path.startswith("/" + settings.ADMIN_URL):
        return {}
    user = request.user
    sections = []
    for title, items in NAV:
        links = []
        for label, name, args, role, icon in items:
            if can(user, role):
                url = reverse(name, args=args)
                home = name == "dashboard:home"
                active = request.path == url if home else request.path.startswith(url)
                links.append({"label": label, "url": url, "icon": icon, "active": active})
        if links:
            sections.append((title, links))
    return {"dash_nav": sections, "is_manager": can(user, "manager"), "is_owner": can(user, "owner")}
