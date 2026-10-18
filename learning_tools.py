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
            "What should Aloko illustrate or teach?",
            placeholder=(
                "e.g. labelled bacterial cell, Gram staining, microscope parts, "
                "fungal structure"
            ),
            key=f"diagram_subject_{course_code}",
        )
        diagram_kind = st.radio(
            "Learning format",
            ["Labelled diagram", "Practical lesson", "Both"],
            horizontal=True,
            key=f"diagram_kind_{course_code}",
        )

        diagram_remaining = _remaining_feature(email, "diagrams", exempt)
        if diagram_remaining == 0 and not _premium_or_exempt(email, exempt):
            st.warning(
                "Your one free diagram/practical generation has been used. "
                "Upgrade to Premium for more."
            )

        if st.button(
            "Create learning illustration",
            key=f"create_diagram_{course_code}",
            disabled=(
                diagram_remaining == 0
                and not _premium_or_exempt(email, exempt)
            ),
        ):
            if not subject.strip():
                st.warning("Enter a topic first.")
            else:
                if diagram_kind == "Labelled diagram":
                    prompt = f"""
Create a clear labelled educational diagram about: {subject}.
Return Graphviz DOT source only, beginning with digraph and ending with }}.
Use simple node labels, arrows, and a top-to-bottom layout.
Keep labels concise and scientifically accurate. Do not include external
URLs, images, file paths, or executable commands.
"""
                else:
                    prompt = f"""
Prepare a practical teaching guide about {subject} for {course_title},
{level}, HND Microbiology. Include:
1. Aim
2. Relevant principle
3. Apparatus/materials
4. Numbered procedure
5. Expected observations and interpretation
6. Precautions, biosafety, and waste disposal
7. Common errors and review questions.
Do not recommend unsafe handling of pathogens. Where conditions vary by
organism or laboratory protocol, say so and refer students to their approved
institutional SOP and supervisor.
"""
                    if diagram_kind == "Both":
                        prompt += (
                            "\nAlso include a simple labelled text diagram using "
                            "Markdown or an ASCII schematic where useful."
                        )

                result = _ask_ai(prompt, email, exempt, count_as_tutor_question=False)
                if result:
                    if diagram_kind == "Labelled diagram":
                        dot = result.strip()
                        dot = re.sub(
                            r"^\s*```(?:dot|graphviz)?|```\s*$",
                            "",
                            dot,
                            flags=re.IGNORECASE,
                        ).strip()
                        if dot.startswith("digraph") or dot.startswith("graph"):
                            try:
                                st.graphviz_chart(dot)
                            except Exception:
                                st.warning("The diagram could not be rendered. Showing its source instead.")
                                st.code(dot, language="dot")
                        else:
                            st.markdown(result)
                            st.caption("The model did not return valid diagram source.")
                    else:
                        st.markdown(result)
                    st.session_state[
                        f"learning_illustration_{course_code}"
                    ] = result
                    if not _premium_or_exempt(email, exempt):
                        _consume_feature(email, "diagrams", 1)
