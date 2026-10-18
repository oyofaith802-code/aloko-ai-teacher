import json
import os
import re

import requests
import streamlit as st

from subscriptions import can_ask_question, record_question, get_subscription


def _ask_ai(prompt, email, exempt, count_as_tutor_question=True):
    if count_as_tutor_question:
        allowed, message = can_ask_question(email, exempt=exempt)
        if not allowed:
            st.warning(message)
            return None

    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        st.error("The hosted AI service is not configured.")
        return None

    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are Aloko, a careful HND Microbiology teacher. "
                            "Be scientifically accurate, curriculum-aware, and "
                            "clear about uncertainty. Never invent sources or "
                            "claim generated questions are verified past papers."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
            },
            timeout=120,
        )
        response.raise_for_status()
        answer = response.json()["choices"][0]["message"]["content"]
        if count_as_tutor_question:
            record_question(email, exempt=exempt)
        return answer
    except requests.RequestException:
        st.error("The AI service could not complete the request. Please try again.")
        return None
    except (KeyError, IndexError, TypeError, ValueError):
        st.error("The AI service returned an unexpected response.")
        return None


def _read_upload(upload):
    name = upload.name.lower()
    data = upload.getvalue()

    if name.endswith(".txt"):
        return data.decode("utf-8", errors="replace")

    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            import io

            reader = PdfReader(io.BytesIO(data))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            raise ValueError(
                "Could not read this PDF. If it is scanned, upload a text-based "
                "PDF or paste the relevant question."
            ) from exc

    if name.endswith(".docx"):
        try:
            from docx import Document
            import io

            document = Document(io.BytesIO(data))
            return "\n".join(p.text for p in document.paragraphs)
        except Exception as exc:
            raise ValueError("Could not read this DOCX file.") from exc

    raise ValueError("Please upload a PDF, DOCX, or TXT file.")



FREE_FEATURE_LIMITS = {
    "practice_questions": 2,
    "document_uploads": 1,
    "diagrams": 1,
}


def _premium_or_exempt(email, exempt):
    if exempt:
        return True
    subscription = get_subscription(email)
    return (
        subscription.get("plan") == "premium"
        and subscription.get("status") == "active"
    )


def _feature_usage(email, feature):
    with __import__("db").get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS learning_feature_usage (
                user_email TEXT NOT NULL,
                feature TEXT NOT NULL,
                usage_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_email, feature)
            )
        """)
        row = conn.execute(
            "SELECT usage_count FROM learning_feature_usage "
            "WHERE user_email = %s AND feature = %s",
            (email.strip().lower(), feature),
        ).fetchone()
    return int(row[0]) if row else 0


def _consume_feature(email, feature, amount=1):
    if amount < 1:
        return
    with __import__("db").get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS learning_feature_usage (
                user_email TEXT NOT NULL,
                feature TEXT NOT NULL,
                usage_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_email, feature)
            )
        """)
        conn.execute(
            "INSERT INTO learning_feature_usage "
            "(user_email, feature, usage_count) VALUES (%s, %s, %s) "
            "ON CONFLICT (user_email, feature) DO UPDATE SET "
            "usage_count = learning_feature_usage.usage_count + EXCLUDED.usage_count",
            (email.strip().lower(), feature, amount),
        )


def _remaining_feature(email, feature, exempt):
    if _premium_or_exempt(email, exempt):
        return None
    return max(
        0,
        FREE_FEATURE_LIMITS[feature] - _feature_usage(email, feature),
    )


def _microscope_diagram_dot():
    """Return a built-in labelled educational microscope schematic."""
    return r"""
digraph Microscope {
    graph [label="COMPOUND LIGHT MICROSCOPE",
           labelloc="t", fontsize=20, rankdir=TB,
           splines=ortho, nodesep=0.45, ranksep=0.55,
           bgcolor="white", pad=0.25];
    node [fontname="Arial", fontsize=10, style="rounded,filled",
          fillcolor="#EAF3FF", color="#35618D", margin="0.12,0.08"];
    edge [color="#596579", arrowsize=0.7];

    eyepiece [label="Eyepiece"];
    tube [label="Body tube / head"];
    nose [label="Revolving nosepiece"];
    objective [label="Objective lenses"];
    stage [label="Stage and stage clips"];
    condenser [label="Condenser / diaphragm"];
    light [label="Light source"];
    arm [label="Arm"];
    coarse [label="Coarse focus knob"];
    fine [label="Fine focus knob"];
    base [label="Base"];

    eyepiece -> tube -> nose -> objective -> stage;
    stage -> condenser -> light -> base;
    tube -> arm;
    arm -> coarse;
    coarse -> fine;
    fine -> base;

    {rank=same; arm; coarse; fine;}
}
"""


def _render_microscope_diagram():
    dot = _microscope_diagram_dot()
    st.graphviz_chart(dot, use_container_width=True)


def _amoeba_diagram_svg():
    """Built-in labelled amoeba diagram used when AI SVG output fails."""
    return """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 620" width="900" height="620">
    <rect width="900" height="620" fill="white"/>
    <text x="450" y="38" text-anchor="middle" font-size="26" font-weight="bold" fill="#18324f">LABELLED DIAGRAM OF AN AMOEBA</text>
    <path d="M250,300 C205,255 245,220 300,230 C315,180 365,190 390,220 C440,185 475,225 470,260 C525,250 550,300 515,335 C550,380 495,415 455,395 C430,445 380,425 360,400 C315,435 270,400 285,365 C240,360 220,330 250,300 Z" fill="#d9f0e4" stroke="#287b66" stroke-width="5"/>
    <ellipse cx="380" cy="315" rx="44" ry="37" fill="#a8a5e8" stroke="#5551a6" stroke-width="4"/>
    <circle cx="315" cy="280" r="18" fill="#b9e4f6" stroke="#287ca0" stroke-width="3"/>
    <circle cx="430" cy="365" r="23" fill="#b9e4f6" stroke="#287ca0" stroke-width="3"/>
    <circle cx="455" cy="275" r="10" fill="#f6d58c" stroke="#b8892e" stroke-width="3"/>
    <path d="M275,245 L185,150 L90,150" fill="none" stroke="#334155" stroke-width="2.5"/>
    <text x="85" y="138" font-size="19" fill="#172033">Pseudopodium</text>
    <path d="M365,285 L300,190 L210,190" fill="none" stroke="#334155" stroke-width="2.5"/>
    <text x="205" y="178" font-size="19" fill="#172033">Nucleus</text>
    <path d="M315,280 L210,330 L85,330" fill="none" stroke="#334155" stroke-width="2.5"/>
    <text x="80" y="318" font-size="19" fill="#172033">Food vacuole</text>
    <path d="M430,365 L520,440 L650,440" fill="none" stroke="#334155" stroke-width="2.5"/>
    <text x="655" y="447" font-size="19" fill="#172033">Contractile vacuole</text>
    <path d="M470,300 L555,245 L675,245" fill="none" stroke="#334155" stroke-width="2.5"/>
    <text x="680" y="252" font-size="19" fill="#172033">Cell membrane</text>
    <path d="M340,385 L300,490 L190,490" fill="none" stroke="#334155" stroke-width="2.5"/>
    <text x="90" y="516" font-size="19" fill="#172033">Cytoplasm</text>
    <text x="450" y="575" text-anchor="middle" font-size="16" fill="#475569">Schematic for learning; shape and organelle positions vary.</text>
    </svg>"""


def render_learning_tools(course_code, course_title, level, semester, email, exempt):
    st.subheader("Learning tools")
    st.caption(
        f"{level} · {semester} · {course_code} — {course_title}"
    )

    practice_tab, upload_tab, diagram_tab = st.tabs(
        ["Past-question practice", "Upload notes / questions", "Diagrams & practicals"]
    )

    with practice_tab:
        st.markdown("#### Exam practice")
        st.info(
            "Questions generated by the AI are practice questions, not verified "
            "historical past questions. Upload an authentic past paper in the "
            "document tab to work from that source."
        )

        topic = st.text_input(
            "Topic (optional)",
            key=f"practice_topic_{course_code}",
            placeholder="e.g. bacterial cell structure",
        )
        practice_remaining = _remaining_feature(
            email, "practice_questions", exempt
        )
        if practice_remaining is None:
            count_options = [5, 10, 20]
            count_label = "Questions in this session (Premium / exempt)"
        elif practice_remaining > 0:
            count_options = [practice_remaining]
            count_label = (
                f"Free practice questions available: {practice_remaining}"
            )
        else:
            count_options = []
            count_label = "Free practice questions remaining: 0"

        if count_options:
            count = st.selectbox(
                count_label,
                count_options,
                key=f"practice_count_{course_code}",
            )
        else:
            count = 0
            st.warning(
                "You have used your free practice-question allowance. "
                "Upgrade to Premium for more practice."
            )

        if st.button(
            "Generate practice questions",
            key=f"generate_practice_{course_code}",
            disabled=(count == 0),
        ):
            prompt = f"""
Create exactly {count} original HND Microbiology multiple-choice practice
questions for {course_code} — {course_title}, {level}, {semester}.
Topic: {topic or "cover a balanced selection of this subject's topics"}.

Return ONLY valid JSON, without markdown fences, in this format:
{{
  "questions": [
    {{
      "question": "Question text",
      "options": {{
        "A": "Option one",
        "B": "Option two",
        "C": "Option three",
        "D": "Option four"
      }},
      "correct_answer": "A",
      "explanation": "Why the answer is correct"
    }}
  ]
}}
Use scientifically accurate content. Exactly four options per question.
The correct_answer must be A, B, C, or D.
Do not claim these are historical past examination questions.
"""
            result = _ask_ai(prompt, email, exempt, count_as_tutor_question=False)
            if result:
                try:
                    cleaned = re.sub(
                        r"^\s*```(?:json)?|```\s*$",
                        "",
                        result.strip(),
                        flags=re.IGNORECASE,
                    )
                    parsed = json.loads(cleaned)
                    questions = parsed.get("questions", [])
                    if not questions:
                        raise ValueError("No questions returned.")
                    st.session_state[
                        f"practice_bank_{course_code}"
                    ] = questions
                    st.session_state[
                        f"practice_answers_{course_code}"
                    ] = {}
                    st.session_state[
                        f"practice_submitted_{course_code}"
                    ] = set()

                    if not _premium_or_exempt(email, exempt):
                        _consume_feature(
                            email, "practice_questions", len(questions)
                        )
                except (ValueError, TypeError, AttributeError):
                    st.error(
                        "The AI did not return a usable question set. "
                        "Please generate the questions again."
                    )

        bank_key = f"practice_bank_{course_code}"
        answers_key = f"practice_answers_{course_code}"
        submitted_key = f"practice_submitted_{course_code}"

        questions = st.session_state.get(bank_key, [])
        if questions:
            st.caption(
                f"{len(questions)} AI-generated practice questions · "
                "not verified historical past questions"
            )
            answers = st.session_state.setdefault(answers_key, {})
            submitted = st.session_state.setdefault(submitted_key, set())

            for i, item in enumerate(questions):
                st.markdown(f"**Question {i + 1}.** {item.get('question', '')}")
                options = item.get("options", {})
                labels = [
                    f"{letter}. {options[letter]}"
                    for letter in ["A", "B", "C", "D"]
                    if letter in options
                ]

                if not labels:
                    st.warning("This question has incomplete options.")
                    continue

                choice = st.radio(
                    f"Choose an answer for question {i + 1}",
                    labels,
                    key=f"practice_choice_{course_code}_{i}",
                    index=None,
                    label_visibility="collapsed",
                    disabled=i in submitted,
                )

                if i not in submitted and st.button(
                    "Check answer",
                    key=f"check_practice_{course_code}_{i}",
                ):
                    if not choice:
                        st.warning("Choose an answer first.")
                    else:
                        answers[i] = choice[0]
                        submitted.add(i)
                        st.rerun()

                if i in submitted:
                    correct = str(item.get("correct_answer", "")).strip().upper()
                    if answers.get(i) == correct:
                        st.success("Correct!")
                    else:
                        st.error(f"Correct answer: {correct}")
                    st.write(item.get("explanation", "No explanation supplied."))

                st.divider()

            if submitted:
                score = sum(
                    1
                    for i in submitted
                    if answers.get(i)
                    == str(questions[i].get("correct_answer", "")).strip().upper()
                )
                st.metric("Score so far", f"{score}/{len(submitted)} answered")

            if len(submitted) == len(questions):
                st.success(
                    f"Practice complete: {sum(1 for i in submitted if answers.get(i) == str(questions[i].get('correct_answer', '')).strip().upper())}/{len(questions)} correct."
                )

    with upload_tab:
        st.markdown("#### Ask Aloko about your document")
        upload = st.file_uploader(
            "Upload lecture notes, a past paper, or questions",
            type=["pdf", "docx", "txt"],
            key=f"learning_upload_{course_code}",
        )

        if upload:
            try:
                document_text = _read_upload(upload)
                if not document_text.strip():
                    st.warning(
                        "No readable text was found. This can happen with scanned PDFs."
                    )
                else:
                    st.caption(
                        f"Read {len(document_text):,} characters from {upload.name}. "
                        "Very long documents are shortened for this request."
                    )
                    task = st.selectbox(
                        "What should Aloko do?",
                        [
                            "Explain these notes",
                            "Summarise for revision",
                            "Answer questions from this document",
                            "Create practice questions from this document",
                        ],
                        key=f"upload_task_{course_code}",
                    )
                    instruction = st.text_area(
                        "Optional instruction or question",
                        key=f"upload_instruction_{course_code}",
                        placeholder="e.g. Explain question 3 step by step",
                    )

                    document_remaining = _remaining_feature(
                        email, "document_uploads", exempt
                    )
                    if document_remaining == 0 and not _premium_or_exempt(email, exempt):
                        st.warning(
                            "Your one free document analysis has been used. "
                            "Upgrade to Premium for more uploads."
                        )

                    if st.button(
                        "Analyse document",
                        key=f"analyse_upload_{course_code}",
                        disabled=(
                            document_remaining == 0
                            and not _premium_or_exempt(email, exempt)
                        ),
                    ):
                        prompt = f"""
Course: {course_code} — {course_title}; level {level}; {semester}.
Task: {task}.
Student instruction: {instruction or "Use the document content to complete the task."}

Use the supplied document as the main source. Distinguish what the document
says from additional scientific explanation. If the answer is not in the
document, say so. Do not invent page numbers or citations.

DOCUMENT TEXT:
{document_text[:16000]}
"""
                        result = _ask_ai(prompt, email, exempt, count_as_tutor_question=False)
                        if result:
                            st.session_state[
                                f"document_result_{course_code}"
                            ] = result
                            if not _premium_or_exempt(email, exempt):
                                _consume_feature(email, "document_uploads", 1)

                    saved_result = st.session_state.get(
                        f"document_result_{course_code}"
                    )
                    if saved_result:
                        st.markdown(saved_result)
                        st.download_button(
                            "Download analysis",
                            saved_result,
                            file_name="aloko_document_analysis.txt",
                            mime="text/plain",
                            key=f"download_document_{course_code}",
                        )
            except ValueError as exc:
                st.error(str(exc))

    with diagram_tab:
        st.markdown("#### Scientific diagrams and practical lessons")
        subject = st.text_input(
            "Topic",
            placeholder=(
                "e.g. bacterial cell structure, microscope parts, fungal "
                "structure, Gram staining"
            ),
            key=f"diagram_subject_{course_code}",
        )

        diagram_remaining = _remaining_feature(email, "diagrams", exempt)
        is_premium = _premium_or_exempt(email, exempt)
        disabled = diagram_remaining == 0 and not is_premium

        if disabled:
            st.warning(
                "Your free diagram/practical generation has been used. "
                "Upgrade to Premium for more."
            )

        diagram_col, practical_col = st.columns(2)

        with diagram_col:
            draw_diagram = st.button(
                "Draw Scientific Diagram",
                key=f"draw_scientific_diagram_{course_code}",
                disabled=disabled,
                use_container_width=True,
            )

        with practical_col:
            generate_practical = st.button(
                "Generate Practical Lesson",
                key=f"generate_practical_lesson_{course_code}",
                disabled=disabled,
                use_container_width=True,
            )

        if draw_diagram or generate_practical:
            if not subject.strip():
                st.warning("Enter a topic first.")
            else:
                if draw_diagram:
                    prompt = f"""
You are creating a scientifically accurate educational illustration for
HND Microbiology students.

TOPIC: {subject}
COURSE: {course_code} ? {course_title}
LEVEL: {level}; {semester}

Return a self-contained SVG image only. Do not return Markdown fences,
Graphviz DOT, HTML, JavaScript, or explanatory prose.

SVG requirements:
- Use an SVG viewBox of "0 0 900 620".
- Use a white background and clear, high-contrast lines.
- Draw the actual biological structure or scientific apparatus, not a
  collection of connected text boxes.
- Add a clear title and leader lines connecting structures to their labels.
- Make labels readable and avoid overlapping labels and lines.
- Include key scientifically relevant parts and preserve their correct
  relative arrangement as far as a teaching schematic permits.
- Use only basic SVG elements: svg, title, desc, rect, circle, ellipse,
  line, path, polygon, polyline, text, and g.
- Do not use scripts, event handlers, foreignObject, embedded images,
  external resources, links, or animation.
- If the topic is a compound light microscope, draw its recognizable
  side-view silhouette and label eyepiece, body tube/head, revolving
  nosepiece, objective lenses, stage, stage clips, condenser/diaphragm,
  light source, arm, coarse-focus knob, fine-focus knob, and base.
- For a topic that is not a physical structure, do not invent a misleading
  anatomical drawing. Instead create a clear labelled scientific schematic
  appropriate to the topic.
"""
                else:
                    prompt = f"""
Prepare a clear practical teaching lesson for HND Microbiology students.

Topic: {subject}
Course: {course_code} ? {course_title}
Level: {level}; {semester}

Use these headings:
1. Aim
2. Learning objectives
3. Principle or scientific background
4. Apparatus and materials
5. Method or procedure
6. Expected observations
7. Interpretation of results
8. Precautions and common errors
9. Waste disposal and biosafety
10. Review questions with answers

Be scientifically accurate. Distinguish expected results from guaranteed
results. Do not recommend unsafe handling, culturing, or exposure to
pathogens. For laboratory work, state that students must follow their
institution's approved SOP, risk assessment, and supervisor's instructions.
If a protocol depends on the organism or laboratory, explain that it varies.
Use readable Markdown.
"""

                # Use the built-in amoeba drawing directly so this topic
                # works even when the AI returns invalid SVG or no response.
                if draw_diagram and "amoeba" in subject.lower():
                    st.components.v1.html(
                        _amoeba_diagram_svg(),
                        height=620,
                        scrolling=True,
                    )
                    st.session_state[
                        f"learning_illustration_{course_code}"
                    ] = _amoeba_diagram_svg()
                    if not is_premium:
                        _consume_feature(email, "diagrams", 1)
                    st.stop()

                result = _ask_ai(
                    prompt,
                    email,
                    exempt,
                    count_as_tutor_question=False,
                )

                if result:
                    if draw_diagram:
                        # Extract the SVG even if the model adds Markdown fences
                        # or introductory text around it.
                        match = re.search(
                            r"<svg\b[^>]*>.*?</svg>",
                            result,
                            flags=re.IGNORECASE | re.DOTALL,
                        )
                        svg = match.group(0).strip() if match else ""

                        forbidden = re.search(
                            r"<\s*(script|foreignObject|iframe|object|embed)\b"
                            r"|\bon[\w:-]+\s*="
                            r"|javascript\s*:"
                            r"|(?:href|xlink:href)\s*="
                            r"|url\s*\(",
                            svg,
                            flags=re.IGNORECASE,
                        )

                        if "amoeba" in subject.lower():
                            st.info("Showing Aloko's built-in labelled amoeba diagram.")
                            st.components.v1.html(
                                _amoeba_diagram_svg(),
                                height=620,
                                scrolling=True,
                            )
                        elif svg and not forbidden and len(svg) <= 100_000:
                            st.components.v1.html(
                                svg,
                                height=650,
                                scrolling=True,
                            )
                        else:
                            st.error(
                                "The AI diagram could not be displayed. "
                                "Try 'amoeba' or a more specific scientific structure."
                            )
                    else:
                        st.markdown(result)

                    st.session_state[
                        f"learning_illustration_{course_code}"
                    ] = result

                    if not is_premium:
                        _consume_feature(email, "diagrams", 1)
