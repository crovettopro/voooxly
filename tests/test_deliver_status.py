"""deliver() must report how the delivery went, so the UI can warn
when the paste fails and the text ends up "only" in the clipboard."""
import voooxly.output as output


def _patch(monkeypatch, paste_ok: bool):
    monkeypatch.setattr(output, "copy_to_clipboard", lambda text, html=None: None)
    monkeypatch.setattr(output, "paste_frontmost", lambda: paste_ok)
    # no real waits in tests
    monkeypatch.setattr(output.time, "sleep", lambda s: None)


def test_pasted_ok(monkeypatch):
    _patch(monkeypatch, paste_ok=True)
    assert output.deliver("hola", auto_paste=True, copy=True) == "pasted"


def test_paste_fails_but_copied(monkeypatch):
    _patch(monkeypatch, paste_ok=False)
    assert output.deliver("hola", auto_paste=True, copy=True) == "copied"


def test_paste_fails_without_copy(monkeypatch):
    _patch(monkeypatch, paste_ok=False)
    assert output.deliver("hola", auto_paste=True, copy=False) == "failed"


def test_clipboard_only_mode(monkeypatch):
    _patch(monkeypatch, paste_ok=True)
    assert output.deliver("hola", auto_paste=False, copy=True) == "copied"


def test_empty_text(monkeypatch):
    _patch(monkeypatch, paste_ok=True)
    assert output.deliver("", auto_paste=True, copy=True) == "failed"
