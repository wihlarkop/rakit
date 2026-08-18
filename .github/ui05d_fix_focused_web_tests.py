from pathlib import Path


QUERY_UI = Path("packages/rakit-web/tests/test_query_ui.py")
text = QUERY_UI.read_text()

# A previous migration pass temporarily left both declarations in place; the
# second default=1 declaration shadowed the intended default=2 fixture policy.
duplicate_pagination = (
    "    pagination = ResourcePaginationPolicy(size=PageSizePolicy(default=2, allowed=(1, 2, 3)))\n"
    "    pagination = ResourcePaginationPolicy(size=PageSizePolicy(default=1, allowed=(1, 2, 3)))\n"
)
single_pagination = (
    "    pagination = ResourcePaginationPolicy(size=PageSizePolicy(default=2, allowed=(1, 2, 3)))\n"
)
if duplicate_pagination in text:
    text = text.replace(duplicate_pagination, single_pagination, 1)
elif single_pagination not in text:
    raise SystemExit("missing UserAdmin pagination fixture anchor")

# Canonical query URLs omit CountPolicy.EXACT because it is the default. Keep
# non-default deferred/disabled policies explicit and assert exactly that.
old_expected = "    expected_without_page = params\n"
new_expected = (
    "    expected_without_page = [\n"
    "        pair\n"
    "        for pair in params\n"
    "        if pair != (\"count_policy\", \"exact\")\n"
    "    ]\n"
)
if old_expected in text:
    text = text.replace(old_expected, new_expected, 1)
elif new_expected not in text:
    raise SystemExit("missing pagination canonicalization assertion anchor")

# Keep terminology aligned with the canonical page-number strategy.
text = text.replace(
    "    # per_page=99999 violates OffsetPagination's le=200 bound; parse_query must\n"
    "    # not let it through -- it falls back to the default query (both rows fit).\n",
    "    # per_page=99999 is outside this resource's allowlisted page sizes; the\n"
    "    # request falls back to the resource default (both seeded rows fit).\n",
)

QUERY_UI.write_text(text)
