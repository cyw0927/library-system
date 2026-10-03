import pytest

from app.services.metadata_service import map_path, natural_key, readme_metadata


@pytest.mark.parametrize("path,volume,number,pov", [
    ("Novel/chapter_01.md", None, 1, None),
    ("Novel/05_Volume/01_001-010/045_Jon_09.md", "Novel/05_Volume", 45, "Jon"),
    ("Novel/05_Volume/046_The_Blind_Girl.md", "Novel/05_Volume", 46, None),
    ("Novel/01_Tome/02_Part/003_T1P2_Ch01.md", "Novel/01_Tome", 3, None),
    ("NewBook/01_001-010/001_PREFACE.md", None, 1, None),
])
def test_generic_paths(path, volume, number, pov):
    mapped = map_path(path)
    assert (mapped.volume_path, mapped.number, mapped.pov) == (volume, number, pov)


def test_natural_sort_and_readme_metadata():
    assert sorted(["Book/10_V/x", "Book/2_V/x"], key=natural_key)[0] == "Book/2_V/x"
    metadata = readme_metadata('# 작품\n\n- 원작: 작가, *Original*\n\n## 진행\n- 전체: **139 / 365장 번역 진행 중**', "Novel")
    assert metadata["title"] == "작품"
    assert metadata["author"] == "작가"
    assert metadata["expected_chapters"] == 365
    assert metadata["status"] == "in_progress"


def test_unknown_totals_are_not_fabricated():
    assert readme_metadata("# 진행 중", "New_Novel")["expected_chapters"] is None
