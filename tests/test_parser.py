import pytest

from app.services.parser_service import ParseError, parse_chapter, plain_text


def test_body_title_navigation_and_plain_text():
    parsed = parse_chapter('# 존\n\n*첫* 문단 [링크](https://example.com).\n\n둘 <!-- 비밀 --> 문단.\n\n<!-- reading-nav:start -->\n### 이동\n[다음](next.md)\n<!-- reading-nav:end -->')
    assert parsed.title == "존"
    assert [p.plain for p in parsed.paragraphs] == ["첫 문단 링크.", "둘 문단."]
    assert "*첫*" in parsed.paragraphs[0].markdown
    assert "이동" not in parsed.body
    assert parsed.paragraphs[0].line == 3


def test_unclosed_nav_is_excluded_but_original_can_be_audited():
    assert len(parse_chapter('# 제목\n\n본문.\n\n<!-- reading-nav:start -->\n링크').paragraphs) == 1


def test_literal_stars_code_quotes_lists_and_html():
    parsed = parse_chapter('# 제목\n\n> 인용 *강조*\n\n- 첫 항목\n- 둘 항목\n\n```python\na * b\n```\n\n2 * 3 = 6\n\n<script>secret()</script>\n')
    assert "인용 강조" in [p.plain for p in parsed.paragraphs]
    assert "a * b" in [p.plain for p in parsed.paragraphs]
    assert plain_text("<script>secret</script><p>보이는 글</p>") == "보이는 글"
    assert plain_text("![설명](x.png)") == "설명"


@pytest.mark.parametrize("source", ["", "# 제목\n<!-- comment -->"])
def test_invalid_body_is_not_silently_imported(source):
    with pytest.raises(ParseError):
        parse_chapter(source)
