"""Tests for the administrator's report font directory: the scan (`services.report_font_directory`), the catalogue that
lays the administrator's settings over it (`services.report_font_catalogue`) and the admin routes
(`routers.system.report_fonts`).

Fonts are copies of the bundled Liberation Mono under other names' files, with one byte patched where a test needs a
restricted licence, so no test depends on a font installed on the machine.
"""

from __future__ import annotations

import shutil
import struct
from pathlib import Path

import pytest

from app.config import get_settings
from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.report_font import ServerReportFont
from app.services import report_font_catalogue as catalogue
from app.services import report_fonts
from app.services.report_font_directory import MAX_FONT_BYTES, read_fs_type, scan_directory, slugify
from tests.conftest import auth_headers, create_org_user

_LIBERATION = Path(report_fonts.__file__).resolve().parent.parent / "assets" / "report_fonts"


def _copy(directory: Path, source: str, name: str | None = None) -> Path:
    """Copies a bundled Liberation file into `directory`."""
    target = directory / (name or source)
    shutil.copyfile(_LIBERATION / source, target)
    return target


def _set_fs_type(path: Path, value: int) -> None:
    """Patches the OS/2 `fsType` of a TrueType file in place."""
    data = bytearray(path.read_bytes())
    (count,) = struct.unpack(">H", data[4:6])
    for i in range(count):
        tag, _c, offset, _l = struct.unpack(">4sIII", data[12 + 16 * i:28 + 16 * i])
        if tag == b"OS/2":
            data[offset + 8:offset + 10] = struct.pack(">H", value)
            path.write_bytes(bytes(data))
            return
    raise AssertionError("no OS/2 table")


@pytest.fixture
def font_dir(tmp_path, monkeypatch):
    """A scratch font directory wired in as `REPORT_FONTS_DIR`, with a clean catalogue before and after."""
    directory = tmp_path / "fonts"
    directory.mkdir()
    monkeypatch.setenv("REPORT_FONTS_DIR", str(directory))
    get_settings.cache_clear()
    catalogue.reset()
    yield directory
    get_settings.cache_clear()
    catalogue.reset()


def test_slugify_is_stable():
    assert slugify("Liberation Mono") == "liberation-mono"
    assert slugify("  Fira Sans (Cond.) ") == "fira-sans-cond"
    assert slugify("日本語") == ""


def test_unconfigured_directory_scans_to_nothing():
    result = scan_directory("")
    assert (result.configured, result.families, result.skipped) == (False, {}, [])


def test_missing_directory_is_reported_not_raised(tmp_path):
    result = scan_directory(str(tmp_path / "nope"))
    assert result.configured and not result.families
    assert result.skipped[0].reason == "the font directory cannot be read"


def test_a_valid_family_is_grouped_with_its_real_faces(font_dir):
    for style in ("Regular", "Bold", "Italic"):
        _copy(font_dir, f"LiberationMono-{style}.ttf")
    result = scan_directory(str(font_dir))
    family = result.families["x-liberation-mono"]
    assert (family.label, family.bundled, family.faces_found) == ("Liberation Mono", False, ("regular", "bold", "italic"))
    assert family.files["bolditalic"] == family.files["bold"]  # no bold italic file: the nearest face, never a fake slant
    assert result.skipped == []
    assert read_fs_type(family.files["regular"]) == 0


def test_unusable_files_are_skipped_with_a_reason(font_dir):
    _copy(font_dir, "LiberationMono-Regular.ttf")
    _set_fs_type(_copy(font_dir, "LiberationSerif-Regular.ttf", "restricted.ttf"), 2)
    _set_fs_type(_copy(font_dir, "LiberationSerif-Bold.ttf", "nosubset.ttf"), 0x0100)
    (font_dir / "cff.otf").write_bytes(b"OTTO" + b"\0" * 100)
    (font_dir / "set.ttc").write_bytes(b"ttcf" + b"\0" * 100)
    (font_dir / "junk.ttf").write_bytes(b"not a font at all")
    (font_dir / "tt-magic-but-bad.ttf").write_bytes(b"\x00\x01\x00\x00" + b"\xff" * 200)
    (font_dir / "README.txt").write_text("ignored")
    big = font_dir / "big.ttf"
    big.write_bytes(b"\x00\x01\x00\x00" + b"\0" * (MAX_FONT_BYTES + 1))
    (font_dir / "link.ttf").symlink_to(font_dir / "LiberationMono-Regular.ttf")
    reasons = {s.file_name: s.reason for s in scan_directory(str(font_dir)).skipped}
    assert "forbids embedding" in reasons["restricted.ttf"] and "forbids" in reasons["nosubset.ttf"]
    assert "CFF" in reasons["cff.otf"] and "collections" in reasons["set.ttc"]
    assert reasons["junk.ttf"] == "not a TrueType font"
    assert reasons["tt-magic-but-bad.ttf"] == "could not be read as a TrueType font"
    assert reasons["big.ttf"].startswith("larger than")
    assert reasons["link.ttf"] == "symbolic links are not followed"
    assert "README.txt" not in reasons
    assert set(scan_directory(str(font_dir)).families) == {"x-liberation-mono"}  # restricted faces never form a family


def test_a_family_without_a_regular_face_is_skipped(font_dir):
    _copy(font_dir, "LiberationMono-Bold.ttf")
    result = scan_directory(str(font_dir))
    assert result.families == {}
    assert "no regular face" in result.skipped[0].reason


def test_a_second_face_of_the_same_style_is_skipped(font_dir):
    _copy(font_dir, "LiberationMono-Regular.ttf")
    _copy(font_dir, "LiberationMono-Regular.ttf", "copy-of-regular.ttf")
    result = scan_directory(str(font_dir))
    assert [s.file_name for s in result.skipped] == ["copy-of-regular.ttf"]


def test_extra_family_registers_and_draws_in_pdf_names(font_dir):
    _copy(font_dir, "LiberationMono-Regular.ttf")
    catalogue.rescan()
    family = report_fonts.get_family("x-liberation-mono")
    assert report_fonts.pdf_face("x-liberation-mono", bold=True) == "Report-x-liberation-mono-bold"
    assert family.files["bold"] == family.files["regular"]
    assert report_fonts.covers("x-liberation-mono", "Ж")


def test_a_changed_directory_is_noticed_without_a_rescan(font_dir, monkeypatch):
    catalogue.current_scan()
    _copy(font_dir, "LiberationMono-Regular.ttf")
    assert "x-liberation-mono" not in catalogue.current_scan().families  # inside the refresh interval
    monkeypatch.setattr(catalogue, "REFRESH_SECONDS", 0.0)
    assert "x-liberation-mono" in catalogue.current_scan().families


def test_catalogue_lays_settings_over_the_scan(font_dir):
    _copy(font_dir, "LiberationMono-Regular.ttf")
    db = SessionLocal()
    try:
        info = {i.key: i for i in catalogue.describe_fonts(db)}
        assert list(info)[:4] == ["sans", "serif", "mono", "unicode"]
        assert (info["x-liberation-mono"].enabled, info["x-liberation-mono"].word_name) == (True, "Liberation Mono")
        catalogue.update_font(db, "x-liberation-mono", word_name="Courier Prime", generic="monospace", enabled=False, actor_id=None)
        db.commit()
        info = {i.key: i for i in catalogue.describe_fonts(db)}
        hidden = info["x-liberation-mono"]
        assert (hidden.enabled, hidden.word_name, hidden.generic) == (False, "Courier Prime", "monospace")
        assert [i.key for i in catalogue.author_choices(db)] == ["sans", "serif", "mono", "unicode"]
        assert catalogue.effective_families(db)["x-liberation-mono"].css_stack == '"Courier Prime", monospace'  # hidden still renders
        with pytest.raises(KeyError):
            catalogue.update_font(db, "x-not-there", word_name=None, generic="serif", enabled=True, actor_id=None)
        with pytest.raises(KeyError):
            catalogue.update_font(db, "sans", word_name=None, generic="serif", enabled=True, actor_id=None)
        with pytest.raises(ValueError):
            catalogue.update_font(db, "x-liberation-mono", word_name=None, generic="cursive", enabled=True, actor_id=None)
    finally:
        db.query(ServerReportFont).delete()
        db.commit()
        db.close()


def test_a_family_whose_files_are_gone_is_missing_and_falls_back(font_dir):
    path = _copy(font_dir, "LiberationMono-Regular.ttf")
    db = SessionLocal()
    try:
        catalogue.update_font(db, "x-liberation-mono", word_name="Courier Prime", generic="monospace", enabled=True, actor_id=None)
        db.commit()
        path.unlink()
        catalogue.rescan()
        info = {i.key: i for i in catalogue.describe_fonts(db)}
        assert info["x-liberation-mono"].missing and info["x-liberation-mono"].family is None
        assert "x-liberation-mono" not in [i.key for i in catalogue.author_choices(db)]
        family, note = catalogue.family_or_fallback(db, "x-liberation-mono")
        assert family.key == "mono" and "Courier Prime" in (note or "")
        assert catalogue.family_or_fallback(db, "sans") == (report_fonts.FAMILIES["sans"], None)
        family, note = catalogue.family_or_fallback(db, "x-never-seen")
        assert family.key == "sans" and note
        assert len(catalogue.font_problems(db, ["sans", "x-liberation-mono", "x-never-seen"])) == 2
        assert catalogue.font_problems(db, ["sans", "mono"]) == []
    finally:
        db.query(ServerReportFont).delete()
        db.commit()
        db.close()


# --- Routes ----------------------------------------------------------------------------------------------------------

def _audit(action: str) -> list[AuditEvent]:
    db = SessionLocal()
    try:
        return list(db.query(AuditEvent).filter(AuditEvent.action == action).all())
    finally:
        db.close()


def test_admin_lists_updates_and_rescans(client, admin_token, font_dir):
    h = auth_headers(admin_token)
    page = client.get("/api/v1/system/report-fonts", headers=h).json()
    assert page["directory_configured"] and [f["key"] for f in page["families"]] == ["sans", "serif", "mono", "unicode"]
    _copy(font_dir, "LiberationMono-Regular.ttf")
    (font_dir / "bad.ttf").write_bytes(b"nonsense")
    page = client.post("/api/v1/system/report-fonts/rescan", headers=h).json()
    extra = next(f for f in page["families"] if f["key"] == "x-liberation-mono")
    assert (extra["bundled"], extra["enabled"], extra["word_name"], extra["generic"]) == (False, True, "Liberation Mono", "sans-serif")
    assert extra["faces"] == [{"style": "regular", "permission": "Installable"}]
    assert page["skipped"] == [{"file_name": "bad.ttf", "reason": "not a TrueType font"}]
    assert "/" not in str(page["skipped"]) and str(font_dir) not in str(page)
    assert _audit("report_font.rescanned")[0].detail == {"families": 1, "skipped": 1}

    page = client.put(
        "/api/v1/system/report-fonts/x-liberation-mono", json={"word_name": "Courier Prime", "generic": "monospace", "enabled": False}, headers=h,
    ).json()
    extra = next(f for f in page["families"] if f["key"] == "x-liberation-mono")
    assert (extra["enabled"], extra["word_name"], extra["generic"]) == (False, "Courier Prime", "monospace")
    event = _audit("report_font.updated")[0]
    assert (event.entity_id, event.detail) == ("x-liberation-mono", {"enabled": False, "generic": "monospace", "word_name_set": True})
    db = SessionLocal()
    db.query(ServerReportFont).delete()
    db.commit()
    db.close()


def test_hiding_a_family_removes_it_from_the_authors_picker(client, admin_token, font_dir):
    h = auth_headers(admin_token)
    _copy(font_dir, "LiberationMono-Regular.ttf")
    client.post("/api/v1/system/report-fonts/rescan", headers=h)
    assert "x-liberation-mono" in [c["key"] for c in client.get("/api/v1/system/report-fonts/choices", headers=h).json()]
    client.put("/api/v1/system/report-fonts/x-liberation-mono", json={"generic": "monospace", "enabled": False}, headers=h)
    assert [c["key"] for c in client.get("/api/v1/system/report-fonts/choices", headers=h).json()] == ["sans", "serif", "mono", "unicode"]
    client.put("/api/v1/system/report-fonts/x-liberation-mono", json={"generic": "monospace", "enabled": True}, headers=h)
    assert "x-liberation-mono" in [c["key"] for c in client.get("/api/v1/system/report-fonts/choices", headers=h).json()]
    db = SessionLocal()
    db.query(ServerReportFont).delete()
    db.commit()
    db.close()


def test_only_the_server_administrator_manages_fonts(client, admin_token, org_id, font_dir):
    create_org_user(client, admin_token, org_id, "fonts-member@example.com", role="org_admin")
    from tests.conftest import login

    token = login(client, "fonts-member@example.com", "Password123!")
    h = auth_headers(token)
    assert client.get("/api/v1/system/report-fonts", headers=h).status_code == 403
    assert client.post("/api/v1/system/report-fonts/rescan", headers=h).status_code == 403
    assert client.put("/api/v1/system/report-fonts/x-a", json={"generic": "serif", "enabled": True}, headers=h).status_code == 403
    assert client.get("/api/v1/system/report-fonts/choices", headers=h).status_code == 200  # authors read the picker list
    assert client.get("/api/v1/system/report-fonts/choices").status_code in (401, 403)


@pytest.mark.parametrize("name", ['Evil"; x', "A<b>", "semi;colon", "back\\slash", "x" * 101])
def test_a_font_name_that_could_break_css_or_xml_is_refused(client, admin_token, font_dir, name):
    _copy(font_dir, "LiberationMono-Regular.ttf")
    h = auth_headers(admin_token)
    client.post("/api/v1/system/report-fonts/rescan", headers=h)
    r = client.put("/api/v1/system/report-fonts/x-liberation-mono", json={"word_name": name, "generic": "serif", "enabled": True}, headers=h)
    assert r.status_code == 422


def test_unknown_or_bundled_keys_and_bad_generics_are_refused(client, admin_token, font_dir):
    h = auth_headers(admin_token)
    assert client.put("/api/v1/system/report-fonts/x-nothing", json={"generic": "serif", "enabled": True}, headers=h).status_code == 404
    assert client.put("/api/v1/system/report-fonts/sans", json={"generic": "serif", "enabled": True}, headers=h).status_code == 404
    assert client.put("/api/v1/system/report-fonts/x-nothing", json={"generic": "cursive", "enabled": True}, headers=h).status_code == 422
