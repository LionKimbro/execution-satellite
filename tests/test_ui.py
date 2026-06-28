from pathlib import Path

from executionsatellite import ui


def make_config():
    return {
        "execpath.staging-folder": Path("C:/Users/Robert/Launch"),
        "execpath.leonardo-save-folder": Path("D:/tmp"),
        "leonardo.output-filename": "Untitled.LDS",
    }


def make_entry(job):
    return {"job": job}


def flatten_items(checklist):
    return [item for section in checklist for item in section["items"]]


def test_layout_checklist_contains_layout_requirements():
    checklist = ui.build_preflight_checklist([make_entry("layout_sticker_to_lds")], make_config())
    titles = [section["title"] for section in checklist]
    items = flatten_items(checklist)

    assert titles == ["layout_sticker_to_lds", "always"]
    assert "Leonardo Design Studio is open on the left display" in items
    assert "Launch folder is open on the left side of the right display" in items
    assert "Launch folder is open to C:\\Users\\Robert\\Launch" in items
    assert '"Save As" in Leonardo Design Studio saves to D:\\tmp\\Untitled.LDS' in items
    assert "You will not touch the mouse or keyboard during playback." in items


def test_print_checklist_contains_print_requirements():
    checklist = ui.build_preflight_checklist([make_entry("print_lds_file")], make_config())
    titles = [section["title"] for section in checklist]
    items = flatten_items(checklist)

    assert titles == ["print_lds_file", "always"]
    assert "The printer is on." in items
    assert "The printer is loaded with paper." in items
    assert not any("Save As" in item for item in items)


def test_mixed_checklist_contains_both_job_sections_once():
    checklist = ui.build_preflight_checklist(
        [
            make_entry("layout_sticker_to_lds"),
            make_entry("print_lds_file"),
            make_entry("layout_sticker_to_lds"),
        ],
        make_config(),
    )
    titles = [section["title"] for section in checklist]

    assert titles == ["layout_sticker_to_lds", "print_lds_file", "always"]
