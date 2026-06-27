# 🧠 MS Lesion Localisation Trainer

An interactive teaching tool that helps 4th-year medical students learn to
**localise multiple sclerosis (MS) lesions** from a structured neurological
examination.

## The idea

Students are shown a full neurological examination chart and asked to work
through the **localisation algorithm themselves** — *before* any answer is
revealed:

1. Is this an **UMN or LMN** lesion?
2. Is there **one lesion, or more than one**?
3. **Where** is the lesion? (cortex · subcortical/white matter · brainstem ·
   cerebellum · spinal cord · root · plexus · nerve · NMJ · muscle)
4. **Which side** is it on — and does the **crossing** make sense?
5. **What level explains the signs with the fewest lesions?**

Only once they commit their reasoning can they reveal the correct lesion
location(s), the diagnosis, and a worked explanation. This deliberately forces
the clinical reasoning that "asking an AI for the answer" would skip.

## Running it locally

```bash
pip install -r requirements.txt
streamlit run teaching_app.py
```

Then open the URL it prints (usually http://localhost:8501).

## How it's built

- `teaching_app.py` — the Streamlit app (the whole interface).
- `cases_github/` — the 10 curated teaching cases. Each case folder holds the
  examination chart image and the validated answer/reasoning data.
- `requirements.txt` — the one dependency (Streamlit).

## Credit & data

Cases are adapted from the open-source
[`stepdaug/medical_llm_evaluation`](https://github.com/stepdaug/medical_llm_evaluation)
project (Auger et al., 2026, *10,000 MS cases — blind spots at scale*). The
cases are **synthetic** — they contain no real patient data.
