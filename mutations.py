"""Break correct C# programs in realistic ways: one controlled mistake (or two) per example."""

import random                                           # Random choices (seeded, so results are repeatable)
import re                                               # Tokenize C# code

TOKEN = re.compile(r'''
    (?P<comment>//[^\n]*|/\*.*?\*/)                     # // line comment or /* block comment */
  | (?P<raw>"""[\s\S]*?""")                             # C# 11 raw string literal
  | (?P<verbatim>\$?@\$?"(?:[^"]|"")*")                 # @"verbatim" or $@"verbatim interpolated"
  | (?P<string>\$?"(?:\\.|[^"\\\n])*")                  # "normal" or $"interpolated" string
  | (?P<char>'(?:\\.|[^'\\\n])+')                       # 'c' character literal
  | (?P<ident>@?[A-Za-z_]\w*)                           # Identifier or keyword
  | (?P<number>\d[\w.]*)                                # Number literal
  | (?P<punct>[;{}()\[\],.<>=])                         # Punctuation we care about
  | (?P<other>\S)                                       # Anything else (operators, etc.)
''', re.VERBOSE | re.DOTALL)

API_SWAPS = [("Add", "Use"), ("Use", "Add"), ("Map", "Add"), ("Get", "Fetch"), ("Create", "Make"),
             ("With", "Set"), ("Builder", "Build"), ("Services", "Service"), ("Options", "Option")]
# ^ Word swaps that look like real-but-wrong API names (the kind of mistake LLMs made in Project 3)


def tokenize(code):
    """List of (kind, text, start, end) tokens, skipping whitespace."""
    return [(m.lastgroup, m.group(), m.start(), m.end()) for m in TOKEN.finditer(code)]


def _replace(code, start, end, new):
    """Replace code[start:end] with new."""
    return code[:start] + new + code[end:]


def _prev(tokens, i):
    """Text of the token before position i ('' at the start)."""
    return tokens[i - 1][1] if i > 0 else ""


def _line_of(code, pos):
    """The full source line containing character position pos."""
    return code[code.rfind("\n", 0, pos) + 1: (code.find("\n", pos) + 1 or len(code) + 1) - 1]


def typo(name, rng):
    """A typing mistake: change the first letter's case, drop/duplicate/swap a letter."""
    options = []
    if name[0].isalpha():
        options.append(name[0].swapcase() + name[1:])   # MapGet -> mapGet
    if len(name) > 3:
        i = rng.randrange(1, len(name) - 1)             # A random position inside the name
        options.append(name[:i] + name[i + 1:])         # MapGet -> MaGet
        options.append(name[:i] + name[i] + name[i:])   # MapGet -> MappGet
        options.append(name[:i] + name[i + 1] + name[i] + name[i + 2:])   # MapGet -> MaGpet
    options = [o for o in options if o != name and re.fullmatch(r"@?[A-Za-z_]\w*", o)]   # Must still be a valid name
    return rng.choice(options) if options else None


def api_mistake(name, rng):
    """A plausible-but-wrong API name: swap a word (AddCors -> UseCors) or add/remove Async/s."""
    options = [name.replace(a, b, 1) for a, b in API_SWAPS if a in name]   # Word swaps
    options.append(name[:-5] if name.endswith("Async") else name + "Async")   # Async mix-ups
    options.append(name[:-1] if name.endswith("s") else name + "s")           # Plural mix-ups
    options = [o for o in options if o and o != name]
    return rng.choice(options) if options else None


# ---------------- The mutation operators ----------------
# Each one takes (code, tokens, rng) and returns the broken code, or None if it doesn't apply to this program.

def drop_semicolon(code, tokens, rng):
    spots = [t for t in tokens if t[1] == ";" and code[t[3]:t[3] + 2].strip(" \t\r")[:1] in ("\n", "")]   # ; at end of a line
    if not spots:
        return None
    t = rng.choice(spots)
    return _replace(code, t[2], t[3], "")


def drop_closing(code, tokens, rng):
    spots = [t for t in tokens if t[1] in (")", "}")]   # A closing bracket or brace
    if not spots:
        return None
    t = rng.choice(spots)
    return _replace(code, t[2], t[3], "")


def wrong_member(code, tokens, rng):
    spots = [i for i, t in enumerate(tokens) if t[0] == "ident" and _prev(tokens, i) == "."
             and t[1][0].isupper()]                     # A member like .MapGet / .AddControllers
    if not spots:
        return None
    t = tokens[rng.choice(spots)]
    new = api_mistake(t[1], rng) if rng.random() < 0.6 else typo(t[1], rng)   # Mostly API-style mistakes
    return _replace(code, t[2], t[3], new) if new else None


def wrong_type(code, tokens, rng):
    spots = [i for i, t in enumerate(tokens) if t[0] == "ident" and t[1][0].isupper() and _prev(tokens, i) != "."
             and _prev(tokens, i) not in ("class", "record", "struct", "interface", "enum", "namespace")
             and not _line_of(code, t[2]).lstrip().startswith(("using ", "namespace "))]   # A type name being used
    if not spots:
        return None
    t = tokens[rng.choice(spots)]
    new = typo(t[1], rng)
    return _replace(code, t[2], t[3], new) if new else None


def wrong_local(code, tokens, rng):
    declared = {tokens[i + 1][1] for i, t in enumerate(tokens[:-1]) if t[1] == "var" and tokens[i + 1][0] == "ident"}
    spots = [i for i, t in enumerate(tokens) if t[1] in declared and _prev(tokens, i) not in (".", "var")]   # A later use
    if not spots:
        return None
    t = tokens[rng.choice(spots)]
    new = typo(t[1], rng)
    return _replace(code, t[2], t[3], new) if new else None


def remove_using(code, tokens, rng):
    lines = code.split("\n")
    spots = [i for i, line in enumerate(lines) if re.match(r"^\s*using\s+(static\s+)?[\w.]+\s*;", line)]   # using X.Y;
    if not spots:
        return None
    del lines[rng.choice(spots)]
    return "\n".join(lines)


def wrong_literal(code, tokens, rng):
    spots = [t for t in tokens if (t[0] == "number" and t[1].isdigit()) or t[1] in ("true", "false")
             or (t[0] == "string" and re.fullmatch(r'"[A-Za-z_]\w*"', t[1]))]   # 10, true, "word"
    if not spots:
        return None
    t = rng.choice(spots)
    new = t[1][1:-1] if t[0] == "string" else f'"{t[1]}"'   # "word" -> word, 10 -> "10", true -> "true"
    return _replace(code, t[2], t[3], new)


def drop_async(code, tokens, rng):
    spots = [t for t in tokens if t[1] == "async"]      # Remove async but keep the await inside
    if not spots:
        return None
    t = rng.choice(spots)
    end = t[3] + 1 if code[t[3]:t[3] + 1] == " " else t[3]   # Also remove the space after it
    return _replace(code, t[2], end, "")


def drop_new(code, tokens, rng):
    spots = [i for i, t in enumerate(tokens[:-1]) if t[1] == "new" and tokens[i + 1][0] == "ident"
             and tokens[i + 1][1][0].isupper()]         # new Something(...)
    if not spots:
        return None
    t = tokens[rng.choice(spots)]
    return _replace(code, t[2], tokens[tokens.index(t) + 1][2], "")   # Remove "new "


OPERATORS = {f.__name__: f for f in [drop_semicolon, drop_closing, wrong_member, wrong_type, wrong_local,
                                      remove_using, wrong_literal, drop_async, drop_new]}


def mutate(code, kinds, rng):
    """Apply the named operators one after another. Returns the broken code, or None if any doesn't apply."""
    for kind in kinds:
        new = OPERATORS[kind](code, tokenize(code), rng)
        if new is None or new == code:
            return None
        code = new
    return code


def make_mutations(seed_id, code, doubles=2):
    """All candidate broken versions of one program: each operator once, plus a few two-mistake versions."""
    out = []
    for kind in OPERATORS:                              # One attempt per operator
        rng = random.Random(f"{seed_id}|{kind}")        # Seeded: the same input always gives the same output
        broken = mutate(code, [kind], rng)
        if broken:
            out.append({"kinds": [kind], "broken": broken})
    for d in range(doubles):                            # A few versions with two different mistakes
        rng = random.Random(f"{seed_id}|double{d}")
        kinds = rng.sample(sorted(OPERATORS), 2)
        broken = mutate(code, kinds, rng)
        if broken:
            out.append({"kinds": kinds, "broken": broken})
    unique = {m["broken"]: m for m in out}              # Two operators can produce the same text: keep one
    return list(unique.values())