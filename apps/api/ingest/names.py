import re

MAX_IDENTIFIER_LENGTH = 60


def sanitize_identifier(name: str, taken: set[str], fallback: str = "col") -> str:
    """Make a safe, unique, lower-case SQL identifier and add it to `taken`.

    Output only contains [a-z0-9_], never starts with a digit or underscore.
    """
    ident = re.sub(r"[^0-9a-zA-Z]+", "_", name.strip()).strip("_").lower() or fallback
    if ident[0].isdigit():
        ident = f"{fallback}_{ident}"
    ident = ident[:MAX_IDENTIFIER_LENGTH]

    candidate, n = ident, 2
    while candidate in taken:
        candidate = f"{ident}_{n}"
        n += 1
    taken.add(candidate)
    return candidate


def quote(identifier: str) -> str:
    """Quote an identifier for DuckDB SQL."""
    return '"' + identifier.replace('"', '""') + '"'
