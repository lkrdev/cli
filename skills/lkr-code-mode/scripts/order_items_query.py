# ruff: noqa: F821
"""Run an inline query on thelook / order_items with status filter."""


def main():
    return run_inline_query(  # ty: ignore[unresolved-reference]
        result_format="json",
        body={
            "model": "thelook",
            "view": "order_items",
            "fields": [
                "order_items.created_year",
                "users.count",
            ],
            "filters": {
                "order_items.status": "Returned",
            },
            "sorts": ["order_items.created_year desc"],
            "limit": "500",
        },
    )


main()
