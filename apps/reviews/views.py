from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.accounts.forms import StyledMixin
from apps.core.images import reencode
from apps.core.ratelimit import ratelimit
from apps.notifications import services as notify
from apps.orders.models import OrderLine

from .models import Review, ReviewPhoto
from .services import looks_abusive


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            return [single(d, initial) for d in data]
        return single(data, initial)


class ReviewForm(StyledMixin, forms.ModelForm):
    photos = MultipleFileField(
        required=False,
        label=gettext_lazy("Photos (up to 3)"),
        widget=MultipleFileInput(attrs={"accept": "image/*", "multiple": True}),
    )

    class Meta:
        model = Review
        fields = ["stars", "title", "body"]
        widgets = {
            "stars": forms.RadioSelect(choices=[(i, "★" * i) for i in range(5, 0, -1)]),
            "body": forms.Textarea(attrs={"rows": 4, "maxlength": 1500}),
        }
        labels = {"body": gettext_lazy("Your review")}


@login_required
@ratelimit("review", limit=6, window=3600)
def write(request, line_id):
    line = get_object_or_404(
        OrderLine.objects.select_related("variant__product", "order"),
        pk=line_id,
        order__user=request.user,
        order__status="delivered",
    )
    if hasattr(line, "review"):
        messages.info(request, _("You already reviewed this item. Thank you!"))
        return redirect(line.order.get_absolute_url())
    form = ReviewForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        files = request.FILES.getlist("photos")[:3]
        processed = []
        try:
            processed = [reencode(f, max_side=1200) for f in files]
        except ValidationError as exc:
            form.add_error("photos", exc.messages[0])
        if not form.errors:
            review = form.save(commit=False)
            review.product = line.variant.product
            review.user = request.user
            review.order_line = line
            review.flagged = looks_abusive(f"{review.title} {review.body}")
            review.save()
            for f in processed:
                ph = ReviewPhoto(review=review)
                ph.image.save(f.name, f, save=True)
            notify.admin_event(
                "new_review",
                {
                    "product": review.product.name,
                    "stars": review.stars,
                    "title": review.title,
                    "flagged": review.flagged,
                },
            )
            messages.success(request, _("Thanks! Your review will appear after a quick check."))
            return redirect(line.order.get_absolute_url())
    return render(request, "reviews/write.html", {"form": form, "line": line})
