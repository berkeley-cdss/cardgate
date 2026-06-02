import asyncio
import io
from flask import Flask, render_template, request, send_file

from cardgate.core.clearances import (
    load_cardgate_config,
    get_academic_units,
    get_semesters,
    get_default_activation_days,
    get_default_expiration_days,
    get_buildings,
)
from cardgate.core.pipeline import export_to_csv
from cardgate.integrations.sis import get_term_dates
from sis.terms import get_term_id_from_year_sem

app = Flask(__name__)

CONFIG_PATH = "cardgate.yaml"
config = load_cardgate_config(CONFIG_PATH)


@app.route("/")
def index():
    academic_units = get_academic_units(config)
    semesters = get_semesters(config)
    buildings = get_buildings(config)
    default_activation = get_default_activation_days(config)
    default_expiration = get_default_expiration_days(config)
    return render_template(
        "index.html",
        academic_units=academic_units,
        semesters=semesters,
        buildings=buildings,
        default_activation=default_activation,
        default_expiration=default_expiration,
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
        
        # Get buffer days from form or fall back to config defaults
        activation_days = request.form.get("activation_days")
        expiration_days = request.form.get("expiration_days")
        if activation_days is None or activation_days == "":
            activation_days = get_default_activation_days(config)
        else:
            activation_days = int(activation_days)
        if expiration_days is None or expiration_days == "":
            expiration_days = get_default_expiration_days(config)
        else:
            expiration_days = int(expiration_days)

        if not academic_unit or not building or not year or not semester:
            return f"Missing required fields: unit={academic_unit}, building={building}, year={year}, semester={semester}", 400

        # Fetch people from SIS
        from cardgate.integrations import sis as sis_module
        people = sis_module.get_course_enrolled_students(
            academic_unit, building, int(year), semester, from_time if from_time else None
        )

        # Get term dates
        term_begin = None
        term_end = None
        if year and semester:
            from dotenv import load_dotenv
            import os
            load_dotenv()
            terms_id = os.getenv("SIS_TERMS_ID")
            terms_key = os.getenv("SIS_TERMS_KEY")
            if terms_id and terms_key:
                term_id_val = asyncio.run(
                    get_term_id_from_year_sem(terms_id, terms_key, int(year), semester.lower())
                )
                term_begin, term_end = asyncio.run(get_term_dates(term_id_val))

        # Generate CSV in memory (binary mode for Flask)
        output = io.BytesIO()
        output_str = io.StringIO()
        export_to_csv(
            people,
            academic_unit,
            config_path=CONFIG_PATH,
            output_path=output_str,
            term_begin=term_begin,
            term_end=term_end,
            activation_days=activation_days,
            expiration_days=expiration_days,
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
    except Exception as e:
        import traceback
        return f"Error: {str(e)}<pre>{traceback.format_exc()}</pre>", 500


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)