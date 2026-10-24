import json
import os
import re
from groq import Groq

MODEL = os.getenv("UNIBEN_AI_MODEL", "llama-3.3-70b-versatile")

COURSES = {
    "PHY101": "General Physics I",
    "PHY103": "General Physics II",
    "PHY104": "Physics",
    "CHM101": "General Chemistry",
    "CHM107": "General Chemistry",
    "MTH101": "Mathematics",
    "MTH102": "Mathematics",
    "BIO101": "Biology",
    "BOT101": "Botany",
    "ZOO101": "Zoology",
    "CSC101": "Computer Science",
    "CSC102": "Computer Science",
    "MEE121": "Engineering",
    "STA112": "Statistics",
    "GST101": "Use of English",
    "GST102": "Nigerian Peoples and Culture",
}


def _extract_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("AI did not return valid JSON.")
    return json.loads(text[start:end + 1])


def generate_questions(course, topic, count=5, difficulty="university beginner"):
    """
    Generate NEW practice questions. These are never represented as
    genuine historical exam questions.
    """
    course = course.upper().strip()
    if course not in COURSES:
        raise ValueError(f"Unsupported course: {course}")
    if not topic.strip():
        raise ValueError("Enter a topic.")
    if not 1 <= count <= 12:
        raise ValueError("Generate between 1 and 12 questions per request.")

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not configured in the environment.")

    client = Groq(api_key=api_key)
    prompt = f"""
Create {count} original university-level multiple-choice practice questions.

Course: {course} — {COURSES[course]}
Topic: {topic}
Difficulty: {difficulty}

Return ONLY a JSON object:
{{
  "course": "{course}",
  "topic": "...",
  "origin": "AI-generated practice",
  "questions": [
    {{
      "question": "...",
      "options": {{"A":"...", "B":"...", "C":"...", "D":"..."}},
      "correct_option": "A",
      "explanation": "Step-by-step or clear explanation"
    }}
  ]
}}

Requirements:
- These must be newly authored practice questions, not claimed as past exam questions.
- Exactly four distinct options per question and one correct option.
- Ensure every answer key matches the question and explanation.
- For calculations, solve independently and include units where needed.
- Do not invent references to UNIBEN exams or historical sessions.
- No repeated questions.
- If a question cannot be answered confidently, replace it.
"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You create accurate educational practice questions. "
                    "Follow the requested JSON schema exactly."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )

    data = _extract_json(response.choices[0].message.content)
    questions = data.get("questions", [])

    if len(questions) != count:
        raise ValueError(f"Expected {count} questions; received {len(questions)}.")

    for index, q in enumerate(questions, start=1):
        options = q.get("options")
        key = q.get("correct_option")
        if (
            not isinstance(q.get("question"), str)
            or not q["question"].strip()
            or not isinstance(options, dict)
            or set(options.keys()) != {"A", "B", "C", "D"}
            or any(not isinstance(v, str) or not v.strip() for v in options.values())
            or key not in {"A", "B", "C", "D"}
            or not isinstance(q.get("explanation"), str)
            or not q["explanation"].strip()
        ):
            raise ValueError(f"Question {index} failed format validation.")

        q["course"] = course
        q["topic"] = topic
        q["question_origin"] = "ai_generated"
        q["verified"] = False
        q["active"] = False

    return data


if __name__ == "__main__":
    course = input("Course code (e.g. PHY101): ").strip()
    topic = input("Topic: ").strip()
    count_text = input("Number of questions (1-12, default 5): ").strip()
    count = int(count_text) if count_text else 5

    result = generate_questions(course, topic, count)
    filename = f"uniben_ai_{course.upper()}_review.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Saved draft: {filename}")
    print("Status: AI-generated, not verified, not published to student quizzes.")
