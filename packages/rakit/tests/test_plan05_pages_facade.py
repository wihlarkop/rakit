"""Public facade contract for Plan 05 Task 6 pages."""

from rakit import (
    DomainPageHandler,
    PageContext,
    PageDefinition,
    PageRedirect,
    PageRejected,
    PageResult,
    PreparedPageMutationHandler,
)


def test_page_types_are_available_from_the_public_facade() -> None:
    assert PageContext.__name__ == "PageContext"
    assert PageDefinition.__name__ == "PageDefinition"
    assert PageResult.__name__ == "PageResult"
    assert PageRedirect.__name__ == "PageRedirect"
    assert PageRejected.__name__ == "PageRejected"
    assert DomainPageHandler.__name__ == "DomainPageHandler"
    assert PreparedPageMutationHandler.__name__ == "PreparedPageMutationHandler"
