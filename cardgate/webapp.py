import csv
import io
import json
import logging
import os
import threading
import time
import uuid
from flask import (
    Flask,
    redirect,
    render_template,
    request,
    Response,
    send_file,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv

from cardgate.auth import (
    init_oidc,
    login_required,
    user_has_allowed_group,
)
from cardgate.core.clearances import (
    load_cardgate_config,
    get_academic_units,
    get_semesters,
    get_buildings,
    get_clearance_locations,
    get_allowed_groups,
    get_hr_department_codes,
)
from cardgate.core.pipeline import (
    export_to_csv,
    fetch_card_data,
    fetch_employees,
    fetch_program_students,
    get_programs,
)

from cardgate.models import Person

logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

oidc = init_oidc(app)

CONFIG_PATH = os.environ.get("CARDGATE_CONFIG", "cardgate.yaml")
config = load_cardgate_config(CONFIG_PATH)

# In-memory job store
jobs = {}


EXEMPT_ROUTES = {"oidc_logout", "auth_error", "static"}


@app.before_request
def require_allowed_group():
    if oidc is None:
        return
    if not app.config.get("OIDC_ENABLED", False):
        return
    if not oidc.is_authenticated():
        return
    if request.endpoint in EXEMPT_ROUTES:
        return
    allowed = get_allowed_groups(config)
    if not allowed:
        return
    if not user_has_allowed_group(oidc, allowed):
        return (
            render_template(
                "error.html",
                error="You are not authorized to access this application.",
            ),
            403,
        )


def start_job(params):
    job_id = str(uuid.uuid4())
    mode = params.get("mode", "courses")

    # Build base job record
    jobs[job_id] = {
        "status": "pending",
        "progress": "",
        "csv": None,
        "error": None,
    }

    if mode == "employees":
        hr_depts = params.get("hr_depts", [])
        label = "-".join(hr_depts[:3])
        jobs[job_id]["filename"] = f"{label}-employees.csv"
    elif mode == "programs":
        program_codes = params.get("program_codes", [])
        code_to_role = params.get("code_to_role", {})
        label = "-".join(program_codes[:3])
        jobs[job_id]["filename"] = f"{label}.csv"
    elif mode == "uids":
        jobs[job_id]["filename"] = "uid-access-request.csv"
    else:
        unit = params.get("academic_unit", "Unknown")
        building = params.get("building", "Unknown")
        year = params.get("year", "")
        semester = params.get("semester", "")
        jobs[job_id]["filename"] = f"{unit}-{building}-{year}{semester}.csv"

    def process():
        try:
            jobs[job_id]["status"] = "processing"

            if mode == "employees":
                jobs[job_id]["progress"] = "Querying HR for employees..."
                people = fetch_employees(params.get("hr_depts", []))
                unit = "-".join(params.get("hr_depts", [])[:3]) or "Employees"
            elif mode == "programs":
                jobs[job_id]["progress"] = "Querying SIS for program students..."
                from cardgate.integrations import sis as sis_module

                people = sis_module.get_program_students(
                    program_codes, code_to_role=code_to_role
                )
                unit = params.get("academic_unit", "Program")
            elif mode == "uids":
                jobs[job_id]["progress"] = "Processing UIDs..."
                uids = params.get("uids", [])
                people = [Person(uid=u) for u in uids]
                unit = "UIDs"
            else:
                jobs[job_id]["progress"] = "Querying SIS..."
                from cardgate.integrations import sis as sis_module

                people = sis_module.get_course_enrolled_students(
                    params.get("academic_unit"),
                    params.get("building"),
                    int(params.get("year")),
                    params.get("semester"),
                    params.get("from_time") or None,
                )
                unit = params.get("academic_unit")

            jobs[job_id]["progress"] = f"Found {len(people)} people"

            if people:
                if not os.environ.get("C1C_API_BASE_URL"):
                    jobs[job_id]["status"] = "error"
                    jobs[job_id][
                        "error"
                    ] = "C1C_API_BASE_URL environment variable not set."
                    return

                jobs[job_id]["progress"] = "Fetching card data..."

                def card_progress(done, total):
                    jobs[job_id]["progress"] = f"Card data: {done}/{total}"

                fetch_card_data(people, progress_callback=card_progress)

            jobs[job_id]["progress"] = "Generating CSV..."
            output = io.StringIO()
            export_to_csv(
                people,
                unit,
                config_path=CONFIG_PATH,
                output_path=output,
                clearances=params.get("selected_clearances"),
            )
            jobs[job_id]["csv"] = output.getvalue()
            jobs[job_id]["status"] = "done"
        except Exception as e:
            import traceback

            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = f"{e}\n{traceback.format_exc()}"

    threading.Thread(target=process, daemon=True).start()
    return job_id


@app.route("/")
def index():
    if oidc is not None and not oidc.is_authenticated():
        return render_template("login.html")

    academic_units = get_academic_units(config)
    semesters = get_semesters(config)
    buildings = get_buildings(config)
    clearances = get_clearance_locations(config)
    programs = get_programs(config)
    hr_department_codes = get_hr_department_codes(config)
    return render_template(
        "index.html",
        academic_units=academic_units,
        semesters=semesters,
        buildings=buildings,
        clearances=clearances,
        programs=programs,
        hr_department_codes=hr_department_codes,
        oidc_enabled=app.config.get("OIDC_ENABLED", False),
    )


@app.route("/generate", methods=["POST"])
@login_required(oidc)
def generate():
    mode = request.form.get("mode", "courses")
    selected_clearances = request.form.getlist("clearances") or None

    if mode == "employees":
        hr_depts = request.form.getlist("hr_depts")
        other_raw = request.form.get("hr_dept_other", "")
        if other_raw:
            extra = [c.strip() for c in other_raw.split(",") if c.strip()]
            hr_depts.extend(extra)

        if not hr_depts:
            return {"error": "No HR departments selected"}, 400

        seen = set()
        hr_depts = [c for c in hr_depts if not (c in seen or seen.add(c))]

        params = {
            "mode": "employees",
            "hr_depts": hr_depts,
            "selected_clearances": selected_clearances,
        }
    elif mode == "programs":
        program_codes = request.form.getlist("program_codes")
        other_raw = request.form.get("program_codes_other", "")
        if other_raw:
            extra = [c.strip() for c in other_raw.split(",") if c.strip()]
            program_codes.extend(extra)

        if not program_codes:
            return {"error": "No program codes selected"}, 400

        seen = set()
        program_codes = [
            c for c in program_codes if not (c in seen or seen.add(c))
        ]

        # Build code_to_role from config
        code_to_role = {}
        for prog in get_programs(config):
            if prog.get("code"):
                code_to_role[prog["code"]] = prog.get("role", "Program-enrolled")

        # Derive academic unit from first selected program
        unit = "Program"
        for prog in get_programs(config):
            if prog.get("code") in program_codes:
                unit = prog.get("unit", "Program")
                break

        params = {
            "mode": "programs",
            "academic_unit": unit,
            "program_codes": program_codes,
            "code_to_role": code_to_role,
            "selected_clearances": selected_clearances,
        }
    elif mode == "uids":
        raw_uids = []
        seen = set()

        def add_uid(val):
            cleaned = val.strip()
            # Ignore empty strings and common header titles
            if cleaned and cleaned.lower() != "uid":
                if cleaned not in seen:
                    seen.add(cleaned)
                    raw_uids.append(cleaned)

        # Parse text box (supports newlines, commas, and spaces)
        uid_text = request.form.get("uid_list", "")
        if uid_text:
            normalized = uid_text.replace("\n", ",").replace("\r", ",").replace(" ", ",")
            for token in normalized.split(","):
                add_uid(token)

        # Parse uploaded file if provided
        if "uid_file" in request.files:
            file = request.files["uid_file"]
            if file and file.filename != "":
                stream = io.StringIO(file.stream.read().decode("utf-8"), newline=None)
                reader = csv.reader(stream)
                for row in reader:
                    for cell in row:
                        add_uid(cell)

        if not raw_uids:
            return {"error": "No UIDs provided or file was empty"}, 400

        params = {
            "mode": "uids",
            "uids": raw_uids,
            "selected_clearances": selected_clearances,
        }
    else:
        academic_unit = request.form.get("academic_unit", "")
        if academic_unit == "Other":
            academic_unit = request.form.get("academic_unit_other", "")

        building = request.form.get("building", "")
        if building == "Other":
            building = request.form.get("building_other", "")
        year = request.form.get("year", "")
        semester = request.form.get("semester", "")
        from_time = request.form.get("from_time", "")

        if not academic_unit or not building or not year or not semester:
            return {"error": "Missing required fields"}, 400

        params = {
            "mode": "courses",
            "academic_unit": academic_unit,
            "building": building,
            "year": year,
            "semester": semester,
            "from_time": from_time,
            "selected_clearances": selected_clearances,
        }

    job_id = start_job(params)
    return {"job_id": job_id}


@app.route("/progress/<job_id>")
@login_required(oidc)
def progress(job_id):
    def stream():
        last_progress = ""
        while True:
            job = jobs.get(job_id)
            if not job:
                yield "data: " + json.dumps(
                    {"type": "error", "message": "Job not found"}
                ) + "\n\n"
                return

            if job["status"] == "error":
                yield "data: " + json.dumps(
                    {"type": "error", "message": job["error"]}
                ) + "\n\n"
                return

            if job["progress"] != last_progress:
                last_progress = job["progress"]
                yield "data: " + json.dumps(
                    {"type": "progress", "message": job["progress"]}
                ) + "\n\n"

            if job["status"] == "done":
                yield "data: " + json.dumps(
                    {"type": "done", "filename": job["filename"]}
                ) + "\n\n"
                return

            time.sleep(0.5)

    return Response(stream(), mimetype="text/event-stream")


@app.route("/download/<job_id>")
@login_required(oidc)
def download(job_id):
    job = jobs.get(job_id)
    if not job or job["status"] != "done" or job["csv"] is None:
        return "Job not found or not ready", 404

    output = io.BytesIO()
    output.write(job["csv"].encode("utf-8"))
    output.seek(0)

    return send_file(
        output,
        mimetype="text/csv",
        as_attachment=True,
        download_name=job["filename"],
    )


@app.route("/auth-error")
def auth_error():
    error = request.args.get(
        "error", "An authentication error occurred. Please try again."
    )
    return render_template("error.html", error=error)


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", error="Page not found."), 404


@app.errorhandler(500)
def server_error(e):
    return render_template("error.html", error="Internal server error."), 500


@app.errorhandler(Exception)
def handle_error(e):
    from werkzeug.exceptions import HTTPException

    if isinstance(e, HTTPException):
        return render_template("error.html", error=str(e)), e.code

    logger.error(f"Unhandled error: {e}")
    return redirect(url_for("auth_error", error=str(e)))


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
