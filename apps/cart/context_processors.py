from .cart import Cart


def cart(request):
    if request.path.startswith(("/static/", "/media/")):
        return {}
    c = Cart(request)
    return {"cart_count": c.count, "cart_keys": c.data}
