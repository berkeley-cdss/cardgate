import base64
import io
import json
import os
import queue
import threading
from flask import Flask, render_template, request, Response
from dotenv import load_dotenv

from cardgate.core.clearances import (
    load_cardgate_config,
    get_academic_units,
    get_semesters,
    get_buildings,
    get_clearance_locations,
)
from cardgate.core.pipeline import export_to_csv, fetch_card_data

load_dotenv()

app = Flask(__name__)

CONFIG_PATH = "cardgate.yaml"
config = load_cardgate_config(CONFIG_PATH)


@app.route("/")
def index():
    academic_units = get_academic_units(config)
    semesters = get_semesters(config)
    buildings = get_buildings(config)
    clearances = get_clearance_locations(config)
    return render_template(
        "index.html",
        academic_units=academic_units,
        semesters=semesters,
        buildings=buildings,
        clearances=clearances,
    )


@app.route("/generate", methods=["POST"])
def generate():
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
        return "Missing required fields", 400

    selected_clearances = request.form.getlist("clearances") or None
    filename = f"{academic_unit}-{building}-{year}{semester}.csv"

    def stream():
        q = queue.Queue()

        def process():
            try:
                # Phase 1: SIS query
                q.put(("progress", "Querying SIS..."))
                from cardgate.integrations import sis as sis_module

                people = sis_module.get_course_enrolled_students(
                    academic_unit, building, int(year), semester, from_time or None
                )
                q.put(("progress", f"Found {len(people)} people"))

                # Phase 2: Card data
                if people:
                    if not os.environ.get("C1C_API_BASE_URL"):
                        q.put(
                            ("error", "C1C_API_BASE_URL environment variable not set.")
                        )
                        return

                    q.put(("progress", "Fetching card data..."))

                    def card_progress(done, total):
                        q.put(("progress", f"Card data: {done}/{total}"))

                    fetch_card_data(people, progress_callback=card_progress)

                # Phase 3: Generate CSV
                q.put(("progress", "Generating CSV..."))
                output = io.StringIO()
                export_to_csv(
                    people,
                    academic_unit,
                    config_path=CONFIG_PATH,
                    output_path=output,
                    clearances=selected_clearances,
                )
                csv_content = output.getvalue()
                q.put(("done", csv_content, filename))

            except Exception as e:
                import traceback

                q.put(("error", f"{e}\n{traceback.format_exc()}"))

        threading.Thread(target=process, daemon=True).start()

        while True:
            msg = q.get()
            if msg[0] == "progress":
                yield json.dumps({"type": "progress", "message": msg[1]}) + "\n"
            elif msg[0] == "done":
                encoded = base64.b64encode(msg[1].encode()).decode()
                yield json.dumps(
                    {"type": "done", "csv": encoded, "filename": msg[2]}
                ) + "\n"
                break
            elif msg[0] == "error":
                yield json.dumps({"type": "error", "message": msg[1]}) + "\n"
                break

    return Response(stream(), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
