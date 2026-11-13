"""Expand C# files that use #define / #if switches into one clean program per variant."""

import re                                               # Find directives and symbols

DIRECTIVE = re.compile(r"^\s*#\s*(define|undef|if|elif|else|endif|region|endregion)\b(.*)$")   # Directive lines we handle
SYMBOL = re.compile(r"\b[A-Za-z_]\w*\b")                # A preprocessor symbol, e.g. FIRST or NET8_0_OR_GREATER
ALWAYS_DEFINED = {"DEBUG", "TRACE", "NET", "NETCOREAPP"} | {f"NET{v}_0_OR_GREATER" for v in range(5, 11)} | {"NET10_0"}
# ^ Symbols the .NET 10 SDK defines automatically in a Debug build, so code under "#if NET8_0_OR_GREATER" stays in


def _symbols_in(expr):
    """All symbol names used in a condition (true/false are literals, not symbols)."""
    return {s for s in SYMBOL.findall(expr.split("//")[0]) if s not in ("true", "false")}


def _evaluate(expr, defined):
    """Evaluate a condition like 'FIRST || (SECOND && !THIRD)' with the given defined symbols."""
    py = expr.split("//")[0]                            # Drop a trailing comment
    py = py.replace("&&", " and ").replace("||", " or ")   # C# operators -> Python operators
    py = re.sub(r"!(?!=)", " not ", py)                 # ! -> not (but leave != alone)
    py = SYMBOL.sub(lambda m: m.group(0) if m.group(0) in ("and", "or", "not")
                    else str(m.group(0) in defined or m.group(0) == "true"), py)   # Each symbol -> True or False
    try:
        return bool(eval(py, {"__builtins__": {}}, {}))   # Safe: only True/False/and/or/not/parentheses remain
    except Exception:                                   # Something unusual: treat the block as inactive
        return False


def preprocess(code, defined):
    """Keep only the active #if branches for this set of symbols; drop #define/#if/#region lines."""
    out = []                                            # The lines we keep
    stack = []                                          # One entry per open #if: [this branch active?, a branch already taken?]
    for line in code.splitlines():
        m = DIRECTIVE.match(line)
        active = all(entry[0] for entry in stack)       # Inside active code only if every enclosing #if is active
        if not m:                                       # A normal code line
            if active:
                out.append(line)
            continue
        kind, rest = m.group(1), m.group(2)
        if kind == "if":
            take = _evaluate(rest, defined)
            stack.append([take, take])
        elif kind == "elif" and stack:
            entry = stack[-1]
            take = not entry[1] and _evaluate(rest, defined)   # Only if no earlier branch was taken
            entry[0], entry[1] = take, entry[1] or take
        elif kind == "else" and stack:
            entry = stack[-1]
            entry[0], entry[1] = not entry[1], True     # Active only if no earlier branch was taken
        elif kind == "endif" and stack:
            stack.pop()
        # define / undef / region / endregion lines are simply dropped
    return "\n".join(out).strip() + "\n"


def expand_variants(code):
    """One clean program per variant: the file as written, plus one per symbol used in #if/#elif."""
    written, used = set(), set()                        # Symbols the file #defines / symbols its conditions test
    for line in code.splitlines():
        m = DIRECTIVE.match(line)
        if m and m.group(1) == "define":
            written |= _symbols_in(m.group(2))          # "#define FIRST // SECOND" defines only FIRST
        elif m and m.group(1) in ("if", "elif"):
            used |= _symbols_in(m.group(2))
    used -= ALWAYS_DEFINED                              # Don't make a separate variant for SDK symbols
    variants = [preprocess(code, ALWAYS_DEFINED | written)]   # 1) the file as its author left it
    for s in sorted(used):                              # 2) each symbol switched on by itself
        variants.append(preprocess(code, ALWAYS_DEFINED | {s}))
    return list(dict.fromkeys(variants))                # Remove identical results, keep the order