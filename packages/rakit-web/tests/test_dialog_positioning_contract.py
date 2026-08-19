from importlib.resources import files


def test_dialog_primitive_is_centered_in_the_viewport() -> None:
    css = files("rakit_web").joinpath("assets", "rakit.css").read_text()
    start = css.index("  .rakit-dialog {")
    end = css.index("  .rakit-dialog-title {", start)
    dialog_rule = css[start:end]

    assert "position: fixed;" in dialog_rule
    assert "top: 50%;" in dialog_rule
    assert "left: 50%;" in dialog_rule
    assert "right: auto;" in dialog_rule
    assert "bottom: auto;" in dialog_rule
    assert "margin: 0;" in dialog_rule
    assert "transform: translate(-50%, -50%);" in dialog_rule
    assert "inset: 0;" not in dialog_rule
