"""Package filter: the subset of aptly query syntax that package configs use.

    expr   := term ('|' term)*
    term   := factor (',' factor)*
    factor := '(' expr ')' | field '(' op value ')' | name
    field  := Name | $Name | Version | $Version | $Architecture | Architecture
    op     := % (glob) | = | << | <= | < | >> | >= | >

As in aptly, '<' means '<=' and '>' means '>='. A bare name matches the
package name exactly.
"""

import fnmatch
import re

from . import debver

_TOKEN = re.compile(r"\s*(\(|\)|\||,|[^\s(),|]+)")
_COND = re.compile(r"\s*(%|<<|<=|<|>>|>=|>|=)\s*(.*?)\s*$")
_FIELDS = {
    "name": "Package",
    "$name": "Package",
    "package": "Package",
    "version": "Version",
    "$version": "Version",
    "architecture": "Architecture",
    "$architecture": "Architecture",
}


class QueryError(ValueError):
    pass


def _tokens(text):
    pos, out = 0, []
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        m = _TOKEN.match(text, pos)
        if not m:
            raise QueryError(f"bad query near: {text[pos:]!r}")
        out.append(m.group(1))
        pos = m.end()
    return out


def _version_ok(op, have, want):
    c = debver.compare(have, want)
    return {
        "=": c == 0,
        "<<": c < 0,
        "<=": c <= 0,
        "<": c <= 0,
        ">>": c > 0,
        ">=": c >= 0,
        ">": c >= 0,
    }[op]


class _Parser:
    def __init__(self, text):
        self.text = text
        self.toks = _tokens(text)
        self.i = 0

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self, want=None):
        tok = self.peek()
        if tok is None or (want and tok != want):
            raise QueryError(f"expected {want or 'token'} in {self.text!r}")
        self.i += 1
        return tok

    def parse(self):
        node = self.expr()
        if self.peek() is not None:
            raise QueryError(f"trailing input in {self.text!r}")
        return node

    def expr(self):
        nodes = [self.term()]
        while self.peek() == "|":
            self.take("|")
            nodes.append(self.term())
        return ("or", nodes) if len(nodes) > 1 else nodes[0]

    def term(self):
        nodes = [self.factor()]
        while self.peek() == ",":
            self.take(",")
            nodes.append(self.factor())
        return ("and", nodes) if len(nodes) > 1 else nodes[0]

    def factor(self):
        tok = self.peek()
        if tok == "(":
            self.take("(")
            node = self.expr()
            self.take(")")
            return node
        word = self.take()
        if self.peek() == "(" and word.lower() in _FIELDS:
            # Field condition: collect the raw text up to the matching ')'.
            self.take("(")
            raw = []
            while self.peek() != ")":
                raw.append(self.take())
            self.take(")")
            m = _COND.match(" ".join(raw))
            if not m:
                raise QueryError(f"bad condition {word}({' '.join(raw)})")
            return ("cond", _FIELDS[word.lower()], m.group(1), m.group(2).replace(" ", ""))
        return ("cond", "Package", "=", word)


def compile_query(text):
    """Return a predicate over a Packages stanza (dict)."""
    tree = _Parser(text).parse()

    def ev(node, pkg):
        kind = node[0]
        if kind == "or":
            return any(ev(n, pkg) for n in node[1])
        if kind == "and":
            return all(ev(n, pkg) for n in node[1])
        _, field, op, value = node
        have = pkg.get(field, "")
        if op == "%":
            return fnmatch.fnmatchcase(have, value)
        if field == "Version":
            return _version_ok(op, have, value)
        return have == value if op == "=" else False

    return lambda pkg: ev(tree, pkg)


def has_name_or_version(text):
    """aptly adds -filter-with-deps only when the filter names no Name/Version."""
    return "Name" in text or "Version" in text
