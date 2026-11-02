from rest_framework.exceptions import NotFound, ValidationError

from ..branches import get_model


def paginate(request, items, default_size=30, max_size=200):
    try:
        page = max(1, int(request.query_params.get("page", 1)))
        size = min(max_size, max(1, int(request.query_params.get("page_size", default_size))))
    except ValueError:
        raise ValidationError("page and page_size must be numbers")
    start = (page - 1) * size
    return {
        "count": len(items),
        "page": page,
        "page_size": size,
        "has_next": start + size < len(items),
        "results": items[start:start + size],
    }


def member_or_404(branch, pk):
    Model = get_model(branch)
    if Model is None:
        raise NotFound("Unknown family branch.")
    m = Model.objects.filter(pk=pk).first()
    if m is None:
        raise NotFound("Member not found.")
    return Model, m
