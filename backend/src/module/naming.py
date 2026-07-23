"""Custom naming templates for media folders and files."""

from dataclasses import dataclass
from re import Match
from re import compile as compile_regex

_FIELDS = frozenset({"title", "season", "episode", "year", "group", "hash"})
_NUMERIC_FIELDS = frozenset({"season", "episode"})
_PLACEHOLDER_RE = compile_regex(r"\{([^{}]*)\}")
_ILLEGAL_PATH_CHARS_RE = compile_regex(r'[<>:"/\\|?*\x00-\x1f]')


class NamingTemplateError(ValueError):
    """Raised when a custom naming template uses unsupported syntax."""


@dataclass(frozen=True, slots=True)
class NamingContext:
    """Values available to a custom naming template."""

    title: str
    season: int | None = None
    episode: int | float | None = None
    year: str | int | None = None
    group: str | None = None
    torrent_hash: str | None = None


def _parse_placeholder(content: str) -> tuple[str, str | None]:
    parts = content.split(":", maxsplit=1)
    field = parts[0]
    modifier = parts[1] if len(parts) == 2 else None
    if field not in _FIELDS:
        raise NamingTemplateError(f"Unknown template field: {field or content}")
    if modifier is None:
        return field, None
    if modifier == "02":
        if field not in _NUMERIC_FIELDS:
            raise NamingTemplateError(f"{field} does not support the 02 format")
        return field, modifier
    if len(modifier) == 2:
        return field, modifier
    raise NamingTemplateError(f"Unsupported template placeholder: {content}")


def _validate_template(template: str) -> None:
    cursor = 0
    for match in _PLACEHOLDER_RE.finditer(template):
        if (
            "{" in template[cursor : match.start()]
            or "}" in template[cursor : match.start()]
        ):
            raise NamingTemplateError("Unmatched brace in template")
        _parse_placeholder(match.group(1))
        cursor = match.end()
    if "{" in template[cursor:] or "}" in template[cursor:]:
        raise NamingTemplateError("Unmatched brace in template")


def validate_custom_template(template: str, *, allow_path: bool = False) -> str:
    """Validate template syntax and whether it may contain path separators."""

    if not template.strip():
        raise NamingTemplateError("Template must not be empty")
    _validate_template(template)
    normalized = template.replace("\\", "/")
    if not allow_path and "/" in normalized:
        raise NamingTemplateError("File template must not contain path separators")
    if allow_path:
        if normalized.startswith("/") or compile_regex(r"^[A-Za-z]:").match(normalized):
            raise NamingTemplateError("Folder template must be relative")
        literal_parts = _PLACEHOLDER_RE.sub("value", normalized).split("/")
        if any(part in {"", ".", ".."} for part in literal_parts):
            raise NamingTemplateError("Folder template contains an unsafe path segment")
    return template


def custom_template_fields(template: str) -> tuple[str, ...]:
    """Return referenced fields once, preserving their template order."""

    validate_custom_template(template)
    return tuple(
        dict.fromkeys(
            _parse_placeholder(match.group(1))[0]
            for match in _PLACEHOLDER_RE.finditer(template)
        )
    )


def _safe_value(value: object | None) -> object | None:
    if not isinstance(value, str):
        return value
    cleaned = _ILLEGAL_PATH_CHARS_RE.sub(" ", value)
    cleaned = " ".join(cleaned.split()).rstrip(". ")
    return cleaned or None


def _safe_fragment(value: str) -> str:
    cleaned = _ILLEGAL_PATH_CHARS_RE.sub(" ", value)
    return " ".join(cleaned.split()).strip().rstrip(". ")


def render_custom_name(
    template: str,
    context: NamingContext,
    *,
    suffix: str = "",
    allow_path: bool = False,
) -> str:
    """Render and validate a custom naming template."""

    validate_custom_template(template, allow_path=allow_path)

    values = {
        "title": _safe_value(context.title),
        "season": context.season,
        "episode": context.episode,
        "year": _safe_value(context.year),
        "group": _safe_value(context.group),
        "hash": context.torrent_hash[:6] if context.torrent_hash else None,
    }

    def replace(match: Match[str]) -> str:
        field, modifier = _parse_placeholder(match.group(1))
        value = values[field]
        if value is None:
            return ""
        if modifier == "02":
            return f"{value:02}"
        if modifier:
            return f"{modifier[0]}{value}{modifier[1]}"
        return str(value)

    rendered = " ".join(_PLACEHOLDER_RE.sub(replace, template).split())
    if allow_path:
        raw_parts = rendered.replace("\\", "/").split("/")
        if any(part.strip() in {".", ".."} for part in raw_parts):
            raise NamingTemplateError("Folder template must render a relative path")
        parts = [part for part in map(_safe_fragment, raw_parts) if part]
        rendered = "/".join(parts)
    else:
        rendered = _safe_fragment(rendered)
    if not rendered:
        raise NamingTemplateError("Template rendered an empty name")
    return f"{rendered}{suffix}"
