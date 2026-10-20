"""Query pagination helpers shared by web pages and the API."""
from __future__ import annotations

from typing import Any

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def clamp_page_size(requested: int | None, default: int = DEFAULT_PAGE_SIZE) -> int:
    if requested is None:
        return default
    return max(1, min(int(requested), MAX_PAGE_SIZE))


def paginate_stable(query, page: int, per_page: int) -> dict[str, Any]:
    """Paginate a query, returning plain-Python page metadata.

    Out-of-range pages clamp to the last one; error_out=False per
    flask-sqlalchemy semantics so bad inputs never 500.
    """
    page_object = query.paginate(page=page, per_page=per_page, error_out=False)
    return {
        "items": page_object.items,
        "page": page_object.page,
        "pages": page_object.pages,
        "per_page": page_object.per_page,
        "total": page_object.total,
        "has_prev": page_object.has_prev,
        "has_next": page_object.has_next,
        "prev_num": page_object.prev_num,
        "next_num": page_object.next_num,
    }
