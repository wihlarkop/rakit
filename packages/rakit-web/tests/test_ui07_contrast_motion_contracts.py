from importlib.resources import files


def _read(*parts: str) -> str:
    return files("rakit_web").joinpath(*parts).read_text()


def test_subtle_text_tokens_are_calibrated_for_light_and_dark_surfaces() -> None:
    source = _read("assets", "rakit.css")

    assert "--color-rakit-text-subtle: oklch(0.54 0.018 285);" in source
    assert "--color-rakit-text-subtle: oklch(0.62 0.022 285);" in source
    assert "--color-rakit-text-subtle: oklch(0.66 0.018 285);" not in source


def test_danger_controls_use_theme_aware_foreground() -> None:
    source = _read("assets", "rakit.css")

    assert (
        "@apply border-rakit-danger bg-rakit-danger text-rakit-bg hover:brightness-90;"
    ) in source
    assert (
        "@apply border-rakit-danger bg-rakit-danger text-rakit-bg "
        "shadow-rakit-sm hover:brightness-90;"
    ) in source


def test_reduced_motion_policy_keeps_state_but_removes_nonessential_motion() -> None:
    source = _read("assets", "rakit.css")

    assert "@media (prefers-reduced-motion: reduce)" in source
    assert "scroll-behavior: auto !important;" in source
    assert "animation-duration: 0.01ms !important;" in source
    assert "animation-iteration-count: 1 !important;" in source
    assert "transition-duration: 0.01ms !important;" in source

    # Loading state visibility is independent from animation.
    assert ".htmx-request .htmx-indicator" in source
    assert "visibility: visible;" in source


def test_action_impact_uses_semantic_warning_feedback() -> None:
    template = _read("templates", "actions", "_confirm.html")

    assert 'class="rakit-alert rakit-alert-warning" role="note"' in template
    assert "border-amber-300" not in template
    assert "bg-amber-50" not in template
    assert "text-amber-950" not in template
    assert "marked as potentially destructive" in template
    assert "runs only when you confirm and submit" in template


def test_delete_confirmation_explains_adapter_dependent_outcome() -> None:
    template = _read("templates", "forms", "delete_confirm.html")

    assert "Review the deletion details before continuing." in template
    assert "Deleting invokes the configured resource adapter for this record." in template
    assert "removal may be permanent or recoverable" in template
    assert "Confirm only if you intend to remove this record." in template
