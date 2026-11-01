"""Minimal reader/writer for KiCad s-expression files.

Unquoted tokens (keywords, numbers) are returned as :class:`Sym`, quoted
strings as plain ``str``, lists as ``list``. Numbers stay raw text so a
round trip never reformats them.
"""

from __future__ import annotations

_ESCAPES_IN = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"'}


_OPEN, _CLOSE = object(), object()


class Sym(str):
    """An unquoted token."""

    __slots__ = ()

    def __repr__(self) -> str:
        return f"Sym({str.__repr__(self)})"


def _tokens(text: str):
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c in "()":
            yield _OPEN if c == "(" else _CLOSE
            i += 1
        elif c == '"':
            i += 1
            buf = []
            while True:
                if i >= n:
                    raise ValueError("unterminated string")
                c = text[i]
                if c == "\\" and i + 1 < n:
                    buf.append(_ESCAPES_IN.get(text[i + 1], text[i + 1]))
                    i += 2
                elif c == '"':
                    i += 1
                    break
                else:
                    buf.append(c)
                    i += 1
            yield "".join(buf)  # plain str marks a quoted string
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n()"':
                j += 1
            yield Sym(text[i:j])
            i = j


def parse(text: str) -> list:
    """Parse exactly one top-level expression."""
    stack: list[list] = []
    result = None
    for tok in _tokens(text):
        if tok is _OPEN:
            if result is not None:
                raise ValueError("more than one top-level expression")
            stack.append([])
        elif tok is _CLOSE:
            if not stack:
                raise ValueError("unbalanced ')'")
            done = stack.pop()
            if stack:
                stack[-1].append(done)
            else:
                result = done
        else:
            if not stack:
                raise ValueError("atom outside of a list")
            stack[-1].append(tok)
    if stack or result is None:
        raise ValueError("unbalanced '(' or empty input")
    return result


def _atom(a) -> str:
    if isinstance(a, Sym):
        return str(a)
    s = str(a).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{s}"'


def _dump(e: list, depth: int, out: list[str]) -> None:
    ind = "\t" * depth
    if all(not isinstance(c, list) for c in e):
        out.append(ind + "(" + " ".join(_atom(c) for c in e) + ")")
        return
    k = 0
    while k < len(e) and not isinstance(e[k], list):
        k += 1
    out.append(ind + "(" + " ".join(_atom(c) for c in e[:k]))
    for c in e[k:]:
        if isinstance(c, list):
            _dump(c, depth + 1, out)
        else:
            out.append("\t" * (depth + 1) + _atom(c))
    out.append(ind + ")")


def dumps(expr: list) -> str:
    """Serialise in KiCad's layout (tabs, one child list per line)."""
    out: list[str] = []
    _dump(expr, 0, out)
    return "\n".join(out) + "\n"


def find(expr: list, head: str) -> list | None:
    for c in expr:
        if isinstance(c, list) and c and c[0] == head:
            return c
    return None


def find_all(expr: list, head: str) -> list[list]:
    return [c for c in expr if isinstance(c, list) and c and c[0] == head]
