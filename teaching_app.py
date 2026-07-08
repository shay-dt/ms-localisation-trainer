# teaching_app.py
# ===========================================================================
# THE MS LESION-LOCALISATION TRAINER  (v2 — interactive + AI coach)
#
# The "flip": show the exam, hide the answer, make the student localise the
# lesion themselves, THEN reveal + let them self-rate. A live AI tutor
# ("Dr. Cortex") gives Socratic hints along the way without giving the answer.
#
# Streamlit mental model: this script runs top-to-bottom on every interaction.
# Every st.something(...) draws on the page. st.session_state is the notebook
# that survives those reruns (it remembers score, chat history, reveal state).
# ===========================================================================

import streamlit as st
from pathlib import Path
import os
import json
import re

# --- Make Bedrock/AWS secrets visible to the AWS SDK ---
# Locally these live in ~/.zshrc (already in the environment). On Streamlit Cloud
# you paste them into the app's Secrets box; this copies them into the environment
# so the AWS SDK (used by the coach) picks them up automatically.
for _k in ("AWS_BEARER_TOKEN_BEDROCK", "AWS_REGION"):
    try:
        if _k in st.secrets and _k not in os.environ:
            os.environ[_k] = str(st.secrets[_k])
    except Exception:
        pass

import coach  # our provider-agnostic AI coach (see coach.py)

# The neuraxis "menu" the student picks regions from (the localisation ladder).
REGION_OPTIONS = [
    "Cortex", "Subcortical / White matter", "Brainstem", "Cerebellum",
    "Spinal cord", "Optic nerve", "Root", "Plexus", "Nerve", "NMJ", "Muscle",
]


# --- Derive the CORRECT checkpoint answers from the ground-truth lesion text ---
# The repo stores lesions as strings like "right C5 myelopathy" or
# "bilateral optic nerve (cranial nerve II)". We parse those into:
#   - how many distinct sites (→ one vs more-than-one),
#   - which neuraxis regions,
#   - which side(s).
# This lets us grade the student instantly with NO AI and NO manual annotation.
# (Shay should sanity-check these derived answers for clinical accuracy.)
def derive_answers(lesions):
    regions, sides = set(), set()
    for raw in lesions:
        l = raw.lower()
        # --- region ---
        if any(k in l for k in ["midbrain", "pons", "medulla", "brainstem"]):
            regions.add("Brainstem")
        if "cerebell" in l:
            regions.add("Cerebellum")
        if ("myelopathy" in l or "spinal cord" in l or "cord" in l
                or "conus" in l or re.search(r"\b[ctl]\d", l)):
            regions.add("Spinal cord")
        if "optic" in l or "cranial nerve ii" in l:
            regions.add("Optic nerve")
        if "subcortical" in l or "white matter" in l:
            regions.add("Subcortical / White matter")
        elif "cortex" in l or "cortical" in l:
            regions.add("Cortex")
        # --- side (bilateral = both) ---
        if "bilateral" in l:
            sides.update(["Left", "Right"])
        else:
            if "right" in l:
                sides.add("Right")
            if "left" in l:
                sides.add("Left")
    # Three-way classification:
    #   - a single entry that spans both sides ("bilateral X") = a bilateral lesion
    #   - a single entry on one side                            = one lesion
    #   - multiple distinct entries                             = multifocal (MS hallmark)
    single_bilateral = len(lesions) == 1 and "bilateral" in lesions[0].lower()
    if single_bilateral:
        one_or_many = "Bilateral lesion"
    elif len(lesions) == 1:
        one_or_many = "One lesion"
    else:
        one_or_many = "More than one distinct lesion"

    return {
        "num_sites": len(lesions),
        "one_or_many": one_or_many,
        "regions": regions,
        "sides": sides,
    }

# --- WHERE THE CASES LIVE ---
BASE_PATH = Path(__file__).parent / "cases_github"

# --- THE 10 CURATED TEACHING CASES (in teaching order) ---
CHOSEN_CASES = ["0001", "0007", "0010", "0017", "0032",
                "0036", "0041", "0053", "0066", "0070"]

# Neutral labels — deliberately NO diagnostic clue in the title.
CASE_TITLES = {c: f"Case {i + 1}" for i, c in enumerate(CHOSEN_CASES)}

# Which model's reasoning to show as the "reference" worked answer on reveal.
REFERENCE_MODEL = "openai_gpt-5-1"


# --- LOAD a case: exam image + ground-truth answer + reference reasoning ---
@st.cache_data(show_spinner="Loading case...")
def load_case(case_number):
    case_path = BASE_PATH / f"case_{case_number}"
    data = {}

    img = case_path / "combined_examination_summary.png"
    data["image"] = img.read_bytes() if img.exists() else None

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

    ans_file = case_path / f"q_{REFERENCE_MODEL}_localisation.json"
    data["reference_reasoning"] = ""
    if ans_file.exists():
        content = json.loads(ans_file.read_text(encoding="utf-8"))
        raw = content.get("response", "")
        if "lesion_locations = " in raw:
            raw = raw.split("lesion_locations = ", 1)[0].rstrip()
        data["reference_reasoning"] = raw

    return data


st.set_page_config(layout="wide", page_title="MS Localisation Trainer", page_icon="🧠")


# ===========================================================================
# PASSWORD GATE — keeps the app (and the AI coach that runs on our AWS bill)
# private to workshop attendees. The password is read from a Streamlit secret
# if present, otherwise falls back to the shared workshop password.
# ===========================================================================
def check_password():
    def _correct():
        try:
            expected = st.secrets.get("APP_PASSWORD", "OxfordAwayDay")
        except Exception:
            expected = "OxfordAwayDay"
        if st.session_state.get("pw_input", "") == expected:
            st.session_state.pw_ok = True
            del st.session_state["pw_input"]   # don't keep the password around
        else:
            st.session_state.pw_ok = False

    if st.session_state.get("pw_ok"):
        return True

    st.title("🧠 MS Lesion Localisation Trainer")
    st.text_input("Enter the workshop password to continue:",
                  type="password", key="pw_input", on_change=_correct)
    if st.session_state.get("pw_ok") is False:
        st.error("Incorrect password — please try again.")
    return False


if not check_password():
    st.stop()


# --- SESSION STATE: our persistent "notebook" across reruns ---
# started    : has the student left the welcome screen?
# score      : how many cases they've self-rated as "got it"
# scored     : set of case ids already scored (so we don't double-count)
# chat_<id>  : chat history with Dr. Cortex, per case
if "started" not in st.session_state:
    st.session_state.started = False
if "score" not in st.session_state:
    st.session_state.score = 0
if "scored" not in st.session_state:
    st.session_state.scored = set()


# ===========================================================================
# WELCOME SCREEN — shown once, sets the tone and explains the game.
# ===========================================================================
def show_welcome():
    st.title("🧠 MS Lesion Localisation Trainer")
    st.subheader("Learn to pinpoint where the lesion is — like a neurologist.")
    st.markdown(
        "You'll see **10 real-style neurological examinations**. For each one, your job is to "
        "**work out where the lesion is** before revealing the answer.\n\n"
        "**How it works:**\n"
        "1. 🔍 Read the examination.\n"
        "2. 🧭 Work through the localisation method (UMN/LMN → how many lesions → where → "
        "which side → fewest lesions).\n"
        "3. 💬 Stuck? Ask **Dr. Cortex**, your AI neurology tutor — she gives hints, never the answer.\n"
        "4. 🔓 Commit your answer, then reveal the correct localisation and score yourself.\n\n"
        "Track your progress across all 10 and aim to build the reflex real clinicians use."
    )
    if coach.coach_is_available():
        st.success("💬 Dr. Cortex (AI tutor) is online and ready to help.")
    else:
        st.info("💡 Dr. Cortex (AI tutor) is currently offline — the trainer works fully without it. "
                "Add an API key to switch her on.")
    if st.button("▶️  Start training", type="primary"):
        st.session_state.started = True
        st.rerun()


if not st.session_state.started:
    show_welcome()
    st.stop()   # don't render the rest until they start


# ===========================================================================
# THE MAIN TRAINER
# ===========================================================================
# --- SIDEBAR: progress, score, case picker ---
with st.sidebar:
    st.header("Your progress")
    done = len(st.session_state.scored)
    st.progress(done / len(CHOSEN_CASES), text=f"{done} / {len(CHOSEN_CASES)} cases attempted")
    st.metric("⭐ Cases you nailed", st.session_state.score)
    st.divider()

    st.header("Cases")
    chosen = st.selectbox(
        "Choose a case",
        options=CHOSEN_CASES,
        format_func=lambda c: (
            f"{CASE_TITLES[c]}  " + ("✅" if c in st.session_state.scored else "•")
        ),
    )
    image_width = st.slider("Exam image size", 500, 1400, 950, 50)

case = load_case(chosen)

reveal_key = f"revealed_{chosen}"
if reveal_key not in st.session_state:
    st.session_state[reveal_key] = False

st.header(CASE_TITLES.get(chosen, chosen))

# --- Layout: exam + task on the left, Dr. Cortex chat on the right ---
main_col, coach_col = st.columns([3, 2])

with main_col:
    st.markdown("#### 🔍 Examination")
    if case["image"]:
        st.image(case["image"], width=image_width)
    else:
        st.error("Examination image not found for this case.")

    st.divider()
    st.subheader("🧭 Your turn: work it out, step by step")
    st.caption("Commit an answer at each checkpoint and get instant feedback — "
               "then write up your full reasoning below.")

    answers = derive_answers(case["lesions"])

    # --- CHECKPOINT 1: how many lesions? ---
    st.markdown("**1. What is the pattern of the lesion(s)?**")
    c1 = st.radio(
        "num lesions",
        ["One lesion", "Bilateral lesion", "More than one distinct lesion"],
        key=f"cp_num_{chosen}", index=None,
        label_visibility="collapsed",
    )
    if c1 is not None:
        if c1 == answers["one_or_many"]:
            explain = {
                "One lesion": "A single, well-localised site accounts for every sign.",
                "Bilateral lesion": "One process affecting **both sides** symmetrically — think "
                                    "toxic/metabolic/degenerative, *not* the multifocal pattern of MS.",
                "More than one distinct lesion": "Signs that no single site can unify → separate "
                                                 "lesions **disseminated in space** — the MS hallmark.",
            }[c1]
            st.success(f"✅ Correct. {explain}")
        else:
            st.warning("🤔 Not quite. Distinguish: can **one** site explain everything? If it needs "
                       "**both sides**, is that a single *bilateral* process, or *separate* lesions "
                       "in different places (dissemination in space)?")

    # --- CHECKPOINT 2: which region(s)? ---
    st.markdown("**2. Which region(s) of the neuraxis are involved?**")
    picked_regions = st.multiselect(
        "regions", REGION_OPTIONS, key=f"cp_reg_{chosen}",
        label_visibility="collapsed",
        placeholder="Choose one or more regions",
    )
    if picked_regions:
        got = set(picked_regions)
        want = answers["regions"]
        if got == want:
            st.success("✅ Spot on — region(s): **" + ", ".join(sorted(want)) + "**.")
        else:
            missed = want - got
            extra = got - want
            msg = []
            if missed:
                msg.append("you haven't yet identified a region the signs point to")
            if extra:
                msg.append("one of your choices isn't supported by the findings")
            st.warning("🤔 " + "; ".join(msg).capitalize() +
                       ". Tip: match each abnormal finding to the structure that produces it.")

    # --- CHECKPOINT 3: which side(s)? ---
    st.markdown("**3. Which side(s) is the lesion on?**")
    picked_sides = st.multiselect(
        "sides", ["Left", "Right", "Midline"], key=f"cp_side_{chosen}",
        label_visibility="collapsed",
        placeholder="Choose one or more",
    )
    if picked_sides:
        if set(picked_sides) == answers["sides"]:
            st.success("✅ Correct side(s): **" + ", ".join(sorted(answers["sides"])) +
                       "**. Remember which tracts cross and where — the crossing has to make sense.")
        else:
            st.warning("🤔 Check the laterality of each sign against where its tract "
                       "decussates. Ipsilateral cranial-nerve + contralateral body signs = brainstem.")

    st.divider()
    st.markdown("**4. Now write up your full reasoning** "
                "(UMN vs LMN, and *why* the level explains the signs with the fewest lesions):")
    st.text_area(
        "Your localisation and reasoning:",
        key=f"answer_{chosen}",
        height=160,
        placeholder=(
            "UMN or LMN? ...\n"
            "Why this level, and does the crossing make sense? ...\n"
            "Fewest lesions that explain all the signs: ..."
        ),
    )

    if st.button("🔓 Reveal correct answer & reasoning", type="primary"):
        st.session_state[reveal_key] = True


# --- DR. CORTEX CHAT (right column) ---
with coach_col:
    st.markdown("#### 💬 Dr. Cortex — your AI tutor")

    if not coach.coach_is_available():
        st.info("Dr. Cortex is offline right now. The trainer still works fully — "
                "reason it out yourself and reveal the answer when ready.")
    else:
        st.caption("Ask for a hint — she'll guide you, never just hand over the answer.")

        # Per-case chat history lives in session_state.
        chat_key = f"chat_{chosen}"
        if chat_key not in st.session_state:
            st.session_state[chat_key] = []

        # Show the conversation so far.
        for msg in st.session_state[chat_key]:
            with st.chat_message("user" if msg["role"] == "user" else "assistant"):
                st.markdown(msg["content"])

        # Input box. When the student sends a message:
        if prompt := st.chat_input("e.g. 'I think it's a cord lesion — am I close?'"):
            st.session_state[chat_key].append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                # st.write_stream renders the coach's reply token-by-token, and
                # returns the full text so we can save it to history.
                reply = st.write_stream(
                    coach.get_coach_reply(st.session_state[chat_key], case)
                )
            st.session_state[chat_key].append({"role": "assistant", "content": reply})


# ===========================================================================
# THE REVEAL — full width, below the two columns.
# ===========================================================================
if st.session_state[reveal_key]:
    st.divider()

    student_answer = st.session_state.get(f"answer_{chosen}", "").strip()
    if student_answer:
        st.markdown("#### Your answer (for comparison)")
        st.markdown(f"> {student_answer}")

    if case["lesions"]:
        st.success("**✅ Correct lesion location(s):**\n\n" +
                   "\n".join(f"- {x}" for x in case["lesions"]))
    if case["diagnosis"]:
        st.info("**Diagnosis:** " + ", ".join(case["diagnosis"]))

    if case["reference_reasoning"]:
        st.markdown("#### Worked reasoning (reference)")
        st.markdown(case["reference_reasoning"])
        st.caption("Reference localisation generated by an LLM in the source study; "
                   "use it to check your reasoning, not as gospel.")

    # --- SELF-RATING (gamification) ---
    st.divider()
    st.markdown("#### How did you do on this case?")
    st.caption("Be honest — this just tracks your own progress.")
    c1, c2 = st.columns(2)
    already = chosen in st.session_state.scored
    with c1:
        if st.button("⭐ I got it right", disabled=already, key=f"got_{chosen}"):
            st.session_state.scored.add(chosen)
            st.session_state.score += 1
            st.balloons()
            st.rerun()
    with c2:
        if st.button("📚 I'll review this one", disabled=already, key=f"review_{chosen}"):
            st.session_state.scored.add(chosen)   # counts as attempted, not nailed
            st.rerun()

    if already:
        st.caption("✅ Scored. Pick the next case from the sidebar.")

    # --- COMPLETION CELEBRATION ---
    if len(st.session_state.scored) == len(CHOSEN_CASES):
        st.success(f"🎉 You've completed all {len(CHOSEN_CASES)} cases! "
                   f"You nailed {st.session_state.score} of them. "
                   "Localisation is a skill — come back and beat your score.")
