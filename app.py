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
from flask_login import login_required, current_user
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

app = Flask(__name__)

app.secret_key = os.getenv("SECRET_KEY", "secretkey0926")

UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT", 587))
app.config["MAIL_USE_TLS"] = os.getenv("MAIL_USE_TLS", "True").lower() in ("true", "1", "yes")
app.config["MAIL_USE_SSL"] = os.getenv("MAIL_USE_SSL", "False").lower() in ("true", "1", "yes")
app.config["MAIL_USERNAME"] = (os.getenv("MAIL_USERNAME") or "").strip()
raw_password = os.getenv("MAIL_PASSWORD") or ""
app.config["MAIL_PASSWORD"] = re.sub(r"\s+", "", raw_password)
app.config["MAIL_DEFAULT_SENDER"] = app.config["MAIL_USERNAME"]
app.config["MAIL_TIMEOUT"] = 10

mail = Mail(app)

Base.metadata.create_all(bind=engine)


@app.teardown_appcontext
def shutdown_session(exception=None):
    pass


def create_notification(db, user_id, message):
    try:
        notification = Notification(
            user_id=user_id,
            message=message
        )
        db.add(notification)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Error creating notification: {e}")


def send_interview_email(email, company, role, interview_date, user_id=None):
    # Check if user has explicitly enabled emails if user_id is available
    if user_id:
        db_check = SessionLocal()
        try:
            u = db_check.query(User).filter(User.id == user_id).first()
            if u and not u.email_enabled:
                print(f"Email not sent: User {user_id} has disabled email notifications.")
                return False
        finally:
            db_check.close()

    if not app.config.get("MAIL_USERNAME") or not app.config.get("MAIL_PASSWORD"):
        print("Email not sent: MAIL_USERNAME or MAIL_PASSWORD is missing.")
        return False

    if not email:
        print("Email not sent: Recipient email address is missing or empty.")
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
        print(f"Interview reminder email sent to {email} for {company}")
        return True
    except Exception as e:
        print(f"Failed to send interview email: {e}")
        return False

def check_and_send_interview_reminders(db, user_id):
    today = date.today()

    try:
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
                    if user and user.email and user.email_enabled:
                        try:
                            send_interview_email(
                                user.email,
                                job.company,
                                job.role,
                                job_date,
                                user_id=user_id
                            )
                        except Exception as mail_err:
                            print(f"Skipping email dispatch: {mail_err}")

        return upcoming_interviews
    except Exception as e:
        print(f"Error checking interview reminders: {e}")
        return []


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
    try:
        if request.method == "POST":
            email = request.form.get("email", "").strip()
            password = request.form.get("password", "")

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
                password=generate_password_hash(password),
                email_enabled=False  # Off by default
            )

            db.add(user)
            db.commit()

            flash("Account created! Please login.", "success")
            return redirect("/")

        return render_template("signup.html")
    finally:
        db.close()


@app.route("/", methods=["GET", "POST"])
def login():
    db = SessionLocal()
    try:
        if request.method == "POST":
            email = request.form.get("email", "").strip()
            password = request.form.get("password", "")

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
    finally:
        db.close()


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    db = SessionLocal()
    error = None
    try:
        if request.method == "POST":
            email = request.form.get("email", "").strip()

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
    finally:
        db.close()


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if "reset_email" not in session:
        return redirect("/forgot-password")

    db = SessionLocal()
    try:
        if request.method == "POST":
            new_password = request.form.get("password", "")

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
    finally:
        db.close()


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    try:
        user_id = session["user_id"]
        jobs = (
            db.query(Job)
            .filter(Job.user_id == user_id)
            .all()
        )

        resumes_count = db.query(Resume).filter(Resume.user_id == user_id).count()

        total = len(jobs)
        applied = len([j for j in jobs if j.status == "Applied"])
        interviews = len([j for j in jobs if j.status == "Interview"])
        offers = len([j for j in jobs if j.status == "Offer"])
        rejected = len([j for j in jobs if j.status == "Rejected"])

        has_resume = resumes_count > 0
        has_jobs = total > 0
        has_interviews = interviews > 0

        progress_score = min(100, (resumes_count * 30) + (total * 15) + (interviews * 20))

        upcoming_interviews = check_and_send_interview_reminders(db, user_id)

        notifications = (
            db.query(Notification)
            .filter(Notification.user_id == user_id)
            .order_by(Notification.id.desc())
            .limit(5)
            .all()
        )

        activities = (
            db.query(Activity)
            .filter(Activity.user_id == user_id)
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
    finally:
        db.close()


@app.route("/add-job", methods=["GET", "POST"])
def add_job():
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    try:
        if request.method == "POST":
            company = request.form.get("company", "Unknown").strip()
            role = request.form.get("role", "Unknown").strip()
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
    finally:
        db.close()


@app.route("/jobs")
def jobs():
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    try:
        search = request.args.get("search")

        query = (
            db.query(Job)
            .filter(Job.user_id == session["user_id"])
        )

        if search:
            query = query.filter(Job.company.contains(search.strip()))

        jobs_list = query.order_by(Job.applied_date.desc()).all()

        return render_template(
            "jobs.html",
            jobs=jobs_list
        )
    finally:
        db.close()


@app.route("/delete-job/<int:id>")
def delete_job(id):
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == id, Job.user_id == session["user_id"]).first()

        if job:
            db.delete(job)
            db.commit()
            flash("Job removed successfully!", "success")

        return redirect("/jobs")
    finally:
        db.close()


@app.route("/edit-job/<int:id>", methods=["GET", "POST"])
def edit_job(id):
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == id, Job.user_id == session["user_id"]).first()

        if not job:
            flash("Job not found.", "error")
            return redirect("/jobs")

        if request.method == "POST":
            job.status = request.form.get("status", job.status)

            interview_date_str = request.form.get("interview_date")
            if interview_date_str:
                try:
                    job.interview_date = datetime.strptime(
                        interview_date_str,
                        "%Y-%m-%d"
                    ).date()
                except ValueError:
                    pass
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
    finally:
        db.close()


@app.route("/upload-resume", methods=["GET", "POST"])
def upload_resume():
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    try:
        if request.method == "POST":
            if "resume" not in request.files:
                flash("No file part provided", "error")
                return redirect("/upload-resume")

            file = request.files["resume"]

            if file.filename == "":
                flash("No file selected", "error")
                return redirect("/upload-resume")

            filename = secure_filename(file.filename)
            unique_filename = f"{session['user_id']}_{int(datetime.now().timestamp())}_{filename}"
            filepath = os.path.join(
                app.config["UPLOAD_FOLDER"],
                unique_filename
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
                filename=unique_filename,
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
    finally:
        db.close()


@app.route("/my-resumes")
def my_resumes():
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    try:
        resumes = (
            db.query(Resume)
            .filter(Resume.user_id == session["user_id"])
            .all()
        )

        return render_template(
            "my_resumes.html",
            resumes=resumes
        )
    finally:
        db.close()


@app.route("/jd-match/<int:id>", methods=["GET", "POST"])
def jd_match(id):
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    try:
        resume = (
            db.query(Resume)
            .filter(Resume.id == id, Resume.user_id == session["user_id"])
            .first()
        )

        if not resume:
            flash("Resume not found", "error")
            return redirect("/my-resumes")

        if request.method == "POST":
            jd = request.form.get("job_description", "").lower()
            resume_text = (resume.resume_text or "").lower()

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
    finally:
        db.close()


@app.route("/resume/<int:id>")
def resume_details(id):
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    try:
        resume = (
            db.query(Resume)
            .filter(Resume.id == id, Resume.user_id == session["user_id"])
            .first()
        )

        if not resume:
            flash("Resume not found", "error")
            return redirect("/my-resumes")

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
    finally:
        db.close()


@app.route("/cover-letter/<int:id>", methods=["GET", "POST"])
def cover_letter(id):
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    try:
        resume = (
            db.query(Resume)
            .filter(Resume.id == id, Resume.user_id == session["user_id"])
            .first()
        )

        if not resume:
            flash("Resume not found", "error")
            return redirect("/my-resumes")

        if request.method == "POST":
            company = request.form.get("company", "")
            role = request.form.get("role", "")

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
    finally:
        db.close()


@app.route("/interview/<int:id>", methods=["GET", "POST"])
def interview_questions(id):
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    try:
        resume = (
            db.query(Resume)
            .filter(Resume.id == id, Resume.user_id == session["user_id"])
            .first()
        )

        if not resume:
            flash("Resume not found", "error")
            return redirect("/my-resumes")

        if request.method == "POST":
            role = request.form.get("role", "")

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
    finally:
        db.close()


@app.route("/resume-feedback/<int:id>")
def resume_feedback(id):
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    try:
        resume = (
            db.query(Resume)
            .filter(Resume.id == id, Resume.user_id == session["user_id"])
            .first()
        )

        if not resume:
            flash("Resume not found", "error")
            return redirect("/my-resumes")

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
    finally:
        db.close()


@app.route("/career-advice/<int:id>")
def career_advice(id):
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    try:
        resume = (
            db.query(Resume)
            .filter(Resume.id == id, Resume.user_id == session["user_id"])
            .first()
        )

        if not resume:
            flash("Resume not found", "error")
            return redirect("/my-resumes")

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
    finally:
        db.close()


@app.route("/download-report/<int:id>")
def download_report(id):
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    try:
        resume = (
            db.query(Resume)
            .filter(Resume.id == id, Resume.user_id == session["user_id"])
            .first()
        )

        if not resume:
            return "Resume not found"

        resume_text = resume.resume_text or ""

        score, skills_found, missing_skills = calculate_ats_score(resume_text)
        feedback = clean_markdown_for_pdf(improve_resume(resume_text))
        advice = clean_markdown_for_pdf(career_recommendations(resume_text))

        filename = f"career_report_{id}.pdf"
        pdf_path = os.path.join(app.root_path, "static", filename)

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
    finally:
        db.close()


@app.route("/view-resume/<int:id>")
def view_resume(id):
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    try:
        resume = (
            db.query(Resume)
            .filter(Resume.id == id, Resume.user_id == session["user_id"])
            .first()
        )

        if not resume:
            flash("Resume not found", "error")
            return redirect("/my-resumes")

        return send_from_directory(
            app.config["UPLOAD_FOLDER"],
            resume.filename
        )
    finally:
        db.close()


@app.route("/profile")
def profile():
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    try:
        user_id = session["user_id"]
        user = db.query(User).filter(User.id == user_id).first()

        total_jobs = db.query(Job).filter(Job.user_id == user_id).count()
        total_resumes = db.query(Resume).filter(Resume.user_id == user_id).count()
        total_notifications = db.query(Notification).filter(Notification.user_id == user_id).count()

        resumes = db.query(Resume).filter(Resume.user_id == user_id).all()

        return render_template(
            "profile.html",
            user=user,
            total_jobs=total_jobs,
            total_resumes=total_resumes,
            total_notifications=total_notifications,
            resumes=resumes
        )
    finally:
        db.close()


@app.route("/test-notification")
def test_notification():
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    try:
        note = Notification(
            user_id=session["user_id"],
            message="Welcome to AI Career Assistant"
        )

        db.add(note)
        db.commit()

        flash("Test notification created successfully!", "success")
        return redirect("/dashboard")
    finally:
        db.close()


@app.route("/test-email")
def test_email():
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == session["user_id"]).first()

        if not user or not user.email:
            return render_template(
                "test_email_result.html",
                message="Error: User record or email not found in the database. Please log in again.",
                status="error"
            )

        success = send_interview_email(
            user.email,
            "Google",
            "Software Engineer",
            date.today() + timedelta(days=1),
            user_id=user.id
        )

        if success:
            message = f"Test email successfully sent to {user.email}! Check your inbox."
            status = "success"
        else:
            message = "Failed to send email. Check if email notifications are enabled in your profile or if outbound SMTP ports are blocked."
            status = "error"

        return render_template(
            "test_email_result.html",
            message=message,
            status=status
        )
    except Exception as e:
        print(f"Error in test-email route: {e}")
        return render_template(
            "test_email_result.html",
            message=f"An error occurred: {str(e)}",
            status="error"
        )
    finally:
        db.close()


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/delete-resume/<int:id>")
def delete_resume(id):
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    try:
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
    finally:
        db.close()


@app.route("/clear-notifications")
def clear_notifications():
    if "user_id" not in session:
        return redirect("/")

    db = SessionLocal()
    try:
        db.query(Notification).filter(Notification.user_id == session["user_id"]).delete()
        db.commit()

        flash("Notifications cleared!", "success")
        return redirect("/dashboard")
    finally:
        db.close()


@app.route("/update-email-preference", methods=["POST"])
@login_required
def update_email_preference():
    db_session = SessionLocal()
    try:
        # Merge current_user into this session to prevent detached instance errors
        user = db_session.merge(current_user)

        # Checkbox is in form if checked, otherwise missing
        user.email_enabled = 'email_enabled' in request.form
        db_session.commit()

        status = "enabled" if user.email_enabled else "disabled"
        flash(f"Email notifications have been {status}.", "success")
    except Exception as e:
        db_session.rollback()
        flash("Failed to update email preference. Please try again.", "error")
    finally:
        db_session.close()

    return redirect(url_for('profile'))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)