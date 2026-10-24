import re

import os
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

# --------------------------------------------------
# ALOKO AI TEACHER - LOCAL MVP
# --------------------------------------------------

APP_DIR = Path(__file__).resolve().parent
from dotenv import load_dotenv
load_dotenv(APP_DIR / ".env")
OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "llama3.2:latest"

COURSE_FILE = APP_DIR / "hnd_microbiology_curriculum.csv"
TOPICS_FILE = APP_DIR / "hnd_microbiology_topics.csv"

st.set_page_config(
    page_title="Aloko AI Teacher",
    page_icon="\U0001F9EB",
    layout="wide",
)

# ALOKO_AUTH_GATE_V1
from auth import init_db, register_user, verify_user, is_subscription_exempt
from subscriptions import init_subscription_db, can_ask_question, record_question, get_subscription
import secrets
from paystack_payments import initialize_checkout, verify_transaction, PLANS
from db import get_connection
from learning_tools import render_learning_tools


init_db()
init_subscription_db()

if "aloko_user_email" not in st.session_state:
    st.session_state.aloko_user_email = None

if not st.session_state.aloko_user_email:
    st.title("Aloko AI Teacher")
    st.write("Sign in or create an account to continue.")
    st.caption("Need help or found a problem? Contact support:")
    st.markdown("**[solomonenamudu@gmail.com](mailto:solomonenamudu@gmail.com)**")
    st.info(
        "Already registered? Sign in using the same email address and password "
        "you used when creating your account. No verification code or email link "
        "will be sent. If you are new, create an account first."
    )
    st.warning(
        "Important: Please remember your password and keep it safe. "
        "Password recovery is not available yet. If you forget your password, "
        "you may be unable to access that account, so you may need to create "
        "a new account."
    )

    sign_in_tab, register_tab = st.tabs(["Sign in", "Create account"])

    with sign_in_tab:
        with st.form("aloko_sign_in_form"):
            login_email = st.text_input("Email address", key="login_email")
            login_password = st.text_input(
                "Password", type="password", key="login_password"
            )
            login_submit = st.form_submit_button("Sign in", use_container_width=True)

        if login_submit:
            if verify_user(login_email, login_password):
                st.session_state.aloko_user_email = login_email.strip().lower()
                st.session_state.aloko_subscription_bypass = is_subscription_exempt(login_email)
                st.rerun()
            else:
                st.error("Sign-in failed. Check your details and try again.")

    with register_tab:
        with st.form("aloko_register_form"):
            new_email = st.text_input("Email address", key="register_email")
            new_password = st.text_input(
                "Create password (at least 8 characters)",
                type="password",
                key="register_password",
            )
            confirm_password = st.text_input(
                "Confirm password", type="password", key="confirm_password"
            )
            register_submit = st.form_submit_button(
                "Create account", use_container_width=True
            )

        if register_submit:
            if new_password != confirm_password:
                st.error("The passwords do not match.")
            else:
                success, message = register_user(new_email, new_password)
                if success:
                    st.success(message)
                else:
                    st.error(message)

    st.stop()

with st.sidebar:
    st.caption(f"Signed in as {st.session_state.aloko_user_email}")
    if is_subscription_exempt(st.session_state.aloko_user_email):
        st.success("Friend access enabled - subscription exempt")
    # ALOKO_PAYSTACK_CHECKOUT_V2 - Neon PostgreSQL
    st.divider()
    st.subheader("Aloko Premium")
    st.write("Monthly — ₦1,500")
    st.write("Annual — ₦15,000")
    st.caption("Free plan: 2 questions per day.")

    current_email = st.session_state.aloko_user_email.strip().lower()

    # Verify Paystack's returned reference against the account and pending plan.
    returned_ref = st.query_params.get("reference")
    if returned_ref:
        try:
            with get_connection() as conn:
                pending = conn.execute(
                    "SELECT user_email, plan FROM pending_payments WHERE reference = %s",
                    (returned_ref,),
                ).fetchone()

            if pending and pending[0].strip().lower() == current_email:
                pending_email, pending_plan = pending
                if pending_plan not in PLANS:
                    st.error("The pending payment has an invalid plan.")
                else:
                    verified = verify_transaction(
                        returned_ref,
                        PLANS[pending_plan]["amount"],
                        pending_email,
                    )
                    if verified:
                        from subscriptions import activate_verified_subscription
                        activate_verified_subscription(pending_email, pending_plan)
                        with get_connection() as conn:
                            conn.execute(
                                "DELETE FROM pending_payments WHERE reference = %s",
                                (returned_ref,),
                            )
                        st.success("Payment verified. Premium is now active.")
                    else:
                        st.warning("Payment is not confirmed yet. Please retry later.")
            else:
                st.warning("No matching checkout was found for this account.")
        except Exception:
            st.error("We could not verify this payment yet. Please retry shortly.")
        st.query_params.clear()
        st.rerun()

    current_subscription = get_subscription(current_email)

    if (
        current_subscription["plan"] == "premium"
        and current_subscription["status"] == "active"
    ):
        with get_connection() as conn:
            details = conn.execute(
                "SELECT billing_plan, expires_at FROM subscription_details "
                "WHERE user_email = %s",
                (current_email,),
            ).fetchone()

        st.success("Aloko Premium is active!")
        if details:
            plan_label = "Monthly" if details[0] == "monthly" else "Annual"
            st.write(f"Plan: {plan_label}")
            st.caption(f"Expires: {str(details[1])[:10]}")
    elif is_subscription_exempt(current_email):
        st.success("Friend access enabled — subscription exempt")
    else:
        st.write("Choose a plan to continue to secure Paystack test checkout.")
        for plan_key, label in [
            ("monthly", "Pay monthly — ₦1,500"),
            ("annual", "Pay annually — ₦15,000"),
        ]:
            if st.button(
                label, use_container_width=True, key=f"aloko_checkout_{plan_key}"
            ):
                reference = "aloko_" + secrets.token_hex(16)
                try:
                    with get_connection() as conn:
                        conn.execute(
                            "INSERT INTO pending_payments "
                            "(reference, user_email, plan) VALUES (%s, %s, %s)",
                            (reference, current_email, plan_key),
                        )

                    callback_url = os.getenv("PAYSTACK_CALLBACK_URL", "").strip()
                    if not callback_url:
                        raise RuntimeError(
                            "PAYSTACK_CALLBACK_URL is missing from environment settings."
                        )

                    checkout_url = initialize_checkout(
                        current_email, plan_key, reference, callback_url
                    )
                    st.link_button(
                        "Open Paystack checkout",
                        checkout_url,
                        use_container_width=True,
                    )
                    st.info(
                        "Complete test checkout, then return to this app to verify payment."
                    )
                except Exception as exc:
                    with get_connection() as conn:
                        conn.execute(
                            "DELETE FROM pending_payments WHERE reference = %s",
                            (reference,),
                        )
                    st.error(f"Could not start checkout: {exc}")

    if st.button("Sign out", use_container_width=True):
        st.session_state.aloko_user_email = None
        st.session_state.messages = []
        st.session_state.chat_signature = None
        st.rerun()


st.title("\U0001F9EB Aloko AI Teacher")

# App download / install entry point
with st.container():
    st.link_button(
        "?? Download App",
        os.getenv("ALOKO_APP_DOWNLOAD_URL", "https://aloko-1.onrender.com/"),
        help="Open Aloko. A standalone installer will be provided when app packaging is ready.",
    )

st.caption("Your AI learning companion for HND Microbiology")

# --------------------------------------------------
# LOAD CURRICULUM CSV FILES
# --------------------------------------------------

@st.cache_data
def load_csv(path_string):
    path = Path(path_string)
    if not path.exists():
        return pd.DataFrame()

    try:
        return pd.read_csv(path, encoding="utf-8-sig").fillna("")
    except Exception:
        return pd.DataFrame()


catalog = load_csv(str(COURSE_FILE))
topics = load_csv(str(TOPICS_FILE))


def available_courses():
    if not catalog.empty and {
        "course_code", "course_title"
    }.issubset(catalog.columns):
        result = catalog[
            ["course_code", "course_title", "level", "semester"]
        ].drop_duplicates()

        return result.to_dict("records")

    return [
        {"course_code": "STH 301", "course_title": "Microbial Biochemistry",
         "level": "HND I", "semester": "Semester 1"},
        {"course_code": "STM 311", "course_title": "Bacteriology",
         "level": "HND I", "semester": "Semester 1"},
        {"course_code": "STM 312", "course_title": "Microbiological Techniques I",
         "level": "HND I", "semester": "Semester 1"},
        {"course_code": "STM 321", "course_title": "Mycology",
         "level": "HND I", "semester": "Semester 2"},
        {"course_code": "STM 322", "course_title": "Microbiological Techniques II",
         "level": "HND I", "semester": "Semester 2"},
        {"course_code": "STM 323", "course_title": "Environmental Microbiology",
         "level": "HND I", "semester": "Semester 2"},
        {"course_code": "STM 414", "course_title": "Pathogenic Microbiology",
         "level": "HND II", "semester": "Semester 1"},
        {"course_code": "STM 415", "course_title": "Immunology and Public Health",
         "level": "HND II", "semester": "Semester 1"},
        {"course_code": "STM 421", "course_title": "Microbiological Quality Control",
         "level": "HND II", "semester": "Semester 2"},
        {"course_code": "STM 422", "course_title": "Industrial Microbiology",
         "level": "HND II", "semester": "Semester 2"},
        {"course_code": "STM 423", "course_title": "Waste Treatment and Utilization",
         "level": "HND II", "semester": "Semester 2"},
    ]


courses = available_courses()

# Ensure Advanced Psychometry remains available even if the CSV is stale.
if not any(
    str(c.get("course_code", "")).strip().upper() == "GNS 306"
    for c in courses
):
    courses.append({
        "course_code": "GNS 306",
        "course_title": "Advanced Psychometry",
        "level": "HND I",
        "semester": "Semester 1",
    })


# --------------------------------------------------
# SESSION STATE
# --------------------------------------------------

if "messages" not in st.session_state:
    st.session_state.messages = []

if "chat_signature" not in st.session_state:
    st.session_state.chat_signature = None


# --------------------------------------------------
# SIDEBAR
# --------------------------------------------------

with st.sidebar:
    st.header("\U0001F4DA Learning Setup")

    level = st.selectbox(
        "HND Level",
        ["HND I", "HND II"],
    )

    semester = st.selectbox(
        "Semester",
        ["Semester 1", "Semester 2"],
    )

    filtered_courses = [
        c for c in courses
        if str(c.get("level", "")).strip() == level
        and str(c.get("semester", "")).strip() == semester
    ]

    if not filtered_courses:
        filtered_courses = courses

    course_labels = [
        f'{c["course_code"]} — {c["course_title"]}'
        for c in filtered_courses
    ]

    selected_label = st.selectbox(
        "Select Course",
        course_labels,
    )

    selected_index = course_labels.index(selected_label)
    selected_course = filtered_courses[selected_index]

    mode = st.selectbox(
        "Teaching Mode",
        [
            "Ask the AI",
            "Teach Me",
            "Detailed Notes",
            "Explain Simply",
            "Test Me",
            "Exam Preparation",
            "Practical Learning",
            "Quick Revision",
        ],
    )

    if os.getenv("GROQ_API_KEY", "").strip():
        model = "openai/gpt-oss-20b"
        st.caption("AI Provider: Groq")
        st.caption(f"Model: {model}")
    else:
        model = st.selectbox(
            "Local AI Model",
            ["llama3.2:latest", "llama3.2:1b"],
            index=0,
        )
        st.caption("AI Provider: Local Ollama")

    st.divider()

    if st.button("\U0001F5D1 Clear Conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.chat_signature = None
        st.rerun()

    

# Reset conversation when the selected course or mode changes.
signature = (
    selected_course["course_code"],
    mode,
)

if st.session_state.chat_signature != signature:
    st.session_state.messages = []
    st.session_state.chat_signature = signature


# --------------------------------------------------
# CURRICULUM CONTEXT
# --------------------------------------------------

def get_course_context(course_code):
    sections = []
    code = str(course_code).strip()

    # 1. Load the existing course catalogue entry.
    if not catalog.empty and "course_code" in catalog.columns:
        selected = catalog[
            catalog["course_code"].astype(str).str.strip().str.upper()
            == code.upper()
        ]
        if not selected.empty:
            sections.append(
                "COURSE CATALOG ENTRY:\\n"
                + selected.to_csv(index=False)
            )

    # 2. Load the existing curriculum topic outline.
    if not topics.empty and "course_code" in topics.columns:
        selected_topics = topics[
            topics["course_code"].astype(str).str.strip().str.upper()
            == code.upper()
        ]
        if not selected_topics.empty:
            sections.append(
                "CURRICULUM TOPICS:\\n"
                + selected_topics.to_csv(index=False)
            )

    # 3. Automatically load verified notes for this course, if available.
    # Example: STM 325 -> STM325_verified_notes.md
    normalized_code = "".join(
        character for character in code.upper() if character.isalnum()
    )
    notes_file = APP_DIR / f"{normalized_code}_verified_notes.md"

    if notes_file.is_file():
        try:
            verified_notes = notes_file.read_text(encoding="utf-8-sig").strip()
            if verified_notes:
                sections.append(
                    "COURSE-SPECIFIC TEACHING NOTES "
                    "(prioritize these notes when relevant; follow their "
                    "accuracy and limitation guidance):\\n"
                    + verified_notes
                )
        except OSError as exc:
            sections.append(
                f"NOTICE: Teaching notes could not be read: {exc}"
            )

    if not sections:
        return (
            "No detailed curriculum CSV entry or verified teaching notes "
            "were found for this course. Use reliable general microbiology "
            "knowledge, clearly identify uncertainty, and never invent "
            "official NBTE requirements."
        )

    return "\\n\\n".join(sections)

def teaching_instruction(selected_mode):
    instructions = {
        "Ask the AI": (
            "Answer the student's question directly. Explain important "
            "terms and preserve context for follow-up questions."
        ),
        "Teach Me": (
            "Teach step by step, starting with prerequisites and definitions. "
            "Use examples, explain why concepts matter, and finish with a "
            "short recap and one or two check-your-understanding questions."
        ),
        "Detailed Notes": (
            "Produce thorough HND-level study notes with headings, "
            "definitions, explanations, examples, key points, and a summary."
        ),
        "Explain Simply": (
            "Explain in accessible language, using analogies where useful. "
            "Keep the science accurate and introduce technical terms clearly."
        ),
        "Test Me": (
            "Create five practice questions on the requested topic. Mix "
            "multiple-choice and short-answer questions where suitable. "
            "Initially withhold the answers so the student can try them. "
            "Mark and explain answers when the student responds."
        ),
        "Exam Preparation": (
            "Prepare the student for examinations using curriculum-aligned "
            "revision notes, likely question styles, practice questions, and "
            "model answer guidance. Do not claim to know leaked exam questions."
        ),
        "Practical Learning": (
            "Explain the purpose of the practical, relevant principles, "
            "equipment, expected observations, interpretation, sources of error, "
            "and appropriate safety precautions. Keep laboratory guidance "
            "within safe educational practice."
        ),
        "Quick Revision": (
            "Give a concise revision sheet containing key definitions, "
            "essential concepts, common confusions, and a few self-test questions."
        ),
    }
    return instructions.get(selected_mode, instructions["Ask the AI"])


SYSTEM_PROMPT = """
You are Aloko AI Teacher, a patient, rigorous and scientifically responsible
tutor for Nigerian HND Microbiology students.

CORE TEACHING RULES
1. Teach at the selected HND level and adapt explanations to the student's question.
2. Use the selected course and supplied curriculum context when relevant.
3. Answer naturally and maintain context across follow-up questions.
4. Explain definitions, mechanisms, examples, reasoning and limitations.
5. Never claim a topic is officially required by NBTE unless supplied curriculum
   evidence supports that claim.
6. Distinguish curriculum wording from additional scientific explanation.
7. Identify conflicting or incomplete source material instead of guessing.
8. Never invent references, citations, experimental results or scientific facts.
9. State uncertainty clearly when you are unsure.
10. Use readable headings, examples, tables and summaries when helpful.
11. Explain laboratory safety principles and avoid unsafe procedural guidance.

COURSE NOTES AND MICROBIOLOGY ACCURACY
- When supplied course-specific teaching notes cover the question, use them
  as the primary grounding source. Follow their stated limitations.
- Do not merely mention the notes; make the actual explanation consistent
  with them. If a requested detail is absent, state the limitation.
- For cellular respiration, distinguish the three pathways precisely:
  aerobic respiration uses oxygen as the terminal electron acceptor;
  anaerobic respiration uses a non-oxygen terminal electron acceptor and
  an electron transport chain; fermentation does not use a respiratory
  electron transport chain and regenerates NAD+ using organic molecules.
- Fermentation produces ATP mainly through substrate-level phosphorylation.
  Do not describe fermentation as passing electrons through a respiratory
  electron transport chain.
- Do not claim anaerobic respiration always produces 2 ATP per glucose.
  Its ATP yield varies by organism and pathway.
- Do not present 36-38 ATP per glucose as a universal aerobic respiration
  yield. If relevant, identify it as a traditional textbook estimate.
- For bacterial growth curves, lag, exponential (log), stationary, and
  death phases are distinct. Never call the lag phase the stationary phase.
- Before submitting a scientific comparison, check every row for consistency
  with the supplied notes. Never invent precise values to fill a gap.

SCIENTIFIC ACCURACY
12. Check terminology, mechanisms, units, calculations and examples for consistency.
13. Distinguish established facts from hypotheses, simplifications and disputed claims.
14. Do not confuse bacteria with viruses, DNA with RNA, genotype with phenotype,
    sterilization with disinfection, or sensitivity with resistance.
15. For calculations, show the formula, values, units and a result check.
16. Do not claim an answer has been independently verified unless it has been
    checked against reliable source material.

DNA AND RNA RULES
17. DNA strands are antiparallel. If one strand runs 5' to 3', its complementary
    strand runs 3' to 5'.
18. DNA replication copies DNA. Each parental strand serves as a template, and
    each daughter DNA double helix normally contains one parental and one new strand.
    This is called semiconservative replication.
19. During transcription, RNA polymerase reads the DNA template 3' to 5' and
    synthesizes RNA 5' to 3'. It transcribes a gene or region, not normally the
    entire genome.
20. DNA base pairs are A-T and G-C. During RNA synthesis, DNA template A pairs
    with RNA U, DNA template T with RNA A, and G with C. RNA uses U instead of T.
21. The RNA sequence matches the DNA coding strand in the 5' to 3' direction,
    except RNA has U where the coding strand has T. RNA is complementary and
    antiparallel to the DNA template strand.
22. Do not describe transcription as conservative replication. Semiconservative
    describes the established mechanism of DNA replication.
23. When giving sequence examples, label the molecule, strand and direction.
    Check complementary bases and orientation before answering.
24. Not all genes encode proteins; some genes produce functional RNA molecules.

COURSE RELEVANCE
25. Use relevant microbiology examples when helpful, including bacterial cells,
    microbial genetics, identification, growth and laboratory quality.
26. Answer related questions even when they extend beyond the selected course.
    Explain the connection without forcing every topic into that course.
27. Never pretend supplied curriculum context contains details that are absent.

RESPONSE QUALITY
28. Answer the student's main question directly.
29. Define important technical terms when first introduced.
30. Include a short takeaway or check-for-understanding question when useful,
    but do not add one mechanically to every answer.
31. For current or source-dependent claims, explain when external verification
    is needed and reliable sources are not available.

"""


def verified_microbiology_answer(question):
    """Return grounded answers for selected, unambiguous microbiology concepts."""
    q = question.lower()

    enzyme_terms = ("enzyme inhibition", "enzyme inhibitor", "competitive inhibition",
                    "non-competitive inhibition", "noncompetitive inhibition")
    if (
        any(term in q for term in enzyme_terms)
        or ("competitive" in q and "non-competitive" in q and "enzyme" in q)
        or ("competitive" in q and "noncompetitive" in q and "enzyme" in q)
    ):
        return (
            "**Competitive vs non-competitive enzyme inhibition**\n\n"
            "| Feature | Competitive inhibition | Pure non-competitive inhibition |\n"
            "|---|---|---|\n"
            "| Binding | Inhibitor binds at the active site and competes with the substrate. | Inhibitor binds at a different site and reduces catalytic activity. It can bind to the free enzyme and the enzyme-substrate complex. |\n"
            "| Effect of more substrate | Can overcome inhibition at sufficiently high substrate concentration. | Does not overcome inhibition. |\n"
            "| Maximum reaction rate (Vmax) | Unchanged. | Decreases. |\n"
            "| Michaelis constant (Km) | Increases. | Unchanged. |\n"
            "| Reversibility | Often reversible; depends on the inhibitor. | Can be reversible or irreversible; non-competitive describes the inhibition mechanism, not reversibility. |\n\n"
            "**Important:** These Vmax and Km effects describe the ideal textbook models. Mixed inhibition can also occur. Do not confuse allosteric binding with proof of non-competitive inhibition. Specific examples should be checked before being classified."
        )


    respiration_terms = ("fermentation", "anaerobic respiration")
    if all(term in q for term in respiration_terms) and (
        "terminal electron acceptor" in q
        or "electron transport chain" in q
        or "compare aerobic" in q
    ):
        return (
            "**Aerobic respiration, anaerobic respiration and fermentation**\n\n"
            "| Feature | Aerobic respiration | Anaerobic respiration | Fermentation |\n"
            "|---|---|---|---|\n"
            "| Terminal electron acceptor | Oxygen (O2) | A non-oxygen acceptor, such as nitrate or sulfate, depending on the organism | An organic molecule or derivative accepts electrons; there is no respiratory terminal acceptor |\n"
            "| Respiratory electron transport chain | Yes | Yes | No |\n"
            "| ATP production | Mainly oxidative phosphorylation, plus substrate-level phosphorylation | Oxidative phosphorylation, plus substrate-level phosphorylation where applicable | Mainly substrate-level phosphorylation |\n\n"
            "ATP yield varies with organism and pathway. The traditional 36–38 ATP per glucose figure is an older textbook estimate, not a universal value. Common lactic acid and alcoholic fermentation pathways yield a net 2 ATP per glucose. Do not assume every anaerobic respiratory pathway yields the same amount."
        )

    oxygen_terms = (
        "obligate aerobe", "obligate anaerobe", "facultative anaerobe",
        "aerotolerant", "tolerate oxygen", "grow without oxygen"
    )
    if sum(term in q for term in oxygen_terms) >= 2:
        return (
            "**Microbial oxygen requirements**\n\n"
            "- **Obligate aerobes:** require oxygen for growth. Example: *Pseudomonas aeruginosa*.\n"
            "- **Facultative anaerobes:** can grow with or without oxygen, usually growing better when oxygen is available. Example: *Escherichia coli*.\n"
            "- **Obligate anaerobes:** oxygen inhibits or may kill them. Example: *Clostridium sporogenes*.\n"
            "- **Aerotolerant anaerobes:** do not use oxygen for respiration but tolerate its presence. Many lactic acid bacteria show this pattern.\n\n"
            "Do not confuse oxygen tolerance with facultative anaerobic growth. Identify the organism and its metabolism before assigning a category."
        )

    growth_terms = (
        "bacterial growth curve",
        "growth curve",
        "lag phase",
        "log phase",
        "exponential phase",
        "stationary phase",
        "death phase",
    )
    phase_terms = ("lag", "stationary", "death", "exponential", "log phase")

    if (
        ("growth curve" in q or "bacterial growth curve" in q)
        and "phase" in q
    ):
        return (
            "**The four phases of the bacterial growth curve**\n\n"
            "| Phase | Cell numbers | Metabolic activity and why it occurs |\n"
            "|---|---|---|\n"
            "| **Lag phase** | There is little or no immediate increase in cell numbers. | Cells adapt to the environment and may synthesize enzymes, proteins and other components needed for growth. They are not necessarily dormant or metabolically inactive. |\n"
            "| **Log (exponential) phase** | Cell numbers increase exponentially under suitable conditions. | Cells divide at a relatively consistent, rapid rate when nutrients and environmental conditions support growth. |\n"
            "| **Stationary phase** | The total population levels off; the rate of new cell formation approximately balances the rate of cell death. | Nutrient limitation, oxygen availability, waste accumulation and other stresses can limit net growth. Some cells remain metabolically active and stress responses may occur. |\n"
            "| **Death (decline) phase** | The number of viable cells generally decreases because cell death exceeds new cell formation. | Nutrient depletion and accumulated harmful products may contribute. Some cells can persist, so the decline is not always uniform. |\n\n"
            "**Important qualifications:** The duration of each phase varies with the organism, medium and environmental conditions. The lag phase is not always the longest, and the stationary phase is not always the shortest. The classic curve describes a population in a closed batch culture; other growth systems may show different patterns."
        )

    growth_terms = (
        "bacterial growth curve",
        "growth curve",
        "lag phase",
        "log phase",
        "exponential phase",
        "stationary phase",
        "death phase",
    )
    phase_terms = ("lag", "stationary", "death", "exponential", "log phase")

    if (
        ("growth curve" in q or "bacterial growth curve" in q)
        and "phase" in q
    ):
        return (
            "**The four phases of the bacterial growth curve**\\n\\n"
            "| Phase | Cell numbers | Metabolic activity and why it occurs |\\n"
            "|---|---|---|\\n"
            "| **Lag phase** | Little or no immediate increase in cell numbers. | Cells adapt and may synthesize enzymes, proteins and other components needed for growth. They are not necessarily dormant. |\\n"
            "| **Log (exponential) phase** | Cell numbers increase exponentially under suitable conditions. | Cells divide rapidly when nutrients and environmental conditions support growth. |\\n"
            "| **Stationary phase** | The population levels off; new cell formation approximately balances cell death in the classic growth curve. | Nutrient limitation, oxygen availability and waste accumulation can restrict net growth. Some cells remain metabolically active. |\\n"
            "| **Death (decline) phase** | Viable cell numbers generally decrease because cell death exceeds new cell formation. | Nutrient depletion and harmful environmental changes may contribute. The decline is not always uniform. |\\n\\n"
            "**Note:** Phase duration and metabolic activity vary with the organism and conditions. The lag phase is not always the longest, and the stationary phase is not always the shortest."
        )

    return None


def verified_dna_transcription_answer(question):
    """Calculate a coding DNA strand's template and RNA transcript."""
    q = question.lower().replace("′", "'").replace("’", "'")

    if not all(term in q for term in ("coding dna", "template", "rna")):
        return None

    sequences = re.findall(r"\b[ACGT]{2,}\b", question.upper())
    if not sequences:
        return None

    coding = sequences[0]
    complement = str.maketrans("ATGC", "TACG")
    template = coding.translate(complement)
    rna = coding.replace("T", "U")

    return (
        "**Verified DNA transcription answer**\n\n"
        f"- Coding DNA strand: 5′-{coding}-3′\n"
        f"- Template DNA strand: 3′-{template}-5′\n"
        f"- RNA transcript: 5′-{rna}-3′\n\n"
        "The strands are antiparallel. RNA polymerase reads the DNA "
        "template 3′→5′ and synthesizes RNA 5′→3′. The RNA transcript "
        "matches the coding strand in sequence, except RNA uses U "
        "instead of T."
    )


# --------------------------------------------------
# CHAT INTERFACE
# --------------------------------------------------

st.subheader(
    f'{selected_course["course_code"]} — {selected_course["course_title"]}'
)
st.caption(f"{level} \u00b7 {semester} \u00b7 Mode: {mode}")

render_learning_tools(
    course_code=selected_course["course_code"],
    course_title=selected_course["course_title"],
    level=level,
    semester=semester,
    email=st.session_state.aloko_user_email,
    exempt=is_subscription_exempt(st.session_state.aloko_user_email),
)


if catalog.empty:
    st.info(
        "Course catalogue CSV not found. The app is using its built-in "
        "starter course list. Place your CSV files beside app.py to load them."
    )

if topics.empty:
    st.info(
        "Detailed topics CSV not found. The AI can still answer general "
        "questions, but detailed curriculum grounding will be limited."
    )


for index, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

        if message["role"] == "assistant":
            st.download_button(
                "Download this note",
                data=message["content"],
                file_name=f"aloko_lesson_{index}.txt",
                mime="text/plain",
                key=f"download_saved_answer_{index}",
            )


question = st.chat_input(
    "Ask a microbiology question or request a lesson..."
)

if question:
    current_email = st.session_state.aloko_user_email
    is_exempt = is_subscription_exempt(current_email)

    allowed, limit_message = can_ask_question(
        current_email,
        exempt=is_exempt,
    )

    if not allowed:
        st.warning(limit_message)
    else:
        # Save and display the user's question before generating an answer.
        st.session_state.messages.append(
            {"role": "user", "content": question}
        )

        with st.chat_message("user"):
            st.markdown(question)

        course_context = get_course_context(
            selected_course["course_code"]
        )

        system_message = f"""
{SYSTEM_PROMPT}

SELECTED COURSE:
{selected_course["course_code"]} — {selected_course["course_title"]}

LEVEL: {level}
SEMESTER: {semester}
TEACHING MODE: {mode}

MODE INSTRUCTIONS:
{teaching_instruction(mode)}

SUPPLIED CURRICULUM CONTEXT:
{course_context}
"""

        conversation = [{"role": "system", "content": system_message}]
        conversation.extend(st.session_state.messages[-12:])

        with st.chat_message("assistant"):
            with st.spinner("Aloko is preparing your lesson..."):
                try:
                    groq_key = os.getenv("GROQ_API_KEY", "").strip()

                    if groq_key:
                        response = requests.post(
                            "https://api.groq.com/openai/v1/chat/completions",
                            headers={
                                "Authorization": f"Bearer {groq_key}",
                                "Content-Type": "application/json",
                            },
                            json={
                                "model": os.getenv(
                                    "GROQ_MODEL", "openai/gpt-oss-20b"
                                ),
                                "messages": conversation,
                                "temperature": 0.4,
                            },
                            timeout=120,
                        )
                        response.raise_for_status()
                        answer = response.json()["choices"][0]["message"]["content"]
                    else:
                        response = requests.post(
                            OLLAMA_URL,
                            json={
                                "model": model,
                                "messages": conversation,
                                "stream": False,
                                "options": {"temperature": 0.4},
                            },
                            timeout=300,
                        )
                        response.raise_for_status()
                        answer = response.json()["message"]["content"]

                    verified_answer = verified_dna_transcription_answer(question)
                    if verified_answer is None:
                        verified_answer = verified_microbiology_answer(question)

                    if verified_answer is not None:
                        answer = verified_answer

                    st.markdown(answer)

                    st.session_state.messages.append(
                        {"role": "assistant", "content": answer}
                    )

                    record_question(current_email, exempt=is_exempt)

                    st.download_button(
                        "Download this note",
                        data=answer,
                        file_name="aloko_lesson_latest.txt",
                        mime="text/plain",
                        key=f"download_latest_{len(st.session_state.messages)}",
                    )

                except requests.exceptions.ConnectionError:
                    st.error(
                        "Cannot connect to the AI provider. Check your Groq key or local Ollama service."
                        "that the local service is running."
                    )
                except requests.exceptions.Timeout:
                    st.error(
                        "The model took too long to respond. Try a shorter "
                        "question or select llama3.2:1b."
                    )
                except Exception as exc:
                    st.error(f"AI request failed: {exc}")


with st.expander("About this prototype"):
    st.write(
        "This is the first local prototype. It connects to Ollama and "
        "can read the two curriculum CSV files when they are stored beside "
        "app.py. Its curriculum knowledge is limited to the supplied "
        "records and the model's general knowledge. A more advanced "
        "retrieval system and broader verified teaching library will be "
        "added in later phases."
    )


