# teaching_app.py
# ===========================================================================
# THE MS LESION-LOCALISATION TEACHING APP
#
# The "flip": instead of showing a student the answer, we show only the EXAM
# (the original examination chart image), ask them to localise the lesion
# themselves (free text), and only THEN reveal the correct lesion(s) + reasoning
# for self-comparison.
#
# Mental model reminder: this script runs top-to-bottom on every interaction.
# Every `st.something(...)` draws on the page. `st.session_state` is the little
# notebook that survives those reruns (so we remember "has the student revealed
# the answer yet?").
# ===========================================================================

import streamlit as st
from pathlib import Path
import json
import ast

# --- WHERE THE CASES LIVE ---
BASE_PATH = Path(__file__).parent / "cases_github"

# --- THE 10 CURATED TEACHING CASES (in teaching order) ---
# We deliberately use these specific cases, as-is, from the original repo.
CHOSEN_CASES = ["0001", "0007", "0010", "0017", "0032",
                "0036", "0041", "0053", "0066", "0070"]

# A neutral label for each case — deliberately NO diagnostic clue, so the
# title never gives away the answer. Just "Case N".
CASE_TITLES = {c: f"Case {i + 1}" for i, c in enumerate(CHOSEN_CASES)}

# Which model's reasoning to show as the "reference" worked answer on reveal.
REFERENCE_MODEL = "openai_gpt-5-1"


# --- LOAD a case: the exam image + the ground-truth answer + reference reasoning ---
@st.cache_data(show_spinner="Loading case...")
def load_case(case_number):
    case_path = BASE_PATH / f"case_{case_number}"
    data = {}

    # 1. The examination chart image (bytes we hand straight to st.image).
    img = case_path / "combined_examination_summary.png"
    data["image"] = img.read_bytes() if img.exists() else None

    # 2. The GROUND TRUTH (the correct answer), dug out of the validation report.
    report_file = case_path / f"validation_report_{REFERENCE_MODEL}.json"
    data["lesions"] = []
    data["diagnosis"] = []
    if report_file.exists():
        report = json.loads(report_file.read_text(encoding="utf-8"))
        marking = report.get("marking_output", {})
        loc = marking.get("Localisation", {}).get("structured_data", {})
        ddx = marking.get("Differential diagnosis", {}).get("structured_data", {})
        data["lesions"] = loc.get("gt_lesions_english", [])
        data["diagnosis"] = list(ddx.get("gt_diagnoses_with_source", {}).keys())

    # 3. The reference model's localisation REASONING (prose), shown on reveal.
    ans_file = case_path / f"q_{REFERENCE_MODEL}_localisation.json"
    data["reference_reasoning"] = ""
    if ans_file.exists():
        content = json.loads(ans_file.read_text(encoding="utf-8"))
        raw = content.get("response", "")
        # The answer ends with a python list "lesion_locations = [...]".
        # Split it off so the prose reads cleanly.
        if "lesion_locations = " in raw:
            raw = raw.split("lesion_locations = ", 1)[0].rstrip()
        data["reference_reasoning"] = raw

    return data


# ===========================================================================
# THE PAGE
# ===========================================================================
st.set_page_config(layout="wide", page_title="MS Localisation Trainer")

st.title("🧠 MS Lesion Localisation Trainer")
st.caption("Read the examination, decide where the lesion is, then reveal the answer.")

# --- SIDEBAR: pick a case + image size ---
with st.sidebar:
    st.header("Cases")
    chosen = st.selectbox(
        "Choose a case",
        options=CHOSEN_CASES,
        format_func=lambda c: CASE_TITLES.get(c, c),
    )
    image_width = st.slider("Exam image size", 500, 1400, 950, 50)

case = load_case(chosen)

# --- "Have they revealed the answer for THIS case yet?" ---
# One flag per case id, so revealing case A doesn't spoil case B.
reveal_key = f"revealed_{chosen}"
if reveal_key not in st.session_state:
    st.session_state[reveal_key] = False

# --- THE EXAM (always shown) ---
st.header(CASE_TITLES.get(chosen, chosen))
if case["image"]:
    st.image(case["image"], width=image_width)
else:
    st.error("Examination image not found for this case.")

st.divider()

# --- THE STUDENT'S TASK ---
# We guide the student through the localisation ALGORITHM, step by step, so they
# learn the METHOD — not just guess an answer. Work through these in the box below.
st.subheader("📝 Your turn: where is the lesion?")
st.markdown(
    "Work through the localisation algorithm in the box below, addressing each step:\n\n"
    "1. **UMN or LMN** lesion?\n"
    "2. **One lesion, or more than one?**\n"
    "3. **Where** is the lesion? (cortex · subcortical/white matter · brainstem · "
    "cerebellum · spinal cord · root · plexus · nerve · NMJ · muscle)\n"
    "4. **Which side** is the lesion on — and does the **crossing** make sense?\n"
    "5. **What level explains the signs with the fewest lesions?**"
)

st.text_area(
    "Your localisation and reasoning:",
    key=f"answer_{chosen}",
    height=220,
    placeholder=(
        "1. UMN / LMN: ...\n"
        "2. One lesion or several: ...\n"
        "3. Where (cortex / brainstem / cord / ...): ...\n"
        "4. Side, and does the crossing make sense: ...\n"
        "5. Fewest lesions that explain the signs: ..."
    ),
)

if st.button("🔓 Reveal correct answer & reasoning", type="primary"):
    st.session_state[reveal_key] = True

# --- THE REVEAL (only after the button) ---
if st.session_state[reveal_key]:
    st.divider()

    # Show the student's own answer back, to compare against.
    student_answer = st.session_state.get(f"answer_{chosen}", "").strip()
    if student_answer:
        st.markdown("#### Your answer (for comparison)")
        st.markdown(f"> {student_answer}")

    # The correct lesion location(s).
    if case["lesions"]:
        st.success("**✅ Correct lesion location(s):**\n\n" +
                   "\n".join(f"- {x}" for x in case["lesions"]))
    if case["diagnosis"]:
        st.info("**Diagnosis:** " + ", ".join(case["diagnosis"]))

    # The reference worked reasoning.
    if case["reference_reasoning"]:
        st.markdown("#### Worked reasoning (reference)")
        st.markdown(case["reference_reasoning"])
        st.caption("Reference localisation generated by an LLM in the source study; "
                   "use it to check your reasoning, not as gospel.")
