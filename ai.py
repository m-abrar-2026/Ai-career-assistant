import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(
    api_key=os.getenv("GROQ_API_KEY")
)

MODEL = os.getenv(
    "GROQ_MODEL",
    "openai/gpt-oss-20b"
)


def ask_ai(prompt):

    try:

        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.7,
            max_tokens=2000
        )

        return response.choices[0].message.content

    except Exception as e:

        return f"Error: {str(e)}"


def generate_cover_letter(
    company,
    role,
    resume_text
):

    prompt = f"""
Create a professional cover letter.

Company: {company}

Role: {role}

Resume:
{resume_text}

Make it concise and professional.
"""

    return ask_ai(prompt)


def generate_interview_questions(
    role,
    resume_text
):

    prompt = f"""
Based on this resume:

{resume_text}

Generate 10 interview questions for a
{role} position.

Include:

- Technical Questions
- Project Questions
- HR Questions

Number them properly.
"""

    return ask_ai(prompt)


def improve_resume(
    resume_text
):

    prompt = f"""
Analyze this resume and provide:

1. Strengths
2. Weaknesses
3. Missing Skills
4. Improvement Suggestions
5. Career Recommendations

Resume:

{resume_text}
"""

    return ask_ai(prompt)


def career_recommendations(
    resume_text
):

    prompt = f"""
Analyze this resume and provide:

1. Current Skills
2. Missing Skills
3. Recommended Career Paths
4. Learning Roadmap
5. Certifications To Pursue

Resume:

{resume_text}
"""

    return ask_ai(prompt)


def jd_match(
    resume_text,
    job_description
):

    prompt = f"""
Compare this resume with the job description.

Resume:
{resume_text}

Job Description:
{job_description}

Provide:

1. Match Percentage
2. Matching Skills
3. Missing Skills
4. Suggestions To Improve Match
"""

    return ask_ai(prompt)