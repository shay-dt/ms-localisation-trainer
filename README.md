# 🧠 MS Lesion Localisation Trainer

An interactive teaching tool that helps **5th-year medical students** learn to
**localise multiple sclerosis (MS) lesions** from a structured neurological
examination.

## The idea

Students are shown a full neurological examination chart and asked to work
through the **localisation algorithm themselves** — *before* any answer is
revealed:

1. Is this an **UMN or LMN** lesion?
2. Is it **one lesion, a bilateral lesion, or more than one distinct lesion**?
3. **Where** is the lesion? (cortex · subcortical/white matter · brainstem ·
   cerebellum · spinal cord · optic nerve · root · plexus · nerve · NMJ · muscle)
4. **Which side** is it on — and does the **crossing** make sense?
5. **What level explains the signs with the fewest lesions?**

They commit an answer at **interactive checkpoints** and get instant feedback,
can ask **Dr. Cortex** (an AI neurology tutor) for Socratic hints, and only then
reveal the correct lesion location(s), diagnosis, and worked reasoning. This
deliberately forces the clinical reasoning that "asking an AI for the answer"
would skip.

## Features

- **Interactive checkpoints** — commit the lesion pattern, region(s), and side(s)
  and get instant, concept-level feedback (works fully offline).
- **Dr. Cortex, an AI tutor** — a Socratic coach that gives hints and never hands
  over the answer. Powered by Claude (via Amazon Bedrock); the coach is
  provider-agnostic and easy to switch.
- **Progress & self-scoring** — a progress bar, a "cases nailed" score, and a
  completion celebration.
- **Password gate** — keeps the app private to workshop attendees.

## Running it locally

```bash
pip install -r requirements.txt
streamlit run teaching_app.py
```

Then open the URL it prints (usually http://localhost:8501).

### Configuration (secrets)

The app reads these from Streamlit secrets (or environment variables). None are
committed to the repo.

- `AWS_BEARER_TOKEN_BEDROCK` and `AWS_REGION` — enable the Dr. Cortex AI coach
  (Claude via Amazon Bedrock). Without them the trainer still works fully; the
  coach simply shows an "offline" message.
- `APP_PASSWORD` — overrides the workshop password (optional).

The AI provider is selected by `COACH_PROVIDER` in `coach.py` (`bedrock` by
default; `groq`, `gemini`, `glm`, and direct `anthropic` are also supported).

## How it's built

- `teaching_app.py` — the Streamlit app (interface, checkpoints, gamification).
- `coach.py` — the provider-agnostic "Dr. Cortex" AI coach.
- `cases_github/` — the 10 curated teaching cases. Each case folder holds the
  examination chart image and the validated answer/reasoning data.
- `requirements.txt` — Python dependencies.

## Credit & data

Cases are adapted from the open-source
[`stepdaug/medical_llm_evaluation`](https://github.com/stepdaug/medical_llm_evaluation)
project (Auger et al., 2026, *10,000 MS cases — blind spots at scale*). The
cases are **synthetic** — they contain no real patient data.
