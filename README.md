# 🧠 Lesional Neurology Trainer

An interactive teaching tool for **medical students** learning to **localise
neurological lesions** from a structured neurological examination. Built for the
**NDCN Undergraduate Faculty** at the University of Oxford as a catchup module.

---

## The idea

Students are shown a full neurological examination chart and must work through
the **localisation algorithm themselves** — *before* any answer is revealed.
This deliberately forces the clinical reasoning that "asking an AI for the
answer" would skip (the "never-skilling" problem).

1. Is this an **UMN or LMN** lesion?
2. Is it **one lesion, a bilateral lesion, or more than one distinct lesion**?
3. **Where** is the lesion? (cortex · subcortical/white matter · brainstem ·
   cerebellum · spinal cord · optic nerve · root · plexus · nerve · NMJ · muscle)
4. **Which side** — and does the **crossing** make sense?
5. **Fewest lesions that explain all the signs?**

Students commit answers at interactive checkpoints, ask **Dr. Cortex** (an AI
Socratic tutor) for hints, then reveal the correct localisation and worked
reasoning. Progress is saved to a database and visible to course organisers.

---

## Features

- **Email + access code login** — students sign in with their email and a shared
  code distributed by the organiser. No passwords to set up.
- **Interactive checkpoints** — commit the lesion pattern, region(s), and
  side(s) and get instant concept-level feedback. Feedback is gated behind a
  "Check my answers" button so students think before they check.
- **3-strikes hint** — after three failed attempts, a button appears to reveal
  the correct checkpoint answers.
- **Dr. Cortex, an AI Socratic tutor** — guides the student's thinking with
  questions and hints. She never volunteers the answer, never interprets a sign
  for the student, and is grounded in the per-case reference reasoning to reduce
  hallucinations. Powered by Claude (via Amazon Bedrock).
- **Q4 gate** — students must write up their full reasoning before the answer is
  revealed.
- **Progress tracking** — per-student completion and self-rating saved to
  Supabase. Progress is restored across sessions.
- **Admin dashboard** — course organisers can add/remove students and admins,
  see each student's login activity and case completions, and read their
  checkpoint answers and free-text reasoning side-by-side with the correct
  answers.
- **Separate admin access code** — admins use a different code from students.
- **Feedback form** — students can leave free-text feedback on the login page,
  visible to admins in the dashboard.
- **Dark mode** — toggle on the login page and in the sidebar.

---

## Running locally

```bash
pip install -r requirements.txt
streamlit run teaching_app.py
```

You will need a `.streamlit/secrets.toml` file (see **Secrets** below).

---

## How it's built

| File | Purpose |
|------|---------|
| `teaching_app.py` | Main Streamlit app — login, welcome screen, trainer, admin dashboard |
| `coach.py` | Provider-agnostic Dr. Cortex AI tutor |
| `db.py` | All Supabase database operations |
| `auth_email.py` | Email sending infrastructure (Gmail SMTP or Resend) |
| `cases_github/` | 10 curated teaching cases — exam chart PNG + validated answer JSON |
| `assets/` | Static assets (preview images) |
| `requirements.txt` | Python dependencies |

---

## Secrets

The app reads configuration from Streamlit secrets (or environment variables).
**Never commit real secret values to this repo.**

Create `.streamlit/secrets.toml` locally with these keys:

```toml
# AWS / Amazon Bedrock (for Dr. Cortex AI coach)
AWS_BEARER_TOKEN_BEDROCK = "..."
AWS_REGION               = "us-east-1"

# Supabase (user accounts, progress tracking)
SUPABASE_URL         = "https://<your-project-ref>.supabase.co"
SUPABASE_SERVICE_KEY = "<service_role_key>"

# Access codes
ACCESS_CODE       = "<code you share with students>"
ADMIN_ACCESS_CODE = "<separate code for admins only>"

# Admin accounts (comma-separated emails)
ADMIN_EMAILS = "organiser@example.com,colleague@example.com"
```

On Streamlit Community Cloud, paste these into **App settings → Secrets**.

---

## Database

The app uses [Supabase](https://supabase.com) (free tier). Run this SQL in the
Supabase SQL editor to create the required tables:

```sql
CREATE TABLE IF NOT EXISTS users (
  id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  email         TEXT        UNIQUE NOT NULL,
  role          TEXT        NOT NULL DEFAULT 'student',
  created_at    TIMESTAMPTZ DEFAULT NOW(),
  last_login_at TIMESTAMPTZ,
  invited_by    TEXT
);

CREATE TABLE IF NOT EXISTS otp_codes (
  id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  email      TEXT        NOT NULL,
  code       TEXT        NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  expires_at TIMESTAMPTZ NOT NULL,
  used       BOOLEAN     DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS completions (
  user_email   TEXT        NOT NULL,
  case_number  TEXT        NOT NULL,
  completed_at TIMESTAMPTZ DEFAULT NOW(),
  self_rating  TEXT,
  cp_pattern   TEXT,
  cp_regions   TEXT,
  cp_sides     TEXT,
  free_text    TEXT,
  PRIMARY KEY (user_email, case_number)
);

CREATE TABLE IF NOT EXISTS feedback (
  id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  email      TEXT,
  message    TEXT        NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Credit & data

Cases are adapted from the open-source
[`stepdaug/medical_llm_evaluation`](https://github.com/stepdaug/medical_llm_evaluation)
project (Auger et al., 2026, *10,000 MS cases — blind spots at scale*,
medRxiv 2026.04.22.26351488v1). The cases are **synthetic** — they contain no
real patient data.
