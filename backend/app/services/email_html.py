from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse


ALLOWED_TAGS = {
    "a",
    "b",
    "blockquote",
    "br",
    "div",
    "em",
    "h1",
    "h2",
    "h3",
    "i",
    "li",
    "ol",
    "p",
    "s",
    "span",
    "strong",
    "u",
    "ul",
}
VOID_TAGS = {"br"}


def safe_link(value: str) -> str | None:
    candidate = value.strip()
    parsed = urlparse(candidate)
    if parsed.scheme.casefold() not in {"http", "https", "mailto"}:
        return None
    return candidate


class RichTextSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag not in ALLOWED_TAGS:
            return
        rendered_attrs = ""
        if tag == "a":
            href = next((value for name, value in attrs if name.casefold() == "href" and value), None)
            checked_href = safe_link(href) if href else None
            if checked_href:
                rendered_attrs = (
                    f' href="{escape(checked_href, quote=True)}"'
                    ' target="_blank" rel="noopener noreferrer"'
                )
        self.parts.append(f"<{tag}{rendered_attrs}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in ALLOWED_TAGS and tag not in VOID_TAGS:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.parts.append(escape(data))
        self.text_parts.append(data)

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")
        self.text_parts.append(" ")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")
        self.text_parts.append(" ")


def sanitize_rich_text(value: str) -> tuple[str, str]:
    parser = RichTextSanitizer()
    parser.feed(value)
    parser.close()
    return "".join(parser.parts).strip(), "".join(parser.text_parts).strip()
