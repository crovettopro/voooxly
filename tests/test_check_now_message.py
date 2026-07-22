from voooxly import app, updates


def test_available_con_notes_incluye_version_y_notes():
    info = {"version": "1.3.0", "url": "u", "notes": "Faster launch."}
    title, body = app.check_now_message(updates.UPDATE_AVAILABLE, info, "1.2.0")
    assert title == "Update available"
    assert "1.3.0" in body
    assert "Faster launch." in body


def test_available_sin_notes_no_ponelineas_vacias():
    info = {"version": "1.3.0", "url": "u", "notes": ""}
    title, body = app.check_now_message(updates.UPDATE_AVAILABLE, info, "1.2.0")
    assert title == "Update available"
    assert body.strip() == "Voooxly 1.3.0 is available."


def test_up_to_date_muestra_version_instalada():
    title, body = app.check_now_message(updates.UP_TO_DATE, None, "1.2.0")
    assert title == "Up to date"
    assert "1.2.0" in body


def test_error_dice_que_no_se_pudo_comprobar():
    title, body = app.check_now_message(updates.UPDATE_ERROR, None, "1.2.0")
    assert title == "Couldn't check"
    assert "couldn't reach" in body.lower()