from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one match in {path}, got {count}: {old[:120]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


path = "packages/rakit-web/src/rakit_web/field_presentation.py"
replace_once(
    path,
    '''        if self.min_value is not None and self.max_value is not None:\n            if self.min_value > self.max_value:\n                raise ValueError("date minimum cannot exceed maximum")\n''',
    '''        if (\n            self.min_value is not None\n            and self.max_value is not None\n            and self.min_value > self.max_value\n        ):\n            raise ValueError("date minimum cannot exceed maximum")\n''',
)
replace_once(path, '    placeholder: str = "YYYY-MM-DD – YYYY-MM-DD"\n', '    placeholder: str = "YYYY-MM-DD - YYYY-MM-DD"\n')
replace_once(
    path,
    '''        if self.min_value is not None and self.max_value is not None:\n            if self.min_value > self.max_value:\n                raise ValueError("number minimum cannot exceed maximum")\n''',
    '''        if (\n            self.min_value is not None\n            and self.max_value is not None\n            and self.min_value > self.max_value\n        ):\n            raise ValueError("number minimum cannot exceed maximum")\n''',
)
replace_once(
    path,
    '''        if self.min_value is not None and self.max_value is not None:\n            if self.min_value > self.max_value:\n                raise ValueError("currency minimum cannot exceed maximum")\n''',
    '''        if (\n            self.min_value is not None\n            and self.max_value is not None\n            and self.min_value > self.max_value\n        ):\n            raise ValueError("currency minimum cannot exceed maximum")\n''',
)
replace_once(
    path,
    '''        if self.min_value is not None and self.max_value is not None:\n            if self.min_value > self.max_value:\n                raise ValueError("percentage minimum cannot exceed maximum")\n''',
    '''        if (\n            self.min_value is not None\n            and self.max_value is not None\n            and self.min_value > self.max_value\n        ):\n            raise ValueError("percentage minimum cannot exceed maximum")\n''',
)
replace_once(
    "packages/rakit-web/tests/test_advanced_widget_contracts.py",
    '''async def test_boolean_hidden_fallback_accepts_exact_false_true_pair_without_relaxing_transport() -> (\n    None\n):\n''',
    '''async def test_boolean_hidden_fallback_accepts_exact_pair() -> None:\n''',
)
