import os
import re
from datetime import date, datetime, timedelta
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    session,
    send_from_directory,
    flash,
    send_file,
    url_for
)
from flask_mail import Mail, Message
from dotenv import load_dotenv
from PyPDF2 import PdfReader
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from sqlalchemy import func
from werkzeug.utils import secure_filename
from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from db import SessionLocal, engine, Base
from models import (
    User,
    Job,
    Resume,
    Activity,
    Notification
)
from ai import (
    career_recommendations,
    generate_cover_letter,
    generate_interview_questions,
    improve_resume
)

load_dotenv()


def create_notification(db, user_id, message):
    notification = Notification(
        user_id=user_id,
        message=message
    )
    db.add(notification)
    db.commit()


app = Flask(__name__)

app.secret_key = "secretkey0926"

UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 587
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_USERNAME")

mail = Mail(app)


def send_interview_email(email, company, role, interview_date):
    if not app.config["MAIL_USERNAME"] or not app.config["MAIL_PASSWORD"]:
        print("Email not sent: MAIL_USERNAME or MAIL_PASSWORD is missing in .env")
        return False

    try:
        days_left = (interview_date - date.today()).days
        if days_left == 0:
            timing_text = "TODAY"
        elif days_left == 1:
            timing_text = "TOMORROW"
        else:
            timing_text = f"in {days_left} days"

        msg = Message(
            subject=f"Interview Reminder: {company} ({role}) is {timing_text}!",
            sender=app.config["MAIL_USERNAME"],
            recipients=[email]
        )

        msg.body = f"""Hello,

This is your automatic interview reminder from AI Career Copilot.

Company: {company}
Role: {role}
Interview Date: {interview_date} ({timing_text})

Make sure to review your resume and practice your interview questions on your dashboard. Best of luck!

AI Career Copilot
"""
        mail.send(msg)
        print(f"✅ Interview reminder email sent to {email} for {company}")
        return True
    except Exception as e:
        print(f"❌ Failed to send interview email: {e}")
        return False


def check_and_send_interview_reminders(db, user_id):
    today = date.today()

    missing_date_jobs = (
        db.query(Job)
        .filter(Job.user_id == user_id)
        .filter(Job.status == "Interview")
        .filter(Job.interview_date == None)
        .all()
    )
    for job in missing_date_jobs:
        job.interview_date = today + timedelta(days=1)
    if missing_date_jobs:
        db.commit()

    upcoming_interviews = (
        db.query(Job)
        .filter(Job.user_id == user_id)
        .filter(Job.interview_date != None)
        .filter(Job.interview_date >= today)
        .order_by(Job.interview_date)
        .all()
    )

    user = db.query(User).filter(User.id == user_id).first()

    for job in upcoming_interviews:
        job_date = (
            job.interview_date.date()
            if isinstance(job.interview_date, datetime)
            else job.interview_date
        )
        job.days_left = (job_date - today).days

        if 0 <= job.days_left <= 3:
            message = f"Upcoming Interview: {job.company} ({job.role}) on {job_date}"

            existing = (
                db.query(Notification)
                .filter(Notification.user_id == user_id)
                .filter(Notification.message == message)
                .first()
            )

            if not existing:
                create_notification(db, user_id, message)
                if user and user.email:
                    send_interview_email(
                        user.email,
                        job.company,
                        job.role,
                        job_date
                    )

    return upcoming_interviews


Base.metadata.create_all(bind=engine)


def calculate_ats_score(text):
    if text is None:
        text = ""

    text = text.lower()

    skills = [
        "python",
        "flask",
        "mysql",
        "html",
        "css",
        "javascript",
        "react",
        "docker",
        "aws"
    ]

    found_skills = []
    score = 0

    for skill in skills:
        if skill in text:
            found_skills.append(skill)
            score += 100 // len(skills)

    score = min(score, 100)

    missing_skills = [
        skill for skill in skills
        if skill not in found_skills
    ]

    return score, found_skills, missing_skills


def clean_markdown_for_pdf(text):
    if not text:
        return ""
    text = re.sub(r'<br\s*/?>', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'\*\*', '', text)
    text = re.sub(r'\*', '', text)
    text = re.sub(r'#+\s', '', text)
    text = text.replace('|', ' ')
    text = text.replace('---', '')
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r'[ \t]+', ' ', text)
    return text


@app.route("/signup", methods=["GET", "POST"])
def signup():
    db = SessionLocal()

    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        existing = (
            db.query(User)
            .filter(User.email == email)
            .first()
        )

        if existing:
            flash("Email already exists", "error")
            return redirect("/signup")

        user = User(
            email=email,
            password=generate_password_hash(password)
        )

        db.add(user)
        db.commit()

        flash("Account created! Please login.", "success")
        return redirect("/")

    return render_template("signup.html")


@app.route("/", methods=["GET", "POST"])
def login():
    db = SessionLocal()

    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        user = (
            db.query(User)
            .filter(User.email == email)
            .first()
        )

        if not user:
            flash("Invalid email! No account found with this email.", "error")
            return redirect("/")

        if not check_password_hash(user.password, password):
            flash("Invalid password! Please try again.", "error")
            return redirect("/")

        session["user_id"] = user.id
        return redirect("/dashboard")

    return render_template("login.html")


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    db = SessionLocal()
    error = None

    if request.method == "POST":
        email = request.form.get("email")

        user = (
            db.query(User)
            .filter(User.email == email)
            .first()
        )

        if not user:
            error = "No account found with that email address."
        else:
            session["reset_email"] = user.email
            return redirect("/reset-password")

    return render_template("forgot_password.html", error=error)


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if "reset_email" not in session:
        return redirect("/forgot-password")

    db = SessionLocal()

    if request.method == "POST":
        new_password = request.form.get("password")

        user = (
            db.query(User)
            .filter(User.email == session["reset_email"])
            .first()
        )

        if user:
            user.password = generate_password_hash(new_password)
            db.commit()

        session.pop("reset_email", None)
        flash("Password reset successfully! Please login.", "success")
        return redirect("/")

    return render_template("reset_password.html")


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()

    jobs = (
        db.query(Job)
        .filter(Job.user_id == session["user_id"])
        .all()
    )

    resumes_count = db.query(Resume).filter(Resume.user_id == session["user_id"]).count()

    total = len(jobs)
    applied = len([j for j in jobs if j.status == "Applied"])
    interviews = len([j for j in jobs if j.status == "Interview"])
    offers = len([j for j in jobs if j.status == "Offer"])
    rejected = len([j for j in jobs if j.status == "Rejected"])

    has_resume = resumes_count > 0
    has_jobs = total > 0
    has_interviews = interviews > 0

    progress_score = min(100, (resumes_count * 30) + (total * 15) + (interviews * 20))

    upcoming_interviews = check_and_send_interview_reminders(
        db,
        session["user_id"]
    )

    notifications = (
        db.query(Notification)
        .filter(Notification.user_id == session["user_id"])
        .order_by(Notification.id.desc())
        .limit(5)
        .all()
    )

    activities = (
        db.query(Activity)
        .filter(Activity.user_id == session["user_id"])
        .order_by(Activity.id.desc())
        .limit(5)
        .all()
    )

    return render_template(
        "dashboard.html",
        total=total,
        applied=applied,
        interviews=interviews,
        offers=offers,
        rejected=rejected,
        jobs=jobs,
        progress_score=progress_score,
        upcoming_interviews=upcoming_interviews,
        notifications=notifications,
        activities=activities,
        has_resume=has_resume,
        has_jobs=has_jobs,
        has_interviews=has_interviews
    )


@app.route("/add-job", methods=["GET", "POST"])
def add_job():
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()

    if request.method == "POST":
        company = request.form.get("company", "Unknown")
        role = request.form.get("role", "Unknown")
        status = request.form.get("status", "Applied")

        applied_date_str = request.form.get("applied_date")
        if applied_date_str:
            try:
                applied_date = datetime.strptime(applied_date_str, "%Y-%m-%d").date()
            except ValueError:
                applied_date = date.today()
        else:
            applied_date = date.today()

        interview_date_str = request.form.get("interview_date")
        if interview_date_str:
            try:
                interview_date = datetime.strptime(interview_date_str, "%Y-%m-%d").date()
            except ValueError:
                interview_date = None
        elif status == "Interview":
            interview_date = date.today() + timedelta(days=1)
        else:
            interview_date = None

        notes = request.form.get("notes", "")

        job = Job(
            user_id=session["user_id"],
            company=company,
            role=role,
            status=status,
            applied_date=applied_date,
            interview_date=interview_date,
            notes=notes
        )

        db.add(job)
        db.commit()

        check_and_send_interview_reminders(db, session["user_id"])
        flash("Job added successfully!", "success")

        return redirect("/jobs")

    return render_template("add_job.html")


@app.route("/jobs")
def jobs():
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    search = request.args.get("search")

    query = (
        db.query(Job)
        .filter(Job.user_id == session["user_id"])
    )

    if search:
        query = query.filter(Job.company.contains(search))

    jobs = query.order_by(Job.applied_date.desc()).all()

    return render_template(
        "jobs.html",
        jobs=jobs
    )


@app.route("/delete-job/<int:id>")
def delete_job(id):
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    job = db.query(Job).get(id)

    if job:
        db.delete(job)
        db.commit()
        flash("Job removed successfully!", "success")

    return redirect("/jobs")


@app.route("/edit-job/<int:id>", methods=["GET", "POST"])
def edit_job(id):
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    job = db.query(Job).get(id)

    if request.method == "POST":
        job.status = request.form["status"]

        interview_date_str = request.form.get("interview_date")
        if interview_date_str:
            job.interview_date = datetime.strptime(
                interview_date_str,
                "%Y-%m-%d"
            ).date()
        elif job.status == "Interview" and not job.interview_date:
            job.interview_date = date.today() + timedelta(days=1)

        db.commit()
        check_and_send_interview_reminders(db, session["user_id"])
        flash("Job updated successfully!", "success")

        return redirect("/jobs")

    return render_template(
        "edit_job.html",
        job=job
    )


@app.route("/upload-resume", methods=["GET", "POST"])
def upload_resume():
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()

    if request.method == "POST":
        file = request.files["resume"]

        if file.filename == "":
            return "No file selected"

        filename = secure_filename(file.filename)
        filepath = os.path.join(
            app.config["UPLOAD_FOLDER"],
            filename
        )
        file.save(filepath)

        reader = PdfReader(filepath)
        resume_text = ""

        for page in reader.pages:
            text = page.extract_text()
            if text:
                resume_text += text

        score, skills_found, missing_skills = calculate_ats_score(resume_text)

        resume = Resume(
            user_id=session["user_id"],
            filename=filename,
            ats_score=score,
            resume_text=resume_text
        )

        db.add(resume)
        db.commit()

        create_notification(
            db,
            session["user_id"],
            "Resume uploaded successfully"
        )
        activity = Activity(
            user_id=session["user_id"],
            action="Uploaded Resume"
        )

        db.add(activity)
        db.commit()
        flash("Resume uploaded successfully!", "success")

        return redirect("/my-resumes")

    return render_template("upload_resume.html")


@app.route("/my-resumes")
def my_resumes():
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()

    resumes = (
        db.query(Resume)
        .filter(Resume.user_id == session["user_id"])
        .all()
    )

    return render_template(
        "my_resumes.html",
        resumes=resumes
    )


@app.route("/jd-match/<int:id>", methods=["GET", "POST"])
def jd_match(id):
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()

    resume = (
        db.query(Resume)
        .filter(Resume.id == id)
        .first()
    )

    if request.method == "POST":
        jd = request.form["job_description"]

        resume_text = resume.resume_text.lower()
        jd = jd.lower()

        skills = [
            "python",
            "flask",
            "mysql",
            "sql",
            "html",
            "css",
            "javascript",
            "react",
            "docker",
            "aws",
            "git",
            "github",
            "api",
            "machine learning",
            "data science"
        ]

        matched = []
        missing = []

        for skill in skills:
            if skill in jd:
                if skill in resume_text:
                    matched.append(skill)
                else:
                    missing.append(skill)

        if len(matched) + len(missing) > 0:
            score = int(
                (len(matched) / (len(matched) + len(missing))) * 100
            )
        else:
            score = 0

        return render_template(
            "jd_result.html",
            score=score,
            matched=matched,
            missing=missing
        )

    activity = Activity(
        user_id=session["user_id"],
        action="Performed JD Match Analysis"
    )

    db.add(activity)
    db.commit()

    return render_template(
        "jd_match.html",
        resume=resume
    )


@app.route("/resume/<int:id>")
def resume_details(id):
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()

    resume = (
        db.query(Resume)
        .filter(Resume.id == id)
        .first()
    )

    score, skills_found, missing_skills = calculate_ats_score(
        resume.resume_text
    )

    create_notification(
        db,
        session["user_id"],
        "JD Match Analysis Completed"
    )

    return render_template(
        "resume_details.html",
        resume=resume,
        score=score,
        skills_found=skills_found,
        missing_skills=missing_skills
    )


@app.route("/cover-letter/<int:id>", methods=["GET", "POST"])
def cover_letter(id):
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()

    resume = (
        db.query(Resume)
        .filter(Resume.id == id)
        .first()
    )

    if request.method == "POST":
        company = request.form["company"]
        role = request.form["role"]

        letter = clean_markdown_for_pdf(generate_cover_letter(
            company,
            role,
            resume.resume_text
        ))

        create_notification(
            db,
            session["user_id"],
            "Cover Letter Generated"
        )
        activity = Activity(
            user_id=session["user_id"],
            action="Generated Cover Letter"
        )

        db.add(activity)
        db.commit()

        return render_template(
            "cover_letter_result.html",
            letter=letter
        )

    return render_template("cover_letter.html")


@app.route("/interview/<int:id>", methods=["GET", "POST"])
def interview_questions(id):
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()

    resume = (
        db.query(Resume)
        .filter(Resume.id == id)
        .first()
    )

    if request.method == "POST":
        role = request.form["role"]

        questions = generate_interview_questions(
            role,
            resume.resume_text
        )

        questions = clean_markdown_for_pdf(questions)

        create_notification(
            db,
            session["user_id"],
            "Interview Questions Generated"
        )
        activity = Activity(
            user_id=session["user_id"],
            action="Generated Interview Questions"
        )

        db.add(activity)
        db.commit()

        return render_template(
            "interview_result.html",
            questions=questions
        )

    return render_template("interview.html")


@app.route("/resume-feedback/<int:id>")
def resume_feedback(id):
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()

    resume = (
        db.query(Resume)
        .filter(Resume.id == id)
        .first()
    )

    feedback = clean_markdown_for_pdf(improve_resume(resume.resume_text))

    create_notification(
        db,
        session["user_id"],
        "AI Resume Feedback Generated"
    )
    activity = Activity(
        user_id=session["user_id"],
        action="Generated Resume Feedback"
    )

    db.add(activity)
    db.commit()

    return render_template(
        "resume_feedback.html",
        feedback=feedback
    )


@app.route("/career-advice/<int:id>")
def career_advice(id):
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()

    resume = (
        db.query(Resume)
        .filter(Resume.id == id)
        .first()
    )

    advice = clean_markdown_for_pdf(career_recommendations(resume.resume_text))

    create_notification(
        db,
        session["user_id"],
        "Career Recommendations Generated"
    )
    activity = Activity(
        user_id=session["user_id"],
        action="Generated Career Recommendations"
    )

    db.add(activity)
    db.commit()

    return render_template(
        "career_advice.html",
        advice=advice
    )


@app.route("/download-report/<int:id>")
def download_report(id):
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()

    resume = (
        db.query(Resume)
        .filter(Resume.id == id)
        .first()
    )

    if not resume:
        return "Resume not found"

    resume_text = resume.resume_text or ""

    score, skills_found, missing_skills = calculate_ats_score(resume_text)
    feedback = clean_markdown_for_pdf(improve_resume(resume_text))
    advice = clean_markdown_for_pdf(career_recommendations(resume_text))

    filename = f"career_report_{id}.pdf"
    pdf_path = os.path.join("static", filename)

    c = canvas.Canvas(pdf_path, pagesize=letter)

    def draw_wrapped_text(text_block, start_y, title):
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, start_y, title)
        start_y -= 22

        c.setFont("Helvetica", 10)
        y = start_y

        for paragraph in text_block.split("\n"):
            if not paragraph.strip():
                continue

            words = paragraph.strip().split(" ")
            current_line = ""
            for word in words:
                test_line = current_line + " " + word if current_line else word
                if len(test_line) > 85:
                    if y < 60:
                        c.showPage()
                        c.setFont("Helvetica", 10)
                        y = 750
                    c.drawString(50, y, current_line)
                    y -= 15
                    current_line = word
                else:
                    current_line = test_line
            if current_line:
                if y < 60:
                    c.showPage()
                    c.setFont("Helvetica", 10)
                    y = 750
                c.drawString(50, y, current_line)
                y -= 15
            y -= 8
        return y

    y = 750
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, y, "AI Career Assistant Report")
    y -= 35

    c.setFont("Helvetica", 12)
    c.drawString(50, y, f"Resume File: {resume.filename}")
    y -= 22
    c.drawString(50, y, f"ATS Score: {score}/100")
    y -= 35

    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, "Skills Found")
    y -= 22
    c.setFont("Helvetica", 11)
    for skill in skills_found:
        c.drawString(70, y, f"- {skill}")
        y -= 16

    y -= 15
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, "Missing Skills")
    y -= 22
    c.setFont("Helvetica", 11)
    for skill in missing_skills:
        c.drawString(70, y, f"- {skill}")
        y -= 16

    c.showPage()
    y = 750
    y = draw_wrapped_text(feedback, y, "Resume Feedback")

    c.showPage()
    y = 750
    y = draw_wrapped_text(advice, y, "Career Recommendations")

    c.save()

    create_notification(
        db,
        session["user_id"],
        "PDF Career Report Downloaded"
    )

    return send_file(pdf_path, as_attachment=True)


@app.route("/view-resume/<int:id>")
def view_resume(id):
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()

    resume = (
        db.query(Resume)
        .filter(Resume.id == id)
        .first()
    )

    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        resume.filename
    )


@app.route("/profile")
def profile():
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    user = db.query(User).filter(User.id == session["user_id"]).first()

    total_jobs = db.query(Job).filter(Job.user_id == session["user_id"]).count()
    total_resumes = db.query(Resume).filter(Resume.user_id == session["user_id"]).count()
    total_notifications = db.query(Notification).filter(Notification.user_id == session["user_id"]).count()

    resumes = db.query(Resume).filter(Resume.user_id == session["user_id"]).all()

    return render_template(
        "profile.html",
        user=user,
        total_jobs=total_jobs,
        total_resumes=total_resumes,
        total_notifications=total_notifications,
        resumes=resumes
    )


@app.route("/test-notification")
def test_notification():
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()

    note = Notification(
        user_id=session["user_id"],
        message="Welcome to AI Career Assistant"
    )

    db.add(note)
    db.commit()

    flash("Test notification created successfully!", "success")
    return redirect("/dashboard")


@app.route("/test-email")
def test_email():
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    user = db.query(User).filter(User.id == session["user_id"]).first()

    success = send_interview_email(
        user.email,
        "Google",
        "Software Engineer",
        date.today() + timedelta(days=1)
    )

    if success:
        message = f"Test email successfully sent to {user.email}! Check your inbox."
        status = "success"
    else:
        message = "Failed to send email. Check your terminal for errors and verify MAIL_USERNAME and MAIL_PASSWORD in your .env file."
        status = "error"

    return render_template(
        "test_email_result.html",
        message=message,
        status=status
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/delete-resume/<int:id>")
def delete_resume(id):
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    resume = db.query(Resume).filter(Resume.id == id, Resume.user_id == session["user_id"]).first()

    if resume:
        try:
            file_path = os.path.join(app.config["UPLOAD_FOLDER"], resume.filename)
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            print(f"Error deleting file: {e}")

        db.delete(resume)
        db.commit()
        flash("Resume deleted successfully!", "success")

    return redirect("/my-resumes")


@app.route("/clear-notifications")
def clear_notifications():
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    db.query(Notification).filter(Notification.user_id == session["user_id"]).delete()
    db.commit()

    flash("Notifications cleared!", "success")
    return redirect("/dashboard")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)