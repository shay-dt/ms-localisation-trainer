# coach.py
# ===========================================================================
# "DR. CORTEX" — the AI coaching agent.
#
# KEY DESIGN IDEA (worth understanding): this module is an ABSTRACTION LAYER.
# The rest of the app calls ONE function — get_coach_reply(...) — and does not
# know or care which AI provider answers. Today it's Google Gemini (free tier);
# switching to Claude later is a ONE-LINE change to COACH_PROVIDER below plus a
# key. The app code never changes. That separation is the whole point.
#
# The coach is SOCRATIC: it nudges the student with hints and questions and is
# instructed NEVER to state the final answer outright. It is given the correct
# answer privately (in its system prompt) so its hints point the right way.
# ===========================================================================

import os
import streamlit as st

# ---------------------------------------------------------------------------
# CONFIG — the one knob that chooses the AI engine.
#   "bedrock"   -> Claude via Amazon Bedrock (uses your AWS token; VISION)  [current]
#   "glm"       -> Zhipu / z.ai GLM (OpenAI-compatible, UK-friendly)
#   "groq"      -> Groq free tier (no card, UK-friendly, text-only)
#   "gemini"    -> Google Gemini free tier (UK-blocked for us)
#   "anthropic" -> Claude via a direct Anthropic key
# ---------------------------------------------------------------------------
COACH_PROVIDER = "bedrock"

# Bedrock uses "inference profile" IDs (note the "us." prefix) for on-demand use.
# Haiku 4.5 is fast + cheap + capable — ideal for a Socratic hint-giver.
BEDROCK_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
BEDROCK_REGION = "us-east-1"

GLM_MODEL = "glm-4-flash"
GLM_BASE_URL = "https://api.z.ai/api/paas/v4"
GROQ_MODEL = "llama-3.3-70b-versatile"
GEMINI_MODEL = "gemini-2.0-flash"
ANTHROPIC_MODEL = "claude-opus-4-8"


# --- Find the API key from Streamlit secrets or an environment variable ---
# st.secrets is where Streamlit Cloud stores secrets safely (never in GitHub).
def _get_key(name):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name)


def coach_is_available():
    """True if we have the key needed for the selected provider."""
    if COACH_PROVIDER == "bedrock":
        # Bedrock bearer-token auth. On Streamlit Cloud the secret is copied into
        # the environment so the AWS SDK picks it up automatically (see main app).
        return bool(_get_key("AWS_BEARER_TOKEN_BEDROCK"))
    if COACH_PROVIDER == "glm":
        return bool(_get_key("GLM_API_KEY"))
    if COACH_PROVIDER == "groq":
        return bool(_get_key("GROQ_API_KEY"))
    if COACH_PROVIDER == "gemini":
        return bool(_get_key("GEMINI_API_KEY"))
    if COACH_PROVIDER == "anthropic":
        return bool(_get_key("ANTHROPIC_API_KEY"))
    return False


# --- The coach's PERSONA and rules (shared across providers) ---
# Note it is given the correct answer, but told firmly not to reveal it.
def _system_prompt(case):
    lesions = ", ".join(case.get("lesions", [])) or "unknown"
    diagnosis = ", ".join(case.get("diagnosis", [])) or "unknown"
    return (
        "You are Dr. Cortex, a warm, encouraging consultant neurologist tutoring a "
        "4th/5th-year medical student on lesion localisation. You are looking at the "
        "same neurological examination chart the student can see (provided as an image).\n\n"
        "TEACHING STYLE — this is critical:\n"
        "- Be SOCRATIC. Guide with questions and small hints; make the student do the reasoning.\n"
        "- NEVER state the final lesion location or diagnosis outright, even if asked directly. "
        "If pushed, give a progressively bigger hint instead, but hold the answer back so they "
        "reach it themselves.\n"
        "- Anchor hints in the actual exam findings (e.g. reflex pattern, RAPD, crossed signs).\n"
        "- Use the localisation method: UMN vs LMN, one lesion vs many, where in the neuraxis, "
        "side and whether the crossing makes sense, fewest lesions that explain the signs.\n"
        "- Keep replies SHORT (2-4 sentences). Warm, not verbose.\n\n"
        f"PRIVATE (never reveal directly): the correct lesion(s) are: {lesions}. "
        f"The diagnosis is: {diagnosis}. Use this only to steer your hints in the right direction."
    )


# ===========================================================================
# THE ONE PUBLIC FUNCTION the app calls.
# Returns a GENERATOR of text chunks (so the UI can stream the reply live).
#   history: list of {"role": "user"|"assistant", "content": "..."}
#   case:    the loaded case dict (has "image", "lesions", "diagnosis")
# ===========================================================================
def get_coach_reply(history, case):
    if COACH_PROVIDER == "bedrock":
        yield from _bedrock_reply(history, case)
    elif COACH_PROVIDER == "glm":
        yield from _glm_reply(history, case)
    elif COACH_PROVIDER == "groq":
        yield from _groq_reply(history, case)
    elif COACH_PROVIDER == "gemini":
        yield from _gemini_reply(history, case)
    elif COACH_PROVIDER == "anthropic":
        yield from _anthropic_reply(history, case)
    else:
        yield "Coach is not configured."


# --- BEDROCK implementation — Claude via Amazon Bedrock, WITH VISION ---
# Uses your AWS_BEARER_TOKEN_BEDROCK. Because it's Claude, we can send the exam
# image so Dr. Cortex can actually see the findings (like the direct Claude path).
def _bedrock_reply(history, case):
    import base64
    from anthropic import AnthropicBedrock

    client = AnthropicBedrock(aws_region=BEDROCK_REGION)

    messages = []
    first_user_seen = False
    for msg in history:
        if msg["role"] == "user" and not first_user_seen and case.get("image"):
            b64 = base64.standard_b64encode(case["image"]).decode("utf-8")
            messages.append({
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/png", "data": b64}},
                    {"type": "text", "text": msg["content"]},
                ],
            })
            first_user_seen = True
        else:
            messages.append({"role": msg["role"], "content": msg["content"]})

    with client.messages.stream(
        model=BEDROCK_MODEL,
        max_tokens=400,
        system=_system_prompt(case),
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            yield text


# --- GLM (z.ai / Zhipu) implementation — OpenAI-compatible, TEXT-ONLY ---
# Uses the standard `openai` library pointed at z.ai's endpoint.
def _glm_reply(history, case):
    from openai import OpenAI

    client = OpenAI(api_key=_get_key("GLM_API_KEY"), base_url=GLM_BASE_URL)

    messages = [{"role": "system", "content": _system_prompt(case)}]
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    stream = client.chat.completions.create(
        model=GLM_MODEL,
        messages=messages,
        max_tokens=400,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


# --- GROQ implementation (free tier, TEXT-ONLY) ---
# Free models here are text-only, so instead of the image we pass the exam's
# key facts as text. The coach still knows the answer (in the system prompt)
# and coaches Socratically toward it.
def _groq_reply(history, case):
    from groq import Groq

    client = Groq(api_key=_get_key("GROQ_API_KEY"))

    # OpenAI-style messages: a system turn, then the alternating chat history.
    messages = [{"role": "system", "content": _system_prompt(case)}]
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    stream = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        max_tokens=400,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


# --- GEMINI implementation (current google-genai library, free tier) ---
def _gemini_reply(history, case):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=_get_key("GEMINI_API_KEY"))

    # Build the conversation. Gemini uses "user"/"model" roles and takes the
    # image as an inline part on the first user turn so the coach can "see" it.
    contents = []
    first_user_seen = False
    for msg in history:
        role = "user" if msg["role"] == "user" else "model"
        parts = [types.Part.from_text(text=msg["content"])]
        if role == "user" and not first_user_seen and case.get("image"):
            # Attach the exam chart image to the first student message.
            parts.append(types.Part.from_bytes(data=case["image"], mime_type="image/png"))
            first_user_seen = True
        contents.append(types.Content(role=role, parts=parts))

    stream = client.models.generate_content_stream(
        model=GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(system_instruction=_system_prompt(case)),
    )
    for chunk in stream:
        if chunk.text:
            yield chunk.text


# --- ANTHROPIC / CLAUDE implementation (future upgrade; ready but dormant) ---
def _anthropic_reply(history, case):
    import base64
    import anthropic

    client = anthropic.Anthropic(api_key=_get_key("ANTHROPIC_API_KEY"))

    # Build messages; attach the exam image to the first user turn (vision).
    messages = []
    first_user_seen = False
    for msg in history:
        if msg["role"] == "user" and not first_user_seen and case.get("image"):
            b64 = base64.standard_b64encode(case["image"]).decode("utf-8")
            messages.append({
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/png", "data": b64}},
                    {"type": "text", "text": msg["content"]},
                ],
            })
            first_user_seen = True
        else:
            messages.append({"role": msg["role"], "content": msg["content"]})

    with client.messages.stream(
        model=ANTHROPIC_MODEL,
        max_tokens=400,
        system=_system_prompt(case),
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            yield text
