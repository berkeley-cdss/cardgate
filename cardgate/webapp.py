import io
import json
import os
import threading
import time
import uuid
from flask import Flask, render_template, request, Response, send_file
from dotenv import load_dotenv

from cardgate.core.clearances import (
    load_cardgate_config,
    get_academic_units,
    get_semesters,
    get_buildings,
    get_clearance_locations,
)
from cardgate.core.pipeline import (
    export_to_csv,
    fetch_card_data,
    fetch_program_students,
    get_programs,
)

load_dotenv()

app = Flask(__name__)

CONFIG_PATH = "cardgate.yaml"
config = load_cardgate_config(CONFIG_PATH)

# In-memory job store
jobs = {}


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

    if mode == "programs":
        program_codes = params.get("program_codes", [])
        code_to_role = params.get("code_to_role", {})
        label = "-".join(program_codes[:3])
        jobs[job_id]["filename"] = f"{label}.csv"
    else:
        unit = params.get("academic_unit", "Unknown")
        building = params.get("building", "Unknown")
        year = params.get("year", "")
        semester = params.get("semester", "")
        jobs[job_id]["filename"] = f"{unit}-{building}-{year}{semester}.csv"

    def process():
        try:
            jobs[job_id]["status"] = "processing"

            if mode == "programs":
                jobs[job_id]["progress"] = "Querying SIS for program students..."
                from cardgate.integrations import sis as sis_module

                people = sis_module.get_program_students(
                    program_codes, code_to_role=code_to_role
                )
                unit = params.get("academic_unit", "Program")
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
    academic_units = get_academic_units(config)
    semesters = get_semesters(config)
    buildings = get_buildings(config)
    clearances = get_clearance_locations(config)
    programs = get_programs(config)
    return render_template(
        "index.html",
        academic_units=academic_units,
        semesters=semesters,
        buildings=buildings,
        clearances=clearances,
        programs=programs,
    )


@app.route("/generate", methods=["POST"])
def generate():
    mode = request.form.get("mode", "courses")
    selected_clearances = request.form.getlist("clearances") or None

    if mode == "programs":
        program_codes = request.form.getlist("program_codes")
        if not program_codes:
            return {"error": "No program codes selected"}, 400

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


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
