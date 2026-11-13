"""Streamlit demo: fix C# compile errors in ASP.NET Core Program.cs files with a QLoRA fine-tuned Qwen2.5-Coder-1.5B."""

import difflib                                          # Show which lines the model changed
import re                                               # Pull the code out of the model's answer

import streamlit as st                                  # The web UI
from huggingface_hub import hf_hub_download, list_repo_files   # Download the model file from the Hub

GGUF_REPO = "alyasarmca/qwen2.5-coder-1.5b-csharp-fix-GGUF"   # The fine-tuned model on the Hugging Face Hub
SYSTEM_PROMPT = ("You fix C# compiler errors in ASP.NET Core Program.cs files. "
                 "Return the complete corrected file in one ```csharp block. Change only what is needed to fix the errors.")   # Exactly as in training
CODE_BLOCK = re.compile(r"```(?:csharp|cs|c#)?[ \t]*\n(.*?)```", re.DOTALL | re.IGNORECASE)   # A ```csharp block
MAX_CODE_CHARS = 3_000                                  # Input guard: longer than anything the model was trained on
MAX_FIXES_PER_SESSION = 20                              # Cost/abuse guard per visitor session (like Project 2)

EXAMPLES = {  # name -> (code, compiler errors)
    "Missing semicolon (CS1002)": (
        'var builder = WebApplication.CreateBuilder(args);\nvar app = builder.Build();\n\napp.MapGet("/", () => "Hello World!")\n\napp.Run();',
        'Line 4: error CS1002: ; expected\n    > app.MapGet("/", () => "Hello World!")'),
    "Misspelled variable (CS0103)": (
        'var builder = WebApplication.CreateBuilder(args);\nbuilder.Services.AddOutputCache();\n\nvar app = buider.Build();\napp.UseOutputCache();\n\napp.MapGet("/time", () => DateTime.Now.ToString()).CacheOutput();\n\napp.Run();',
        "Line 4: error CS0103: The name 'buider' does not exist in the current context\n    > var app = buider.Build();"),
    "await without async (CS4034)": (
        'var builder = WebApplication.CreateBuilder(args);\nvar app = builder.Build();\n\napp.MapGet("/weather", () =>\n{\n    await Task.Delay(200);\n    return Results.Ok(new { Summary = "Sunny" });\n});\n\napp.Run();',
        "Line 6: error CS4034: The 'await' operator can only be used within an async lambda expression. "
        "Consider marking this lambda expression with the 'async' modifier.\n    > await Task.Delay(200);"),
}


@st.cache_resource(show_spinner="Loading the model (first visit only, about 1 minute)…")
def load_model():
    """Download the 4-bit GGUF model once and keep it in memory for all visitors."""
    from llama_cpp import Llama                         # Imported here so the page appears before the heavy library loads
    gguf_file = next(f for f in list_repo_files(GGUF_REPO) if f.lower().endswith("q4_k_m.gguf"))   # Find the 4-bit file
    return Llama(model_path=hf_hub_download(GGUF_REPO, gguf_file),   # Download (cached on disk), then load
                 n_ctx=2048,                            # Same context length as training
                 verbose=False)


def changed_lines(before, after):
    """Only the removed (-) and added (+) lines between two versions."""
    diff = difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
    lines = [l for l in diff if l[:1] in "+-" and not l.startswith(("+++", "---"))]
    return "\n".join(lines) or "(no changes)"


def fix(code, errors):
    """Ask the model for the corrected file (deterministic) and return just the code."""
    user = f"Compiler errors:\n{errors.strip()}\n\nCode:\n```csharp\n{code.strip()}\n```"   # Same format as training
    out = load_model().create_chat_completion(
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
        temperature=0.0,                                # Same input -> same answer
        max_tokens=1024)                                # Enough for any file the model was trained on
    answer = out["choices"][0]["message"]["content"]
    m = CODE_BLOCK.search(answer)
    return (m.group(1) if m else answer).strip()        # The code inside the ```csharp block


# ---------------- Page ----------------
st.set_page_config(page_title="C# Compile-Error Fixer", page_icon="🛠️", layout="wide")
st.title("🛠️ C# Compile-Error Fixer")
st.markdown(
    "A **Qwen2.5-Coder-1.5B** model fine-tuned with **QLoRA** to fix compiler errors in ASP.NET Core `Program.cs` files.  \n"
    "**Held-out test (200 examples):** faithful fix rate **46% → 94%** after fine-tuning (25 minutes on a free T4 GPU).  \n"
    "**Limitation:** trained on synthetic errors (typos, missing `;` / `)`, missing `async`, …). Errors that need API knowledge "
    "the model doesn't have (e.g. the right method name of an unfamiliar API) usually stay unfixed. "
    "Runs on a free CPU, so a fix takes about 15–60 seconds.")

if "fixes" not in st.session_state:                     # Count fixes per visitor session
    st.session_state.fixes = 0

choice = st.selectbox("Start from an example, or paste your own below:", ["(your own code)"] + list(EXAMPLES))
default_code, default_errors = EXAMPLES.get(choice, ("", ""))   # Pre-fill the boxes when an example is chosen

left, right = st.columns(2)
with left:
    code = st.text_area("Broken Program.cs", value=default_code, height=380, key=f"code_{choice}")
    errors = st.text_area("Compiler errors (from dotnet build)", value=default_errors, height=130, key=f"errors_{choice}")
    clicked = st.button("Fix", type="primary")

with right:
    if clicked:
        if not code.strip() or not errors.strip():      # The model needs both inputs
            st.warning("Please paste both the code and the compiler errors.")
        elif len(code) > MAX_CODE_CHARS:                # Input guard
            st.warning(f"The code is too long for this small model (max {MAX_CODE_CHARS:,} characters).")
        elif st.session_state.fixes >= MAX_FIXES_PER_SESSION:   # Session limit
            st.warning("Fix limit for this session reached. Refresh the page later to try again.")
        else:
            with st.spinner("Fixing… (CPU inference, please wait)"):
                fixed = fix(code, errors)
            st.session_state.fixes += 1
            st.subheader("Fixed code")
            st.code(fixed, language="csharp")           # Syntax-highlighted, with a copy button
            st.subheader("Changed lines")
            st.code(changed_lines(code.strip(), fixed), language="diff")   # - before, + after

st.caption("Model: huggingface.co/" + GGUF_REPO + " · Base: Qwen2.5-Coder-1.5B-Instruct · Fine-tuned with Unsloth (QLoRA)")