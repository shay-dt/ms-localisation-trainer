# teaching_app.py
# ===========================================================================
# THE MS LESION-LOCALISATION TRAINER  (v3 — email login + admin dashboard)
#
# New in v3:
#   - Email OTP login replaces the shared workshop password.
#   - Admin dashboard: invite students, see who logged in and their progress.
#   - Completion tracking: every self-rating is saved to Supabase.
#   - Progress is restored from the database on each login.
#
# Streamlit mental model: this script runs top-to-bottom on every interaction.
# st.session_state is the notebook that persists across those reruns.
# ===========================================================================

import streamlit as st
from pathlib import Path
import os
import json
import re
from datetime import datetime, timezone

# --- Make Bedrock/AWS secrets visible to the AWS SDK ---
for _k in ("AWS_BEARER_TOKEN_BEDROCK", "AWS_REGION"):
    try:
        if _k in st.secrets and _k not in os.environ:
            os.environ[_k] = str(st.secrets[_k])
    except Exception:
        pass

import coach        # provider-agnostic AI coach (coach.py)
import db           # Supabase database operations (db.py)


# ── Page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(layout="wide", page_title="Lesional Neurology Trainer", page_icon="🧠")


# ── Constants ──────────────────────────────────────────────────────────────────
REGION_OPTIONS = [
    "Cortex", "Subcortical / White matter", "Brainstem", "Cerebellum",
    "Spinal cord", "Optic nerve", "Root", "Plexus", "Nerve", "NMJ", "Muscle",
]

BASE_PATH    = Path(__file__).parent / "cases_github"
CHOSEN_CASES = ["0001", "0007", "0010", "0017", "0032",
                "0036", "0041", "0053", "0066", "0070"]
CASE_TITLES  = {c: f"Case {i + 1}" for i, c in enumerate(CHOSEN_CASES)}
REFERENCE_MODEL = "openai_gpt-5-1"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _admin_emails() -> list[str]:
    """Comma-separated list of admin emails from secrets."""
    try:
        raw = st.secrets.get("ADMIN_EMAILS", "")
    except Exception:
        raw = os.environ.get("ADMIN_EMAILS", "")
    return [e.strip().lower() for e in raw.split(",") if e.strip()]


def _relative_time(iso_str: str) -> str:
    """Turn an ISO timestamp into a human string like '3 days ago'."""
    try:
        dt   = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        diff = datetime.now(timezone.utc) - dt
        days = diff.days
        if days == 0:
            hours = diff.seconds // 3600
            return "just now" if hours == 0 else f"{hours}h ago"
        if days == 1:
            return "yesterday"
        if days < 7:
            return f"{days} days ago"
        if days < 30:
            return f"{days // 7}w ago"
        return f"{days // 30}mo ago"
    except Exception:
        return iso_str


# ── Derive correct checkpoint answers from ground-truth lesion text ───────────
def derive_answers(lesions):
    regions, sides = set(), set()
    for raw in lesions:
        l = raw.lower()
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
        if "bilateral" in l:
            sides.update(["Left", "Right"])
        else:
            if "right" in l:
                sides.add("Right")
            if "left" in l:
                sides.add("Left")

    single_bilateral = len(lesions) == 1 and "bilateral" in lesions[0].lower()
    if single_bilateral:
        one_or_many = "Bilateral lesion"
    elif len(lesions) == 1:
        one_or_many = "One lesion"
    else:
        one_or_many = "More than one distinct lesion"

    return {"num_sites": len(lesions), "one_or_many": one_or_many,
            "regions": regions, "sides": sides}


# ── Load a case ───────────────────────────────────────────────────────────────
@st.cache_data(show_spinner="Loading case...")
def load_case(case_number):
    case_path = BASE_PATH / f"case_{case_number}"
    data = {}
    img = case_path / "combined_examination_summary.png"
    data["image"] = img.read_bytes() if img.exists() else None

    report_file = case_path / f"validation_report_{REFERENCE_MODEL}.json"
    data["lesions"] = []
    data["diagnosis"] = []
    data["demographics"] = {}
    data["ddx_report"] = ""
    if report_file.exists():
        report  = json.loads(report_file.read_text(encoding="utf-8"))
        marking = report.get("marking_output", {})
        loc     = marking.get("Localisation", {}).get("structured_data", {})
        ddx     = marking.get("Differential diagnosis", {}).get("structured_data", {})
        data["lesions"]      = loc.get("gt_lesions_english", [])
        data["diagnosis"]    = list(ddx.get("gt_diagnoses_with_source", {}).keys())
        data["demographics"] = report.get("patient_demographics", {})
        data["ddx_report"]   = marking.get("Differential diagnosis", {}).get("report_string", "")

    ans_file = case_path / f"q_{REFERENCE_MODEL}_localisation.json"
    data["reference_reasoning"] = ""
    if ans_file.exists():
        content = json.loads(ans_file.read_text(encoding="utf-8"))
        raw = content.get("response", "")
        if "lesion_locations = " in raw:
            raw = raw.split("lesion_locations = ", 1)[0].rstrip()
        data["reference_reasoning"] = raw

    return data


# ===========================================================================
# LOGIN — email address + shared access code
#
# No email infrastructure needed. The organiser distributes the access code
# alongside the app URL. Students self-register on first login; returning
# students are recognised by their email and their progress is restored.
#
# Secrets required:
#   ACCESS_CODE  = "OxfordNeuro2026"   (distribute this to your cohort)
#   ADMIN_EMAILS = "shay@atmanlabs.ai" (comma-separated; get admin dashboard)
#
# session_state keys set on login:
#   logged_in  : True once authenticated
#   user_email : the verified email address
#   user_role  : "student" | "admin"
# ===========================================================================

def _access_code() -> str:
    """The shared code students use to sign in."""
    try:
        return str(st.secrets.get("ACCESS_CODE", "OxfordNeuro2026"))
    except Exception:
        return os.environ.get("ACCESS_CODE", "OxfordNeuro2026")


def show_login_page():
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        st.markdown("# 🧠 Lesional Neurology Trainer")
        st.markdown("*Oxford Clinical Neurosciences — Catchup Module*")
        st.divider()
        st.markdown("### Sign in")
        st.caption("Enter your email and the access code from your session organiser.")

        email_input = st.text_input(
            "Email address", placeholder="you@ox.ac.uk", key="login_email"
        )
        code_input = st.text_input(
            "Access code", placeholder="e.g. OxfordNeuro2026",
            type="password", key="login_code"
        )

        if st.button("Sign in →", type="primary", use_container_width=True):
            email = email_input.strip().lower()
            code  = code_input.strip()

            if not email or "@" not in email:
                st.error("Please enter a valid email address.")
            elif code != _access_code():
                st.error("Access code incorrect — check with your session organiser.")
            else:
                is_admin = email in _admin_emails()
                user     = db.get_user(email)

                # First-time visitor: create their account automatically
                if not user:
                    db.add_user(email, role="admin" if is_admin else "student")
                    user = db.get_user(email)

                db.touch_login(email)

                # Restore any prior progress from the database
                prior = db.completions_for(email)
                st.session_state.scored = set(c["case_number"] for c in prior)
                st.session_state.score  = sum(
                    1 for c in prior if c.get("self_rating") == "nailed_it"
                )

                st.session_state.logged_in  = True
                st.session_state.user_email = email
                st.session_state.user_role  = "admin" if is_admin else (
                    user.get("role", "student") if user else "student"
                )
                st.rerun()


def check_auth() -> bool:
    """Return True if logged in, otherwise show login page and return False."""
    if st.session_state.get("logged_in"):
        return True
    show_login_page()
    return False


if not check_auth():
    st.stop()


# ===========================================================================
# ADMIN DASHBOARD
# Visible only when logged in as admin and show_admin is True.
# ===========================================================================

def show_admin_page():
    # ── Student detail view ───────────────────────────────────────────────────
    if st.session_state.get("admin_student_view"):
        _show_student_detail(st.session_state.admin_student_view)
        return

    # ── Main admin page ───────────────────────────────────────────────────────
    st.title("🧠 Lesional Neurology Trainer — Admin")
    st.caption(f"Signed in as **{st.session_state.get('user_email', '')}**")

    # ── Add a student ─────────────────────────────────────────────────────────
    st.markdown("#### Add a student")
    st.caption("Students must be added here before they can sign in.")

    col_em, col_btn = st.columns([4, 1])
    with col_em:
        new_email = st.text_input(
            "Student email", placeholder="student@ox.ac.uk",
            label_visibility="collapsed", key="admin_invite_email"
        )
    with col_btn:
        if st.button("Add", type="primary", use_container_width=True):
            email = new_email.strip().lower()
            if not email or "@" not in email:
                st.error("Enter a valid email.")
            elif db.get_user(email):
                st.warning(f"{email} is already in the system.")
            else:
                db.add_user(email, role="student",
                            invited_by=st.session_state.get("user_email"))
                st.success(f"Added {email}")
                st.rerun()

    st.divider()

    # ── Student table ─────────────────────────────────────────────────────────
    st.markdown("#### Students")
    st.caption("Click a student's email to see their answers for each case.")

    summary = db.admin_summary()
    students = [u for u in summary if u.get("role") == "student"]

    if not students:
        st.info("No students added yet. Use the form above to add them.")
    else:
        h = st.columns([3, 2, 1.8, 1.5, 1])
        for col, label in zip(h, ["Email", "Last login", "Completed", "⭐ Nailed", ""]):
            col.markdown(f"<span style='color:#6c7d85;font-size:13px;font-weight:600'>"
                         f"{label}</span>", unsafe_allow_html=True)
        st.divider()

        for u in students:
            row = st.columns([3, 2, 1.8, 1.5, 1])

            # Clickable email → opens student detail view
            if row[0].button(u["email"], key=f"view_{u['email']}",
                             help="Click to see this student's answers"):
                st.session_state.admin_student_view = u["email"]
                st.rerun()

            last = u.get("last_login_at")
            row[1].markdown(_relative_time(last) if last else "*never*")
            row[2].markdown(f"{u['cases_completed']} / {len(CHOSEN_CASES)}")
            row[3].markdown(str(u["cases_nailed"]))

            if row[4].button("Remove", key=f"rm_{u['email']}",
                             help=f"Remove {u['email']} from the system"):
                db.remove_user(u["email"])
                st.rerun()

    st.divider()
    if st.button("← Back to trainer"):
        st.session_state.show_admin = False
        st.rerun()


def _show_student_detail(email: str):
    """Detail view: all completed cases for one student with their answers."""
    st.title(f"🧠 Student answers")
    st.markdown(f"**{email}**")

    if st.button("← Back to all students"):
        st.session_state.admin_student_view = None
        st.rerun()

    st.divider()

    rows = db.student_detail(email)
    if not rows:
        st.info("This student hasn't completed any cases yet.")
        return

    for r in rows:
        case_num  = r.get("case_number", "?")
        case_idx  = CHOSEN_CASES.index(case_num) + 1 if case_num in CHOSEN_CASES else "?"
        rating    = r.get("self_rating", "")
        badge     = "⭐ Nailed it" if rating == "nailed_it" else "📚 Needs review"
        completed = r.get("completed_at", "")

        with st.expander(f"Case {case_idx}  —  {badge}  ({_relative_time(completed) if completed else ''})", expanded=False):

            q1 = r.get("cp_pattern") or "*not answered*"
            q2 = ", ".join(r.get("cp_regions") or []) or "*not answered*"
            q3 = ", ".join(r.get("cp_sides") or []) or "*not answered*"
            q4 = r.get("free_text") or "*not answered*"

            st.markdown(f"**Q1 — Pattern:** {q1}")
            st.markdown(f"**Q2 — Region(s):** {q2}")
            st.markdown(f"**Q3 — Side(s):** {q3}")
            st.markdown("**Q4 — Their reasoning:**")
            st.markdown(f"> {q4}")


# Route admin to the dashboard if they asked for it
if (st.session_state.get("show_admin")
        and st.session_state.get("user_role") == "admin"):
    show_admin_page()
    st.stop()


# ===========================================================================
# SESSION STATE — persistent notebook for the trainer
# ===========================================================================
if "started" not in st.session_state:
    st.session_state.started = False
if "score" not in st.session_state:
    st.session_state.score = 0
if "scored" not in st.session_state:
    st.session_state.scored = set()


# ===========================================================================
# WELCOME SCREEN
# ===========================================================================
def show_welcome():
    st.title("🧠 Lesional Neurology Trainer")
    st.subheader("Learn to pinpoint where the lesion is — like a neurologist.")
    st.markdown(
        "This module contains **10 real-style neurological examinations**. "
        "For each one, your job is to **work out where the lesion is** before the answer is revealed."
    )

    st.divider()

    st.markdown("#### How to use this trainer")
    st.markdown(
        "**Step 1 — Read the examination.**  \n"
        "Each case shows you a structured neurological examination summary. "
        "Read it carefully before attempting the questions.\n\n"
        "**Step 2 — Use Dr. Cortex, your AI tutor, to help you reason through the case.**  \n"
        "Dr. Cortex is available on the right-hand side of every case. "
        "Ask her questions — she will guide your thinking with hints and teaching points "
        "without ever giving the answer away. Use her as much as you need.\n\n"
        "**Step 3 — Answer the four questions below the examination.**  \n"
        "Work through the checkpoints in order and get instant feedback on each one. "
        "Then write up your full reasoning in the free-text box.\n\n"
        "**Step 4 — Reveal and score yourself.**  \n"
        "Compare your answer to the correct localisation and rate how you did."
    )

    # Preview of the question format — constrained width so it fits without scrolling
    preview_img = Path(__file__).parent / "assets" / "question_format_preview.png"
    if preview_img.exists():
        st.markdown("#### What the questions look like")
        st.caption(
            "After reading the examination, scroll down to find these checkpoints. "
            "Work through them in order — don't skip straight to Reveal."
        )
        _, img_col, _ = st.columns([1, 3, 1])
        with img_col:
            st.image(str(preview_img), use_container_width=True)

    st.divider()

    if coach.coach_is_available():
        st.success("💬 Dr. Cortex (AI tutor) is online — ask her for hints at any point, she will guide you without giving the answer away.")
    else:
        st.info("💡 Dr. Cortex (AI tutor) is currently offline — the trainer works fully without it.")

    if st.button("▶️  Start training", type="primary"):
        st.session_state.started = True
        st.rerun()


if not st.session_state.started:
    show_welcome()
    st.stop()


# ===========================================================================
# SIDEBAR — progress, score, case picker, admin button, sign out
# ===========================================================================
with st.sidebar:
    st.header("Your progress")
    done = len(st.session_state.scored)
    st.progress(done / len(CHOSEN_CASES),
                text=f"{done} / {len(CHOSEN_CASES)} cases attempted")
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

    st.divider()

    # Admin dashboard shortcut (only shown to admins)
    if st.session_state.get("user_role") == "admin":
        if st.button("⚙️ Admin dashboard", use_container_width=True):
            st.session_state.show_admin = True
            st.rerun()

    # Sign-out button
    user_display = st.session_state.get("user_email", "")
    st.caption(f"Signed in as {user_display}")
    if st.button("Sign out", use_container_width=True):
        for key in ["logged_in", "user_email", "user_role",
                    "started", "score", "scored", "show_admin",
                    "admin_student_view"]:
            st.session_state.pop(key, None)
        st.rerun()


# ===========================================================================
# MAIN TRAINER
# ===========================================================================
case = load_case(chosen)

reveal_key = f"revealed_{chosen}"
if reveal_key not in st.session_state:
    st.session_state[reveal_key] = False

st.header(CASE_TITLES.get(chosen, chosen))

main_col, coach_col = st.columns([3, 2])

with main_col:
    st.markdown("#### 🔍 Examination")
    if case["image"]:
        st.image(case["image"], width=image_width)
    else:
        st.error("Examination image not found for this case.")

    st.divider()
    st.subheader("🧭 Your turn: work it out, step by step")
    st.caption("Select your answers for questions 1–3, then click **Check my answers** "
               "to get feedback. Write up your full reasoning in Q4, then reveal.")

    answers = derive_answers(case["lesions"])
    submit_key   = f"cp_submitted_{chosen}"
    attempts_key = f"cp_attempts_{chosen}"
    hint_key     = f"cp_hint_{chosen}"
    if submit_key   not in st.session_state: st.session_state[submit_key]   = False
    if attempts_key not in st.session_state: st.session_state[attempts_key] = 0
    if hint_key     not in st.session_state: st.session_state[hint_key]     = False

    # ── Checkpoint 1: how many lesions? ──────────────────────────────────────
    st.markdown("**1. What is the pattern of the lesion(s)?**")
    c1 = st.radio(
        "num lesions",
        ["One lesion", "Bilateral lesion", "More than one distinct lesion"],
        key=f"cp_num_{chosen}", index=None,
        label_visibility="collapsed",
    )

    # ── Checkpoint 2: which region(s)? ───────────────────────────────────────
    st.markdown("**2. Which region(s) of the neuraxis are involved?**")
    picked_regions = st.multiselect(
        "regions", REGION_OPTIONS, key=f"cp_reg_{chosen}",
        label_visibility="collapsed",
        placeholder="Choose one or more regions",
    )

    # ── Checkpoint 3: which side(s)? ─────────────────────────────────────────
    st.markdown("**3. Which side(s) is the lesion on?**")
    picked_sides = st.multiselect(
        "sides", ["Left", "Right", "Midline"], key=f"cp_side_{chosen}",
        label_visibility="collapsed",
        placeholder="Choose one or more",
    )

    # ── Submit button — gates all checkpoint feedback ─────────────────────────
    btn_label = "🔄 Check again" if st.session_state[submit_key] else "✅ Check my answers"
    if st.button(btn_label, key=f"cp_submit_{chosen}"):
        st.session_state[submit_key]    = True
        st.session_state[attempts_key] += 1

    # ── Feedback — only shown after submit ────────────────────────────────────
    if st.session_state[submit_key]:
        # Q1 feedback
        if c1 is None:
            st.warning("Q1: please select an answer.")
        elif c1 == answers["one_or_many"]:
            explain = {
                "One lesion": "A single, well-localised site accounts for every sign.",
                "Bilateral lesion": "One process affecting **both sides** symmetrically — think "
                                    "toxic/metabolic/degenerative, *not* the multifocal pattern of MS.",
                "More than one distinct lesion": "Signs that no single site can unify → separate "
                                                 "lesions **disseminated in space** — the MS hallmark.",
            }[c1]
            st.success(f"✅ Q1 correct. {explain}")
        else:
            st.warning("🤔 Q1: not quite. Can **one** site explain everything? If it needs "
                       "**both sides**, is that a single *bilateral* process, or *separate* lesions "
                       "in different places (dissemination in space)?")

        # Q2 feedback
        if not picked_regions:
            st.warning("Q2: please select at least one region.")
        else:
            got  = set(picked_regions)
            want = answers["regions"]
            if got == want:
                st.success("✅ Q2 correct — region(s): **" + ", ".join(sorted(want)) + "**.")
            else:
                missed = want - got
                extra  = got - want
                msg = []
                if missed:
                    msg.append("you haven't yet identified a region the signs point to")
                if extra:
                    msg.append("one of your choices isn't supported by the findings")
                st.warning("🤔 Q2: " + "; ".join(msg) +
                           ". Tip: match each abnormal finding to the structure that produces it.")

        # Q3 feedback
        if not picked_sides:
            st.warning("Q3: please select at least one side.")
        elif set(picked_sides) == answers["sides"]:
            st.success("✅ Q3 correct — side(s): **" + ", ".join(sorted(answers["sides"])) +
                       "**. Remember which tracts cross and where.")
        else:
            st.warning("🤔 Q3: check the laterality of each sign against where its tract "
                       "decussates. Ipsilateral cranial-nerve + contralateral body signs = brainstem.")

        # ── Hint after 3 failed attempts ─────────────────────────────────────
        q1_ok = c1 == answers["one_or_many"]
        q2_ok = bool(picked_regions) and set(picked_regions) == answers["regions"]
        q3_ok = bool(picked_sides)   and set(picked_sides)   == answers["sides"]

        if not (q1_ok and q2_ok and q3_ok) and st.session_state[attempts_key] >= 3:
            if not st.session_state[hint_key]:
                st.info(f"You've had {st.session_state[attempts_key]} attempts. "
                        "Would you like to see the correct answers for Q1–3?")
                if st.button("💡 Show me the correct answers", key=f"hint_btn_{chosen}"):
                    st.session_state[hint_key] = True
                    st.rerun()
            else:
                st.success(
                    f"**Q1:** {answers['one_or_many']}  \n"
                    f"**Q2:** {', '.join(sorted(answers['regions']))}  \n"
                    f"**Q3:** {', '.join(sorted(answers['sides']))}"
                )

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

    if st.button("🔓 Reveal correct answer & reasoning", type="primary",
                 key=f"reveal_btn_{chosen}"):
        student_text = st.session_state.get(f"answer_{chosen}", "").strip()
        if not student_text:
            st.warning(
                "✏️ **Before revealing, write up your reasoning in the box above.** "
                "Not sure where to start? Ask **Dr. Cortex** on the right — she'll help you "
                "think it through step by step without giving the answer away. "
                "Even a rough attempt helps the learning stick."
            )
        else:
            st.session_state[reveal_key] = True

    # ── THE REVEAL — inline in main column so it appears right here ───────────
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

        # ── Self-rating ───────────────────────────────────────────────────────
        st.divider()
        st.markdown("#### How did you do on this case?")
        st.caption("Be honest — this just tracks your own progress.")
        col_got, col_rev = st.columns(2)
        already = chosen in st.session_state.scored

        with col_got:
            if st.button("⭐ I got it right", disabled=already, key=f"got_{chosen}"):
                st.session_state.scored.add(chosen)
                st.session_state.score += 1
                if st.session_state.get("user_email"):
                    db.log_completion(
                        st.session_state.user_email, chosen, "nailed_it",
                        cp_pattern = st.session_state.get(f"cp_num_{chosen}"),
                        cp_regions = st.session_state.get(f"cp_reg_{chosen}", []),
                        cp_sides   = st.session_state.get(f"cp_side_{chosen}", []),
                        free_text  = st.session_state.get(f"answer_{chosen}", ""),
                    )
                st.balloons()
                st.rerun()

        with col_rev:
            if st.button("📚 I'll review this one", disabled=already, key=f"review_{chosen}"):
                st.session_state.scored.add(chosen)
                if st.session_state.get("user_email"):
                    db.log_completion(
                        st.session_state.user_email, chosen, "needs_review",
                        cp_pattern = st.session_state.get(f"cp_num_{chosen}"),
                        cp_regions = st.session_state.get(f"cp_reg_{chosen}", []),
                        cp_sides   = st.session_state.get(f"cp_side_{chosen}", []),
                        free_text  = st.session_state.get(f"answer_{chosen}", ""),
                    )
                st.rerun()

        if already:
            st.caption("✅ Scored. Pick the next case from the sidebar.")

        if len(st.session_state.scored) == len(CHOSEN_CASES):
            st.success(f"🎉 You've completed all {len(CHOSEN_CASES)} cases! "
                       f"You nailed {st.session_state.score} of them. "
                       "Localisation is a skill — come back and beat your score.")


# ── Dr. Cortex chat (right column) ────────────────────────────────────────────
with coach_col:
    st.markdown("#### 💬 Dr. Cortex — your AI tutor")

    if not coach.coach_is_available():
        st.info("Dr. Cortex is offline right now. The trainer still works fully — "
                "reason it out yourself and reveal the answer when ready.")
    else:
        st.caption("Ask for a hint — she'll guide you, never just hand over the answer.")

        chat_key = f"chat_{chosen}"
        if chat_key not in st.session_state:
            st.session_state[chat_key] = []

        for msg in st.session_state[chat_key]:
            with st.chat_message("user" if msg["role"] == "user" else "assistant"):
                st.markdown(msg["content"])

        if prompt := st.chat_input("e.g. 'I think it's a cord lesion — am I close?'"):
            st.session_state[chat_key].append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                reply = st.write_stream(
                    coach.get_coach_reply(st.session_state[chat_key], case)
                )
            st.session_state[chat_key].append({"role": "assistant", "content": reply})
