from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    # Pickers that must show every row — the store list an order is split
    # across — ask for one big page rather than paging behind a checkbox grid.
    page_size_query_param = "page_size"
    max_page_size = 1000
