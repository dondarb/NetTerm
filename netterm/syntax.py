"""Resaltado de sintaxis para el editor de texto.

Sustituye al motor de GtkSource (cuyos ficheros de definición de lenguaje no
están disponibles en forma binaria) con un analizador propio basado en
expresiones regulares. Soporta los lenguajes habituales en administración de
sistemas: shell, Python, C/C++, JSON, YAML, XML, Markdown, JavaScript, INI.
"""

from __future__ import annotations

import re

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402


LANGUAGES: dict[str, dict] = {
    "sh": {
        "keywords": ("if then else elif fi for while do done case esac function "
                     "return exit local export readonly declare source alias "
                     "unset trap set shift break continue in time until"),
        "types": ("echo cd pwd ls cat grep sed awk cut tail head wc sort uniq "
                  "curl wget ssh scp rsync tar gzip find xargs chmod chown "
                  "ping traceroute nc telnet mosh systemctl journalctl dnf "
                  "rpm ip ss nsdig host dig"),
        "line_comment": "#",
        "block_comment": None,
        "strings": True,
    },
    "python": {
        "keywords": ("and as assert async await break class continue def del "
                     "elif else except finally for from global if import in "
                     "is lambda nonlocal not or pass raise return try while "
                     "with yield match case"),
        "types": ("bool bytes dict float frozenset int list object set str "
                  "tuple type self None True False print len range open "
                  "enumerate zip map filter super Exception"),
        "line_comment": "#",
        "block_comment": None,
        "strings": True,
    },
    "c": {
        "keywords": ("auto break case const continue default do else enum "
                     "extern for goto if inline register restrict return "
                     "sizeof static struct switch typedef union volatile while"),
        "types": ("char double float int long short signed unsigned void "
                  "size_t uint8_t uint16_t uint32_t uint64_t FILE bool"),
        "line_comment": "//",
        "block_comment": ("/*", "*/"),
        "strings": True,
        "preproc": True,
    },
    "cpp": {
        "keywords": ("auto break case catch class const continue default delete "
                     "do else explicit export friend for goto if inline "
                     "namespace new operator private protected public return "
                     "short signed sizeof static struct switch template this "
                     "throw try typedef typename union unsigned using virtual "
                     "volatile while"),
        "types": ("bool char double float int long std string vector map "
                  "unordered_map shared_ptr unique_ptr uint8_t uint32_t void"),
        "line_comment": "//",
        "block_comment": ("/*", "*/"),
        "strings": True,
        "preproc": True,
    },
    "javascript": {
        "keywords": ("async await break case catch class const continue default "
                     "delete do else export extends finally for function if "
                     "import in instanceof let new of return static super "
                     "switch this throw try typeof var void while yield"),
        "types": ("Array Boolean Date Error Function JSON Math Number Object "
                  "Promise String console document window"),
        "line_comment": "//",
        "block_comment": ("/*", "*/"),
        "strings": True,
    },
    "json": {
        "keywords": (),
        "types": ("true false null"),
        "line_comment": None,
        "block_comment": None,
        "strings": True,
        "numbers": True,
    },
    "yaml": {
        "keywords": ("true false null yes no on off"),
        "types": (),
        "line_comment": "#",
        "block_comment": None,
        "strings": True,
    },
    "xml": {
        "keywords": (),
        "types": (),
        "line_comment": None,
        "block_comment": ("<!--", "-->"),
        "strings": True,
    },
    "markdown": {
        "keywords": (),
        "types": (),
        "line_comment": None,
        "block_comment": None,
        "strings": False,
    },
    "ini": {
        "keywords": (),
        "types": (),
        "line_comment": (";", "#"),
        "block_comment": None,
        "strings": True,
    },
    "text": {
        "keywords": (),
        "types": (),
        "line_comment": None,
        "block_comment": None,
        "strings": False,
    },
}

EXTENSION_MAP = {
    "sh": "sh", "bash": "sh", "zsh": "sh", "ksh": "sh", "conf": "ini",
    "cfg": "ini", "ini": "ini", "py": "python", "c": "c", "h": "c",
    "cpp": "cpp", "cc": "cpp", "hpp": "cpp", "js": "javascript",
    "json": "json", "yaml": "yaml", "yml": "yaml", "xml": "xml",
    "md": "markdown", "markdown": "markdown", "txt": "text", "log": "sh",
    "service": "ini", "socket": "ini", "timer": "ini", "mount": "ini",
}

# Prioridades de las etiquetas (la de mayor prioridad gana).
TAG_PRIORITY = {
    "netterm-comment": 500,
    "netterm-string": 400,
    "netterm-number": 350,
    "netterm-keyword": 300,
    "netterm-type": 280,
    "netterm-preproc": 260,
}

_tags: dict[str, Gtk.TextTag] = {}


def _tag(name: str) -> Gtk.TextTag:
    if name in _tags:
        return _tags[name]
    tag = Gtk.TextTag.new(name)
    tag.set_priority(TAG_PRIORITY.get(name, 200))
    if name == "netterm-comment":
        tag.set_property("foreground", "#5c6370")
        tag.set_property("style", Gtk.Style.ITALIC)
    elif name == "netterm-string":
        tag.set_property("foreground", "#a3be8c")
    elif name == "netterm-number":
        tag.set_property("foreground", "#d08770")
    elif name == "netterm-keyword":
        tag.set_property("foreground", "#b48ead")
        tag.set_property("weight", Pango_WEIGHT_BOLD)
    elif name == "netterm-type":
        tag.set_property("foreground", "#ebcb8b")
    elif name == "netterm-preproc":
        tag.set_property("foreground", "#8fbcbb")
    _tags[name] = tag
    return tag


from gi.repository import Pango  # noqa: E402

Pango_WEIGHT_BOLD = Pango.Weight.BOLD


def language_for_path(path: str) -> str:
    ext = path.rsplit(".", 1)[-1].lower() if "." in os.path.basename(path) else ""
    return EXTENSION_MAP.get(ext, "text")


def highlight(buffer: Gtk.TextBuffer, language: str) -> None:
    """Aplica el resaltado al contenido del buffer."""
    import os  # noqa: F401  (usado por language_for_path)

    spec = LANGUAGES.get(language)
    if not spec:
        return
    for name in TAG_PRIORITY:
        buffer.remove_tag_by_name(name, buffer.get_start_iter(),
                                 buffer.get_end_iter())
        buffer.get_tag_table().add(_tag(name))

    start = buffer.get_start_iter()
    end = buffer.get_end_iter()
    text = buffer.get_text(start, end, False)
    if not text:
        return

    lines = text.split("\n")
    offset = 0
    for line in lines:
        _highlight_line(buffer, line, offset, spec)
        offset += len(line) + 1


def _highlight_line(buffer: Gtk.TextBuffer, line: str, offset: int,
                    spec: dict) -> None:
    if not line:
        return
    length = len(line)

    def apply(tag_name: str, start: int, end: int) -> None:
        if end <= start:
            return
        s = buffer.get_iter_at_offset(offset + start)
        e = buffer.get_iter_at_offset(offset + end)
        buffer.apply_tag(_tag(tag_name), s, e)

    # 1) Comentarios de línea
    line_comment = spec.get("line_comment")
    if line_comment:
        for marker in ([line_comment] if isinstance(line_comment, str)
                       else list(line_comment)):
            idx = line.find(marker)
            if idx >= 0:
                apply("netterm-comment", idx, length)
                return

    # 2) Comentarios de bloque (solo si abren y cierran en la misma línea)
    block = spec.get("block_comment")
    if block:
        start_marker, end_marker = block
        s_idx = line.find(start_marker)
        e_idx = line.find(end_marker, s_idx + len(start_marker)) if s_idx >= 0 else -1
        if s_idx >= 0 and e_idx > s_idx:
            apply("netterm-comment", s_idx, e_idx + len(end_marker))

    # 3) Cadenas
    if spec.get("strings"):
        for m in re.finditer(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'', line):
            apply("netterm-string", m.start(), m.end())

    # 4) Números
    if spec.get("numbers", True):
        for m in re.finditer(r"\b\d+(\.\d+)?\b", line):
            apply("netterm-number", m.start(), m.end())

    # 5) Directivas de preprocesador
    if spec.get("preproc") and line.lstrip().startswith("#"):
        apply("netterm-preproc", 0, length)
        return

    # 6) Palabras clave y tipos
    keywords = set(spec.get("keywords", ()))
    types = set(spec.get("types", ()))
    for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", line):
        word = m.group(0)
        if word in keywords:
            apply("netterm-keyword", m.start(), m.end())
        elif word in types:
            apply("netterm-type", m.start(), m.end())
