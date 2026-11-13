"""Score model fixes: does the fix compile, and how far is it from the original code?"""

import difflib                                          # Compare two versions line by line
import re                                               # Normalize spacing

import pandas as pd                                     # Tables

from csharp import compile_many                         # Our parallel build tool


def _lines(code):
    """Non-blank lines with spacing normalized (so indentation or blank-line differences don't count)."""
    return [re.sub(r"\s+", " ", line).strip() for line in code.splitlines() if line.strip()]


def line_changes(original, pred):
    """(changed, deleted): lines the prediction changed or added, and original lines it removed entirely."""
    changed = deleted = 0
    sm = difflib.SequenceMatcher(None, _lines(original), _lines(pred), autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():         # Each block of difference between the two versions
        if op == "replace":                             # Lines rewritten
            changed += max(i2 - i1, j2 - j1)
        elif op == "insert":                            # Lines added
            changed += j2 - j1
        elif op == "delete":                            # Original lines removed (e.g. "fixing" by deleting code)
            deleted += i2 - i1
    return changed, deleted


def score(preds_path, eval_path, workers=4):
    """Compile every prediction and compute the metrics. Returns one row per example."""
    preds = pd.read_json(preds_path, lines=True)        # id, model, raw, pred
    ref = pd.read_json(eval_path, lines=True)[["id", "kinds", "error_codes", "broken", "fixed"]]   # The correct answers
    df = preds.merge(ref, on="id")                      # Prediction next to its correct answer
    results = compile_many(df["pred"].tolist(), workers=workers)   # Really build every prediction
    df["compiles"] = [r.succeeded for r in results]
    df[["changed", "deleted"]] = [line_changes(f, p) for f, p in zip(df["fixed"], df["pred"])]
    df["exact"] = (df["changed"] == 0) & (df["deleted"] == 0)   # Same as the original
    df["faithful_fix"] = df["compiles"] & (df["deleted"] == 0) & (df["changed"] <= 2)   # The main score
    df["returned_broken"] = [_lines(p) == _lines(b) for p, b in zip(df["pred"], df["broken"])]   # Gave the input back unchanged
    df["new_errors"] = [("" if r.succeeded else r.error_text(p, max_errors=2)) for r, p in zip(results, df["pred"])]
    df["operator"] = df["kinds"].str.split("+").str[0]  # Main operator of each example
    return df


def summary(df, name):
    """One row of headline metrics."""
    return {"model": name, "examples": len(df),
            "compiles": f"{df['compiles'].mean():.0%}",
            "faithful fix": f"{df['faithful_fix'].mean():.0%}",   # Main score
            "exact": f"{df['exact'].mean():.0%}",
            "deleted code": f"{(df['deleted'] > 0).mean():.0%}",  # Answers that removed original lines
            "returned broken": f"{df['returned_broken'].mean():.0%}",
            "median changed lines": df["changed"].median()}