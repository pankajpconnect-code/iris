"""Auto-translation of legacy pm.test(...) scripts into declarative Tests-tab rows.

Split out of collection_io.py, which had grown past this repo's 500-line
file-size gate — this is the largest single cohesive concern in that file
(regex-driven capture/assertion/visualizer detection) and translate_scripts
is the only entry point _walk (collection_io.py) calls into it, so the split
carries no other call-site changes.
"""

import re

# \w+ rather than a hardcoded object name — legacy scripts always call this
# on their scripting environment's global object, whatever it's named. The
# method alternation covers setEnvironmentVariable(...) (the original,
# deprecated pm API) alongside the four pm.X.set(...) forms that replaced
# it (environment/collectionVariables/variables/globals) — same call shape,
# different scope. The response-object name is captured (not hardcoded into
# the alternation) so translate_scripts can filter it against a whitelist
# in code, keeping the door open for per-script allow-list extensions
# without needing a different compiled regex per script.
_CAPTURE_SET_METHODS = r"(?:setEnvironmentVariable|environment\.set|collectionVariables\.set|variables\.set|globals\.set)"
# The path segment's character class also allows [ ] so an array-index
# segment like "events[0].id" captures whole — assertions.py's
# _json_path_get already understands [n] segments; this is purely widening
# what the capture regex is willing to grab as a path.
_CAPTURE_RE = re.compile(
    r"\w+\." + _CAPTURE_SET_METHODS +
    r"\(\s*[\"']([^\"']+)[\"']\s*,\s*(\w+)\.([A-Za-z0-9_.\[\]]+)\s*\)\s*;?"
)
# The default response-object names a capture's second argument may be
# rooted at. Extended per-script (not globally — see translate_scripts)
# with variable names assigned from JSON.parse(pm.response.text()).
_CAPTURE_RESPONSE_OBJECTS = {"jsonData", "res", "json"}
# Category D idiom: `let x = JSON.parse(pm.response.text());` followed later
# by a capture rooted at `x`. Collected per-script so a variable named the
# same in a different request's script scope never leaks in.
_ASSIGN_FROM_RESPONSE_TEXT_RE = re.compile(
    r"(?:var|let|const)\s+(\w+)\s*=\s*JSON\.parse\(pm\.response\.text\(\)\)\s*;?"
)
# \w+ rather than a hardcoded object name — same convention as _CAPTURE_RE
# above; legacy scripts always call .expect() on their scripting
# environment's own global, whatever it's named.
_ASSERT_EXISTS_RE = re.compile(r"\w+\.expect\((?:jsonData|res)\.([A-Za-z0-9_.]+)(?:,[^)]*)?\)\.to\.exist\s*;?")
_ASSERT_NOT_NULL_RE = re.compile(r"\w+\.expect\((?:jsonData|res)\.([A-Za-z0-9_.]+)\)\.to\.not\.be\.null\s*;?")
_ASSERT_NOT_EMPTY_RE = re.compile(
    r"\w+\.expect\((?:jsonData|res)\.([A-Za-z0-9_.]+)\.length(?:,[^)]*)?\)\.to\.be\.above\(0\)\s*;?"
)
_ASSERT_EQUALS_RE = re.compile(r"\w+\.expect\((?:jsonData|res)\.([A-Za-z0-9_.]+)\)\.to\.eql\(([^)]+)\)\s*;?")
# The commercial client's own auto-suggested boilerplate — the single most
# common assertion in real scripts (ROADMAP.md §12). Numeric form only
# (.status(200)) — the quoted status-text form (.status("OK")) checks the
# HTTP reason phrase, which Iris's response object never carries, so it
# stays untranslated rather than translating into an assertion that can
# never pass.
_ASSERT_STATUS_RE = re.compile(r"\w+\.response\.to\.have\.status\(\s*(\d+)\s*\)\s*;?")


_BOILERPLATE_LINE_RE = re.compile(
    r"^\s*("
    r"//.*"                                                        # comments
    r"|pm\.test\(\s*[\"'].*[\"']\s*,\s*function\s*\(\s*\)\s*\{"     # pm.test(...) { wrapper open
    r"|\}\)\s*;?"                                                    # wrapper close: }); or })
    r"|(var|let|const)\s+\w+\s*=\s*(pm\.response\.json\(\)|JSON\.parse\(responseBody\)|JSON\.parse\(pm\.response\.text\(\)\))\s*;"  # response-parse setup
    r")\s*$"
)


def _blank_spans(text, spans):
    """Blank out matched regions (newlines preserved) so leftover, unmatched lines
    can be detected even when a script mixes a matched statement with one that
    isn't a recognised pattern — matching a substring must not hide the rest."""
    chars = list(text)
    for start, end in spans:
        for i in range(start, end):
            if chars[i] != "\n":
                chars[i] = " "
    lines = "".join(chars).split("\n")
    return "\n".join(line for line in lines if line.strip() and not _BOILERPLATE_LINE_RE.match(line))


_VISUALIZER_CALL_RE = re.compile(r"\w+\.visualizer\.set\(")


def _find_balanced_close_paren(text, open_paren_index):
    """Scans forward from a call's own opening '(' to find its matching
    ')', tracking string/template-literal state so a stray paren inside a
    quoted string doesn't end the scan early. A single regex can't safely
    match a whole pm.visualizer.set(...) call because its arguments can
    contain a multi-hundred-line HTML/CSS template literal that looks
    unbalanced to naive bracket matching (e.g. `rgba(17, 17, 26, 0.1)`
    inside a backtick string). Returns None if the call is never closed."""
    depth = 1
    quote = None
    i = open_paren_index + 1
    length = len(text)
    while i < length:
        char = text[i]
        if quote:
            if char == "\\":
                i += 2
                continue
            if char == quote:
                quote = None
        elif char in ("'", '"', "`"):
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _visualizer_spans(text):
    """Finds pm.visualizer.set(...) calls to blank out — the API console's
    Tests tab has nowhere to render a visualizer template, so this content
    is neither a capture nor an assertion, just noise. The real-world idiom
    builds the template as its own backtick-literal variable first (e.g.
    `var template = \\`...hundreds of lines...\\`;`) and then passes that
    variable by name into the call, so when the call's first argument is a
    bare identifier, the search also blanks that identifier's own preceding
    assignment — otherwise the giant template literal itself would still
    leak into untranslatedScripts even though the call referencing it
    didn't."""
    spans = []
    for call_match in _VISUALIZER_CALL_RE.finditer(text):
        open_paren = call_match.end() - 1
        close_paren = _find_balanced_close_paren(text, open_paren)
        if close_paren is None:
            continue
        span_start = call_match.start()
        first_arg = re.match(r"\s*(\w+)\s*,", text[open_paren + 1:close_paren])
        if first_arg:
            assign_re = re.compile(r"(?:var|let|const)\s+" + re.escape(first_arg.group(1)) + r"\s*=\s*`")
            last_assign = None
            for assign_match in assign_re.finditer(text, 0, call_match.start()):
                last_assign = assign_match
            if last_assign is not None:
                span_start = last_assign.start()
        span_end = close_paren + 1
        if span_end < len(text) and text[span_end] == ";":
            span_end += 1
        spans.append((span_start, span_end))
    return spans


def translate_scripts(events):
    """Auto-translate the known test-script patterns from imported collection
    exports into declarative Tests-tab rows. Anything that doesn't match a
    known pattern is returned as untranslated text, not silently dropped,
    even when it shares a script block with a statement that DOES match."""
    tests = []
    untranslated = []
    for event in events or []:
        if not isinstance(event, dict) or event.get("listen") != "test":
            continue
        script = event.get("script")
        exec_lines = script.get("exec", []) if isinstance(script, dict) else []
        text = "\n".join(exec_lines) if isinstance(exec_lines, list) else str(exec_lines or "")
        if not text.strip():
            continue
        spans = []
        # Per-script (not module-level) so a variable named the same in a
        # different request's script scope never leaks into this one.
        allowed_objects = _CAPTURE_RESPONSE_OBJECTS | {
            m.group(1) for m in _ASSIGN_FROM_RESPONSE_TEXT_RE.finditer(text)
        }
        for match in _CAPTURE_RE.finditer(text):
            variable, obj_name, path = match.groups()
            if obj_name not in allowed_objects:
                continue
            tests.append({"type": "capture", "source": "body", "path": path, "variable": variable})
            spans.append(match.span())
        spans.extend(_visualizer_spans(text))
        for match in _ASSERT_EXISTS_RE.finditer(text):
            tests.append({"type": "assert", "source": "body", "path": match.group(1), "operator": "exists", "expected": ""})
            spans.append(match.span())
        for match in _ASSERT_NOT_NULL_RE.finditer(text):
            tests.append({"type": "assert", "source": "body", "path": match.group(1), "operator": "notNull", "expected": ""})
            spans.append(match.span())
        for match in _ASSERT_NOT_EMPTY_RE.finditer(text):
            tests.append({"type": "assert", "source": "body", "path": match.group(1), "operator": "notEmpty", "expected": ""})
            spans.append(match.span())
        for match in _ASSERT_EQUALS_RE.finditer(text):
            path, expected = match.groups()
            tests.append({
                "type": "assert", "source": "body", "path": path,
                "operator": "equals", "expected": expected.strip("'\" "),
            })
            spans.append(match.span())
        for match in _ASSERT_STATUS_RE.finditer(text):
            tests.append({
                "type": "assert", "source": "status", "path": "",
                "operator": "equals", "expected": match.group(1),
            })
            spans.append(match.span())
        leftover = _blank_spans(text, spans)
        if leftover:
            untranslated.append(leftover)
    return tests, untranslated
