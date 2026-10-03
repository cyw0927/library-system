import re
from dataclasses import dataclass
from html.parser import HTMLParser

from markdown_it import MarkdownIt

MARKDOWN = MarkdownIt("commonmark", {"html": True}).enable("table")
START = "<!-- reading-nav:start -->"
END = "<!-- reading-nav:end -->"


class ParseError(ValueError):
    pass


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"br", "p", "li", "tr", "pre", "blockquote"}:
            self.parts.append("\n")
        if tag == "img":
            self.parts.append(dict(attrs).get("alt", ""))

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "li", "td", "th", "tr", "pre", "blockquote"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def without_navigation(markdown: str) -> str:
    # An unclosed navigation block is excluded too; QA reports its malformed marker.
    return re.sub(r"<!--\s*reading-nav:start\s*-->.*?(?:<!--\s*reading-nav:end\s*-->|\Z)",
                  "", markdown, flags=re.S | re.I)


def plain_text(markdown: str) -> str:
    parser = TextExtractor()
    parser.feed(MARKDOWN.render(without_navigation(markdown)))
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()


@dataclass(frozen=True)
class ParsedParagraph:
    markdown: str
    plain: str
    line: int


@dataclass(frozen=True)
class ParsedChapter:
    title: str | None
    body: str
    paragraphs: list[ParsedParagraph]


def parse_chapter(source: str) -> ParsedChapter:
    if not source.strip():
        raise ParseError("Empty Markdown file")
    cleaned = without_navigation(source.replace("\r\n", "\n"))
    tokens = MARKDOWN.parse(cleaned)
    lines = cleaned.splitlines()
    heading = next((t for t in tokens if t.type == "heading_open" and t.tag == "h1"), None)
    title = plain_text("\n".join(lines[heading.map[0]:heading.map[1]])) if heading else None
    paragraphs = []
    table_end = -1
    for token in tokens:
        if not token.map or token.map[0] < table_end:
            continue
        if token.type not in {"paragraph_open", "fence", "code_block", "table_open"}:
            continue
        start, end = token.map
        md = "\n".join(lines[start:end])
        text = plain_text(md)
        if text:
            paragraphs.append(ParsedParagraph(md, text, start + 1))
        if token.type == "table_open":
            table_end = end
    if not paragraphs:
        raise ParseError("Markdown has no body paragraphs")
    if heading:
        start, end = heading.map
        lines = lines[:start] + lines[end:]
    return ParsedChapter(title, "\n".join(lines).strip(), paragraphs)
