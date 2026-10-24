import json
import os
import re
from groq import Groq

MODEL = os.getenv("UNIBEN_AI_MODEL", "openai/gpt-oss-120b")

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
    if not text:
        raise ValueError("The AI returned an empty response.")

    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("The AI response contained incomplete JSON.")

    return json.loads(text[start:end + 1])


def generate_questions(course, topic, count=5, difficulty="university beginner"):
    """Generate original AI practice questions, not verified historical questions."""
    course = course.upper().strip()
    topic = topic.strip()

    if course not in COURSES:
        raise ValueError(f"Unsupported course: {course}")
    if not topic:
        raise ValueError("Enter a topic.")
    if not 1 <= count <= 12:
        raise ValueError("Generate between 1 and 12 questions per request.")

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not configured in the environment.")

    client = Groq(api_key=api_key)

    prompt = f"""
Create exactly {count} original multiple-choice practice questions.

Course: {course} — {COURSES[course]}
Topic: {topic}
Difficulty: {difficulty}

Return one valid JSON object with this schema:
{{
  "course": "{course}",
  "topic": "{topic}",
  "origin": "AI-generated practice",
  "questions": [
    {{
      "question": "Question text",
      "options": {{
        "A": "Option A",
        "B": "Option B",
        "C": "Option C",
        "D": "Option D"
      }},
      "correct_option": "A",
      "explanation": "Brief explanation"
    }}
  ]
}}

Rules:
- Return JSON only, with no Markdown or surrounding text.
- Include exactly {count} questions and four distinct options per question.
- Use one correct answer and an accurate, concise explanation per question.
- Keep question text, options, and explanations concise.
- Ensure calculations and units are correct where applicable.
- Do not claim questions are historical UNIBEN past questions.
- Do not repeat questions.
"""

    last_error = None

    for attempt in range(2):
        current_prompt = prompt
        max_tokens = 6000

        if attempt == 1:
            current_prompt += (
                "\nRetry: produce the complete JSON now. Keep all explanations "
                "to one short sentence and do not add any extra fields."
            )
            max_tokens = 8000

        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You generate accurate educational practice questions. "
                            "Return complete, valid JSON matching the requested schema."
                        ),
                    },
                    {"role": "user", "content": current_prompt},
                ],
                temperature=0.2,
                max_completion_tokens=max_tokens,
                response_format={"type": "json_object"},
            )

            choice = response.choices[0]
            if choice.finish_reason == "length":
                raise ValueError(
                    "The AI response reached its token limit before completing JSON."
                )

            data = _extract_json(choice.message.content)
            questions = data.get("questions", [])

            if not isinstance(questions, list) or len(questions) != count:
                raise ValueError(
                    f"Expected {count} questions; received "
                    f"{len(questions) if isinstance(questions, list) else 'invalid data'}."
                )

            for index, question in enumerate(questions, start=1):
                options = question.get("options")
                key = question.get("correct_option")

                if (
                    not isinstance(question.get("question"), str)
                    or not question["question"].strip()
                    or not isinstance(options, dict)
                    or set(options.keys()) != {"A", "B", "C", "D"}
                    or any(
                        not isinstance(value, str) or not value.strip()
                        for value in options.values()
                    )
                    or key not in {"A", "B", "C", "D"}
                    or not isinstance(question.get("explanation"), str)
                    or not question["explanation"].strip()
                ):
                    raise ValueError(
                        f"Question {index} failed format validation."
                    )

                question["course"] = course
                question["topic"] = topic
                question["question_origin"] = "ai_generated"
                question["verified"] = False
                question["active"] = False

            data["course"] = course
            data["topic"] = topic
            data["origin"] = "AI-generated practice"
            return data

        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt == 1:
                break

    raise RuntimeError(
        f"Could not generate complete valid questions after two attempts: {last_error}"
    )


if __name__ == "__main__":
    course = input("Course code (e.g. PHY101): ").strip()
    topic = input("Topic: ").strip()
    count_text = input("Number of questions (1-12, default 5): ").strip()
    count = int(count_text) if count_text else 5

    result = generate_questions(course, topic, count)
    filename = f"uniben_ai_{course.upper()}_review.json"

    with open(filename, "w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)

    print(f"Saved draft: {filename}")
    print("Status: AI-generated, not verified, not published to student quizzes.")
