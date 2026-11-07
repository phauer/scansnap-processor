"""Tests for the photo folder → markdown feature (no real OCR, made-up text)."""

import numpy as np
import pytest
from PIL import Image

import photos_to_md
from scansnap_ocr import photos
from scansnap_ocr.photos import (
    Line,
    Table,
    build_markdown,
    find_tables,
    find_toc_pages,
    heading_level,
    list_photos,
    load_image,
    reflow,
    render_toc,
)


def L(text, top, left=0, right=500, h=20):
    return Line(text, left, right, top, top + h)


def page(*texts, start=0, step=24):
    return [L(t, start + i * step) for i, t in enumerate(texts)]


class TestListPhotos:
    def test_sorted_filtered(self, tmp_path):
        for n in ["IMG_2.HEIC", "img_1.jpg", "IMG_3.PNG", "notes.txt", "doc.pdf", ".hidden.jpg"]:
            (tmp_path / n).write_bytes(b"x")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "IMG_0.jpg").write_bytes(b"x")
        assert [p.name for p in list_photos(tmp_path)] == ["img_1.jpg", "IMG_2.HEIC", "IMG_3.PNG"]

    def test_empty(self, tmp_path):
        assert list_photos(tmp_path) == []


class TestReflow:
    def test_joins_lines_and_hyphenation(self):
        out = reflow([page("Die Ver-", "sicherung gilt für", "alle Kinder.")])
        assert out == "Die Versicherung gilt für alle Kinder."

    def test_keeps_hyphen_before_und(self):
        assert "Be- und Entladen" in reflow([page("Das Be-", "und Entladen geht.")])

    def test_keeps_hyphen_before_capital(self):
        assert "Ab-Bau" in reflow([page("Der Ab-", "Bau läuft.")])

    def test_paragraph_break_on_gap(self):
        lines = [L("Erster Absatz.", 0), L("Zweiter Absatz.", 80)]
        assert reflow([lines]) == "Erster Absatz.\n\nZweiter Absatz."

    def test_page_numbers_dropped(self):
        out = reflow([page("12", "Text eins", "13"), page("Text zwei")])
        assert "12" not in out and "13" not in out

    def test_running_header_dropped(self):
        pages = [page(f"Kapitel Eins {i}", "Inhalt A.", "Mehr B.") for i in range(3)]
        out = reflow(pages)
        assert "Kapitel" not in out and "Inhalt A." in out

    def test_running_header_variants_dropped_but_chapter_heading_kept(self):
        h = "3 Musterkapitel"
        pages = [
            [L(h, 0), L("Eröffnung des Kapitels.", 40)],  # real heading (plain, first)
            [L(f"36 | {h}", 0), L("Text A.", 40)],
            [L(f"| {h}", 0), L("Text B.", 40)],
            [L(f"42 {h}", 0), L("Text C.", 40)],
            [L(h, 0), L("Text D.", 40)],  # header whose page number the OCR lost
            [L(f"{h} | 47", 0), L("Text E.", 40)],
        ]
        out = reflow(pages)
        assert out.count("Musterkapitel") == 1 and out.startswith("## 3 Musterkapitel")
        for t in "ABCDE":
            assert f"Text {t}." in out

    def test_paragraph_continues_across_pages(self):
        out = reflow([page("Der Satz geht", "noch weiter"), page("und endet hier.")])
        assert out == "Der Satz geht noch weiter und endet hier."

    def test_no_merge_after_sentence_end(self):
        out = reflow([page("Fertig."), page("und klein.")])
        assert out == "Fertig.\n\nund klein."

    def test_empty(self):
        assert reflow([]) == ""
        assert reflow([[]]) == ""


class TestHeadings:
    @pytest.mark.parametrize("text,level", [
        ("3 Musterkapitel", 2), ("3.18 Muster gründen", 3), ("3.1.2 Unterpunkt Eins", 4),
        ("2.1.1 Gibt es einen Musteranspruch?", None),  # question mark: sentence end
        ("3.19 Musterthema annehmen 55", None),  # TOC entry with page number
        ("2.2.1 Musterregelung ...", None),  # dot leader
        ("4.10 Hochzeit auf die letzten Tage? ...•", None), ("5.2 Musterregelung •", None),
        ("1. Auflage", None), ("2025 Muster GmbH", None), ("80.000 Euro Betrag", None),
        ("3 kleine Zahl", None), ("Vorwort", None),
    ])
    def test_heading_level(self, text, level):
        assert heading_level(text) == level

    def test_headings_rendered_and_split_paragraphs(self):
        out = reflow([page("Davor steht Text.", "3.18 Muster gründen", "Danach geht es weiter.")])
        assert out == "Davor steht Text.\n\n### 3.18 Muster gründen\n\nDanach geht es weiter."

    def test_heading_does_not_pull_previous_page_paragraph(self):
        out = reflow([page("Offener Satz ohne Ende"), page("3.1 Neuer Abschnitt", "klein weiter")])
        assert out == "Offener Satz ohne Ende\n\n### 3.1 Neuer Abschnitt\n\nklein weiter"

    def test_pipe_running_header_dropped(self):
        out = reflow([page("52 | 3 Musterkapitel", "Text."), page("Mehr | 53")])
        assert "Musterkapitel" not in out and "53" not in out and "Text." in out


def toc_page(*rows, right=2000):
    """rows: (text, left) tuples laid out top to bottom."""
    return [Line(t, left, right, i * 60, i * 60 + 40) for i, (t, left) in enumerate(rows)]


class TestToc:
    def test_render_nested_without_page_numbers(self):
        pg = toc_page(
            ("Inhaltsverzeichnis", 400), ("Vorwort 9", 400), ("2 Allgemeines .. 13", 400),
            ("2.1 Anspruch 13", 400), ("2.1.1 Gibt es das? 13", 500), ("2.2.1 Regel ...", 500),
        )
        assert render_toc([pg]) == (
            "- Vorwort\n- 2 Allgemeines\n  - 2.1 Anspruch\n    - 2.1.1 Gibt es das?"
            "\n    - 2.2.1 Regel"
        )

    def test_margin_tab_numbers_and_detached_page_numbers_dropped(self):
        pg = toc_page(
            ("3.20 Beispiele 56 4.5", 350), ("57", 1900), ("4 Fälle 57", 350), ("4.6", 1990),
            ("4.1 Rente?", 350), ("4.1.5 Ideen 59 4.7", 450),
        )
        assert render_toc([pg]) == "  - 3.20 Beispiele\n- 4 Fälle\n  - 4.1 Rente?\n    - 4.1.5 Ideen"

    def test_orphan_numbering_assigned_to_unnumbered_entries(self):
        pg = toc_page(
            ("4.9.3 Geschichte 131", 400), ("Wichtige Fakten 132", 500), ("4.9.4", 375),
            ("Meine Ideen 132", 500), ("4.9.5", 375),
        )
        assert render_toc([pg]) == (
            "    - 4.9.3 Geschichte\n    - 4.9.4 Wichtige Fakten\n    - 4.9.5 Meine Ideen"
        )

    def test_wrong_number_replaced_by_fitting_orphan(self):
        pg = toc_page(
            ("4.9.5 Meine Ideen 132", 500), ("Die Planung 132", 500),
            ("4.9.6 Die Berechnung 133", 500), ("4.9.7", 375), ("4.9.8 Anmerkungen 134", 500),
        )
        out = render_toc([pg])
        assert "4.9.6 Die Planung" in out  # inferred: the next entry confirms the sequence
        assert "4.9.7 Die Berechnung" in out and "4.9.8 Anmerkungen" in out

    def test_unnumbered_trailing_entries_stay_plain(self):
        pg = toc_page(("5.9 Musterkonto 200", 400), ("Schlusswort 210", 400),
                      ("Stichwortverzeichnis 220", 400))
        assert render_toc([pg]) == "  - 5.9 Musterkonto\n- Schlusswort\n- Stichwortverzeichnis"

    def test_orphan_with_page_number_is_not_a_title(self):
        pg = toc_page(("4.9.6 Planung 130", 500), ("4.9.7 132", 375), ("Berechnung 133", 500))
        assert render_toc([pg]) == "    - 4.9.6 Planung\n    - 4.9.7 Berechnung"

    def test_chapter_number_orphan_on_left_but_not_page_numbers(self):
        pg = toc_page(
            ("3.20 Beispiele 56", 350), ("Zehn Fälle 57", 350), ("4", 353), ("57", 1900),
            ("4.1 Rente 57", 350),
        )
        out = render_toc([pg])
        assert out == "  - 3.20 Beispiele\n- 4 Zehn Fälle\n  - 4.1 Rente"

    def test_running_header_with_slash_dropped(self):
        pg = toc_page(("8 / Inhaltsverzeichnis", 400), ("1 Einleitung 11", 400))
        assert render_toc([pg]) == "- 1 Einleitung"

    def test_find_toc_pages_stops_at_prose(self):
        toc = toc_page(("Inhaltsverzeichnis", 400), ("1 Einleitung 11", 400))
        more = toc_page(("2 Mehr 13", 400), ("14", 1900), ("2.1 Noch 14", 400))
        prose = page("Das ist ein langer Fließtext", "ohne Seitenzahlen am Ende")
        assert find_toc_pages([page("Titel"), toc, more, prose]) == [1, 2]

    def test_no_toc(self):
        assert find_toc_pages([page("Nur Text")]) == []

    def test_reflow_renders_toc_between_text(self):
        toc = toc_page(("6 Inhaltsverzeichnis", 400), ("1 Einleitung 11", 400))
        out = reflow([page("Vorspann Text."), toc, page("Danach Text.")])
        assert out == "Vorspann Text.\n\n## Inhaltsverzeichnis\n\n- 1 Einleitung\n\nDanach Text."


def trow(top, *cells, h=40):
    """A table row: cells are (text, left, right); the row text joins them."""
    boxes = [Line(t, left, right, top, top + h) for t, left, right in cells]
    if len(boxes) == 1:
        return boxes[0]
    return Line(" ".join(b.text for b in boxes), boxes[0].left, boxes[-1].right, top, top + h,
                cells=boxes)


L0, L1, L2 = (100, 500), (700, 900), (1000, 1200)  # label / value columns (x-ranges)


def basic_table(top=0):
    return [
        trow(top, ("Jahr A", 720, 880), ("Jahr B", 1020, 1180)),
        trow(top + 60, ("Betrag", *L0), ("80.000 €", 760, 900), ("90.000 €", 1060, 1200)),
        trow(top + 120, ("Steuer", *L0), ("3.180 €", 780, 900), ("14.330 €", 1060, 1200)),
    ]


class TestTables:
    def test_basic_table_with_header_and_right_aligned_numbers(self):
        [t] = find_tables(basic_table())
        assert isinstance(t, Table)
        assert t.render() == (
            "|  | Jahr A | Jahr B |\n| --- | ---: | ---: |\n"
            "| Betrag | 80.000 € | 90.000 € |\n| Steuer | 3.180 € | 14.330 € |"
        )

    def test_stacked_header_rows_are_merged(self):
        rows = [
            trow(0, ("Jahr 2025", 720, 880), ("Jahr 2025", 1020, 1180)),
            trow(50, ("ohne", 760, 840), ("mit", 1060, 1140)),
            trow(110, ("Betrag", *L0), ("1 €", 860, 900), ("2 €", 1160, 1200)),
        ]
        [t] = find_tables(rows)
        assert t.header == ["", "Jahr 2025 ohne", "Jahr 2025 mit"]

    def test_wrapped_label_joins_previous_row(self):
        rows = basic_table() + [
            trow(180, ("Steuer und", *L0), ("1 €", 860, 900), ("2 €", 1160, 1200)),
            trow(225, ("Zuschlag", 100, 300)),
        ]
        [t] = find_tables(rows)
        assert t.rows[-1][0] == "Steuer und Zuschlag"

    def test_split_row_is_rejoined(self):
        rows = basic_table() + [
            trow(180, ("Summe", *L0), ("1 €", 860, 900)),
            trow(200, ("2 €", 1160, 1200)),  # drifted cell of the same row
        ]
        # a lone numeric box below a table row is attached to its column by overlap
        [t] = find_tables(rows)
        assert t.rows[-1][2] == "2 €"

    def test_complementary_rows_are_merged(self):
        rows = basic_table() + [
            trow(180, ("Summe", *L0), ("1 €", 860, 900)),
            trow(215, ("x", 100, 150), ("2 €", 1160, 1200)),
        ]
        [t] = find_tables(rows)
        assert [r[1:] for r in t.rows][-1] == ["1 €", "2 €"]

    def test_prose_two_column_layout_is_not_a_table(self):
        long = "Dies ist ein langer Satz aus einer Spalte eines Fließtexts"
        rows = [trow(i * 60, (long, 100, 900), (long, 1000, 1800)) for i in range(4)]
        assert find_tables(rows) == rows

    def test_text_only_rows_are_not_a_table(self):
        rows = [trow(i * 60, ("Print: ISBN", 100, 400), ("Bestell-Nr.", 600, 900)) for i in range(3)]
        assert find_tables(rows) == rows

    def test_single_row_is_not_a_table(self):
        rows = [trow(0, ("A", 100, 200), ("1 €", 600, 700)), page("Text")[0]]
        assert find_tables(rows) == rows

    def test_table_ends_before_far_apart_prose(self):
        rows = basic_table() + [trow(500, ("Ein ganz normaler Absatz.", 100, 900))]
        segs = find_tables(rows)
        assert isinstance(segs[0], Table) and segs[1].text == "Ein ganz normaler Absatz."

    def test_pipe_escaped(self):
        t = Table(["a|b"], [["c|d"]], [False])
        assert t.render() == "| a\\|b |\n| --- |\n| c\\|d |"

    def test_reflow_table_between_paragraphs(self):
        lines = [L("Davor Text.", -100, right=900), *basic_table(), L("Danach Text.", 400, right=900)]
        out = reflow([lines])
        assert out.startswith("Davor Text.\n\n|  | Jahr A | Jahr B |")
        assert out.endswith("| 14.330 € |\n\nDanach Text.")

    def test_no_tables_flag_keeps_text_rows(self):
        out = reflow([basic_table()], tables=False)
        assert "|" not in out and "Betrag 80.000 € 90.000 €" in out

    def test_table_continues_on_next_photo(self):
        cont = [
            trow(0, ("Zins", *L0), ("5 €", 860, 900), ("6 €", 1160, 1200)),
            trow(60, ("Miete", *L0), ("7 €", 860, 900), ("8 €", 1160, 1200)),
        ]
        out = reflow([basic_table(), cont])
        assert out.count("| --- |") == 1 and "| Miete | 7 € | 8 € |" in out

    def test_table_with_header_on_next_photo_is_a_new_table(self):
        out = reflow([basic_table(), basic_table()])
        assert out.count("| --- |") == 2

    def test_order_lines_keeps_cells(self):
        a, b = L("links", 0, left=0, right=100), L("rechts", 2, left=300, right=400)
        [row] = photos.order_lines([b, a])
        assert [c.text for c in row.cells] == ["links", "rechts"]

    def test_numbered_page_header_with_page_number_dropped(self):
        header = trow(0, ("3.6 Musterthema: Vom Beispiel", 100, 700), ("39", 1500, 1550))
        out = reflow([[header, *basic_table(100)]])
        assert "Arbeitslosengeld" not in out


class TestBuildMarkdown:
    def test_raw_sections(self):
        md = build_markdown("Titel", ["a.heic"], [page("Zeile 1", "Zeile 2")], raw=True)
        assert md == "# Titel\n\n## a.heic\n\nZeile 1\nZeile 2\n"

    def test_reflowed(self):
        assert build_markdown("T", ["a"], [page("Hallo Welt.")]) == "# T\n\nHallo Welt.\n"


class TestOrderLines:
    def test_same_row_merged_left_to_right(self):
        a, b = L("rechts", 0, left=300, right=400), L("links", 2, left=0, right=100)
        [row] = photos.order_lines([a, b])
        assert row.text == "links rechts"


class TestLoadImage:
    def test_exif_rotation_and_downscale(self, tmp_path):
        img = Image.new("RGB", (400, 200), "white")
        exif = Image.Exif()
        exif[0x0112] = 6  # rotate 90° CW on display
        path = tmp_path / "a.jpg"
        img.save(path, exif=exif)
        arr = load_image(path, max_edge=100)
        assert arr.shape == (100, 50, 3)

    def test_heic_roundtrip(self, tmp_path):
        pillow_heif = pytest.importorskip("pillow_heif")
        pillow_heif.register_heif_opener()
        path = tmp_path / "a.heic"
        Image.new("RGB", (64, 32), "white").save(path)
        assert load_image(path).shape == (32, 64, 3)


class FakeEngine:
    name = "fake"

    def __init__(self, text_when):
        self.text_when = text_when
        self.calls = 0

    def recognize(self, image):
        self.calls += 1
        if self.text_when(image):
            return [([[0, 0], [100, 0], [100, 20], [0, 20]], "x" * 50, 0.9)]
        return []


class TestOcrPhoto:
    def test_rotation_retry(self, monkeypatch):
        img = np.zeros((10, 20, 3), dtype=np.uint8)
        eng = FakeEngine(lambda a: a.shape[0] == 20)  # only the 90°-rotated image "has text"
        monkeypatch.setattr(photos, "get_engine", lambda: eng)
        lines = photos.ocr_photo(img)
        assert lines and eng.calls == 2

    def test_no_retry_when_text_found(self, monkeypatch):
        eng = FakeEngine(lambda a: True)
        monkeypatch.setattr(photos, "get_engine", lambda: eng)
        photos.ocr_photo(np.zeros((10, 20, 3), dtype=np.uint8))
        assert eng.calls == 1


class TestCli:
    def _patch(self, monkeypatch, fail=()):
        def fake_ocr(image):
            return [L("Hallo Welt.", 0)]

        def fake_load(path):
            if path.name in fail:
                raise ValueError("broken")
            return np.zeros((2, 2, 3), dtype=np.uint8)

        monkeypatch.setattr(photos_to_md, "ocr_photo", fake_ocr)
        monkeypatch.setattr(photos_to_md, "load_image", fake_load)

    def test_missing_folder(self, tmp_path):
        assert photos_to_md.main([str(tmp_path / "nope")]) == 1

    def test_empty_folder(self, tmp_path):
        assert photos_to_md.main([str(tmp_path)]) == 1

    def test_default_output(self, tmp_path, monkeypatch):
        self._patch(monkeypatch)
        folder = tmp_path / "buch"
        folder.mkdir()
        (folder / "a.heic").write_bytes(b"x")
        assert photos_to_md.main([str(folder)]) == 0
        assert (folder / "buch.md").read_text() == "# buch\n\nHallo Welt.\n"

    def test_output_and_raw(self, tmp_path, monkeypatch):
        self._patch(monkeypatch)
        (tmp_path / "a.jpg").write_bytes(b"x")
        out = tmp_path / "o.md"
        assert photos_to_md.main([str(tmp_path), "-o", str(out), "--raw"]) == 0
        assert "## a.jpg" in out.read_text()

    def test_failure_continues_and_exits_1(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, fail={"a.jpg"})
        (tmp_path / "a.jpg").write_bytes(b"x")
        (tmp_path / "b.jpg").write_bytes(b"x")
        out = tmp_path / "o.md"
        assert photos_to_md.main([str(tmp_path), "-o", str(out)]) == 1
        assert "Hallo Welt." in out.read_text()


@pytest.mark.ocr
def test_end_to_end_ocr(tmp_path):
    from PIL import ImageDraw, ImageFont

    img = Image.new("RGB", (1200, 300), "white")
    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 60)
    ImageDraw.Draw(img).text((40, 100), "Musterstadt Hausnummer", fill="black", font=font)
    path = tmp_path / "t.png"
    img.save(path)
    text = " ".join(ln.text for ln in photos.ocr_photo(load_image(path)))
    assert "Musterstadt" in text
