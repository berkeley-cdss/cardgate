import io
from flask import Flask, render_template, request, send_file
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
    try:
        # Get form data
        academic_unit = request.form.get("academic_unit", "")
        if academic_unit == "Other":
            academic_unit = request.form.get("academic_unit_other", "")

        building = request.form.get("building", "")
        year = request.form.get("year", "")
        semester = request.form.get("semester", "")
        from_time = request.form.get("from_time", "")

        if not academic_unit or not building or not year or not semester:
            return f"Missing required fields: unit={academic_unit}, building={building}, year={year}, semester={semester}", 400

        # Fetch people from SIS
        from cardgate.integrations import sis as sis_module
        people = sis_module.get_course_enrolled_students(
            academic_unit, building, int(year), semester, from_time or None
        )

        if people:
            fetch_card_data(people)

        # Get selected clearances (multi-select)
        selected_clearances = request.form.getlist("clearances") or None

        # Generate CSV in memory (binary mode for Flask)
        output = io.BytesIO()
        output_str = io.StringIO()
        export_to_csv(
            people,
            academic_unit,
            config_path=CONFIG_PATH,
            output_path=output_str,
            clearances=selected_clearances,
        )
        output.write(output_str.getvalue().encode('utf-8'))
        output.seek(0)

        filename = f"{academic_unit}-{building}-{year}{semester}.csv"
        response = send_file(
            output,
            mimetype="text/csv",
            as_attachment=True,
            download_name=filename,
        )
        response.headers['X-Download-Filename'] = filename
        return response
    except Exception as e:
        import traceback
        return f"Error: {str(e)}<pre>{traceback.format_exc()}</pre>", 500


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)