#!/usr/bin/env python3
"""Map ndxvo_converter.py (or any Python file in the repo) without reading it whole.

The app embeds its device photo as ~270 lines of base64, so reading the file
top to bottom spends most of the context on that blob.  This prints a
navigable outline with line numbers and pulls single symbols out on demand.

Run from anywhere inside the repository:

    python .claude/skills/ndxvo-project-map/scripts/outline.py
    python .claude/skills/ndxvo-project-map/scripts/outline.py --constants
    python .claude/skills/ndxvo-project-map/scripts/outline.py --show build_vf
    python .claude/skills/ndxvo-project-map/scripts/outline.py --show App._compose_device
    python .claude/skills/ndxvo-project-map/scripts/outline.py --refs FRAME_BUDGET_BYTES
    python .claude/skills/ndxvo-project-map/scripts/outline.py --file .github/scripts/stamp_version.py
"""

import argparse
import ast
import io
import os
import re
import sys

# A top-level string assignment spanning at least this many lines is a blob.
BLOB_MIN_LINES = 20
RULE = re.compile(r"^#\s*[-=]{10,}\s*$")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def repo_root():
    for start in (os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
        d = start
        while True:
            if os.path.isfile(os.path.join(d, "ndxvo_converter.py")):
                return d
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    sys.exit("ndxvo_converter.py not found above %s" % os.getcwd())


def load(path):
    with io.open(path, encoding="utf-8") as fh:
        text = fh.read()
    return text, text.splitlines(), ast.parse(text, filename=path)


def assigned_names(node):
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    names = []
    for t in targets:
        if isinstance(t, ast.Name):
            names.append(t.id)
        elif isinstance(t, ast.Tuple):
            names += [e.id for e in t.elts if isinstance(e, ast.Name)]
    return names


def blob_info(node):
    """(chars) if this top-level assignment is a long string literal, else None."""
    if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
        return None
    if node.end_lineno - node.lineno + 1 < BLOB_MIN_LINES:
        return None
    val = node.value
    if isinstance(val, ast.Constant) and isinstance(val.value, (str, bytes)):
        return len(val.value)
    return None


def first_doc_line(node):
    doc = ast.get_docstring(node)
    if not doc:
        return ""
    line = doc.strip().splitlines()[0].strip()
    return "  - " + (line if len(line) <= 72 else line[:69] + "...")


def arg_list(fn):
    names = [a.arg for a in fn.args.posonlyargs + fn.args.args]
    if names and names[0] in ("self", "cls"):
        names = names[1:]
    if fn.args.vararg:
        names.append("*" + fn.args.vararg.arg)
    names += [a.arg for a in fn.args.kwonlyargs]
    if fn.args.kwarg:
        names.append("**" + fn.args.kwarg.arg)
    s = ", ".join(names)
    return s if len(s) <= 40 else s[:37] + "..."


def span(node):
    start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
    return start, node.end_lineno


def outline(path, text, lines, tree):
    print("%s  -  %d lines" % (os.path.relpath(path), len(lines)))
    for node in tree.body:
        n = blob_info(node)
        if n:
            print("  BLOB %s: lines %d-%d (%d chars). Never read these lines; "
                  "use --show or Read with offset/limit around them."
                  % (", ".join(assigned_names(node)), node.lineno, node.end_lineno, n))
    print()

    events = []
    for i in range(len(lines) - 2):
        a, b, c = lines[i].strip(), lines[i + 1].strip(), lines[i + 2].strip()
        if RULE.match(a) and RULE.match(c) and b.startswith("#") and not RULE.match(b):
            events.append((i + 2, 0, "== %s ==" % b.lstrip("#").strip()))

    fn_types = (ast.FunctionDef, ast.AsyncFunctionDef)
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            s, e = span(node)
            events.append((s, 1, "class %s  L%d-%d%s" % (node.name, s, e, first_doc_line(node))))
            for sub in node.body:
                if isinstance(sub, fn_types):
                    s2, e2 = span(sub)
                    events.append((s2, 2, "    def %s(%s)  L%d-%d%s"
                                   % (sub.name, arg_list(sub), s2, e2, first_doc_line(sub))))
        elif isinstance(node, fn_types):
            s, e = span(node)
            events.append((s, 1, "def %s(%s)  L%d-%d%s"
                           % (node.name, arg_list(node), s, e, first_doc_line(node))))

    for lineno, _order, txt in sorted(events):
        print("%5d  %s" % (lineno, txt))


def constants(path, text, lines, tree):
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        names = [n for n in assigned_names(node) if n.upper() == n]
        if not names:
            continue
        n = blob_info(node)
        if n:
            src = "%s = <%d-char string literal, lines %d-%d>" % (
                ", ".join(names), n, node.lineno, node.end_lineno)
        else:
            src = " ".join((ast.get_source_segment(text, node) or "").split())
            if len(src) > 150:
                src = src[:147] + "..."
        print("%5d  %s" % (node.lineno, src))


def find_symbol(tree, name):
    fn_types = (ast.FunctionDef, ast.AsyncFunctionDef)
    cls_name, _, meth = name.partition(".")
    hits = []
    for node in tree.body:
        if meth:
            if isinstance(node, ast.ClassDef) and node.name == cls_name:
                hits += [("%s.%s" % (cls_name, meth), s) for s in node.body
                         if isinstance(s, fn_types) and s.name == meth]
            continue
        if isinstance(node, fn_types + (ast.ClassDef,)) and node.name == name:
            hits.append((name, node))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and name in assigned_names(node):
            hits.append((name, node))
        if isinstance(node, ast.ClassDef):
            hits += [("%s.%s" % (node.name, name), s) for s in node.body
                     if isinstance(s, fn_types) and s.name == name]
    return hits


def show(lines, tree, name):
    hits = find_symbol(tree, name)
    if not hits:
        print("'%s' is not defined at module or class level. Try --refs %s." % (name, name))
        return False
    for qual, node in hits:
        n = blob_info(node)
        if n:
            print("# %s is a %d-char string literal at lines %d-%d (not printed)"
                  % (qual, n, node.lineno, node.end_lineno))
            continue
        s, e = span(node)
        print("# %s  (lines %d-%d)" % (qual, s, e))
        for i in range(s, e + 1):
            print("%5d  %s" % (i, lines[i - 1]))
        print()
    return True


class RefFinder(ast.NodeVisitor):
    def __init__(self, name):
        self.name = name
        self.stack = []
        self.hits = {}

    def _scope(self, node):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _scope

    def _hit(self, node):
        self.hits.setdefault(node.lineno, ".".join(self.stack) or "<module>")

    def visit_Name(self, node):
        if node.id == self.name:
            self._hit(node)

    def visit_Attribute(self, node):
        if node.attr == self.name:
            self._hit(node)
        self.generic_visit(node)


def refs(lines, tree, name):
    finder = RefFinder(name)
    finder.visit(tree)
    for qual, node in find_symbol(tree, name):
        print("defined: %s at line %d" % (qual, node.lineno))
    if not finder.hits:
        print("no code references to '%s' (comments and strings are not searched)" % name)
        return
    for lineno in sorted(finder.hits):
        src = lines[lineno - 1].strip()
        if len(src) > 100:
            src = src[:97] + "..."
        print("%5d  in %-32s %s" % (lineno, finder.hits[lineno], src))


def main():
    ap = argparse.ArgumentParser(description="Outline / symbol lookup for ndxvo_converter.py")
    ap.add_argument("--file", help="Python file to inspect (default: ndxvo_converter.py at repo root)")
    ap.add_argument("--constants", action="store_true", help="list top-level UPPER_CASE constants")
    ap.add_argument("--show", action="append", default=[], metavar="NAME",
                    help="print a function, class, method (Class.method) or constant with line numbers")
    ap.add_argument("--refs", action="append", default=[], metavar="NAME",
                    help="every code reference to NAME, with the enclosing function")
    args = ap.parse_args()

    path = os.path.abspath(args.file) if args.file else os.path.join(repo_root(), "ndxvo_converter.py")
    text, lines, tree = load(path)

    ok = True
    if args.constants:
        constants(path, text, lines, tree)
    for name in args.show:
        ok = show(lines, tree, name) and ok
    for name in args.refs:
        refs(lines, tree, name)
    if not (args.constants or args.show or args.refs):
        outline(path, text, lines, tree)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
