import frappe
from frappe.utils import now_datetime, getdate
from datetime import datetime, timedelta
import requests


def check_missing_biometric():

    today = getdate()

    employees = frappe.get_all(
        "Employee",
        filters={
            "status": "Active"
        },
        fields=[
            "name",
            "employee_name",
            "company",
            "company_email",
            "custom_whatsapp_number",
            "default_shift",
            "holiday_list"
        ]
    )

    current_time = now_datetime().time()

    for emp in employees:

        try:


            if not emp.default_shift:
                continue

            shift = frappe.get_doc(
                "Shift Type",
                emp.default_shift
            )

            start_time = shift.start_time
            end_time = shift.end_time

            in_grace_minutes = (
                shift.late_entry_grace_period or 15
            )

            out_grace_minutes = (
                shift.early_exit_grace_period or 30
            )


            leave_exists = frappe.db.exists(
                "Leave Application",
                {
                    "employee": emp.name,
                    "from_date": ["<=", today],
                    "to_date": [">=", today],
                    "docstatus": 1
                }
            )

            if leave_exists:

                frappe.logger().info(
                    f"Leave exists for employee {emp.name}"
                )

                continue


            holiday_list = emp.holiday_list

            if not holiday_list:

                holiday_list = frappe.db.get_value(
                    "Company",
                    emp.company,
                    "default_holiday_list"
                )

            if holiday_list:

                is_holiday = frappe.db.exists(
                    "Holiday",
                    {
                        "parent": holiday_list,
                        "holiday_date": today
                    }
                )

                if is_holiday:

                    frappe.logger().info(
                        f"Holiday found for employee {emp.name}"
                    )

                    continue


            in_punch = frappe.db.exists(
                "Employee Checkin",
                {
                    "employee": emp.name,
                    "log_type": "IN",
                    "time": ["between", [
                        f"{today} 00:00:00",
                        f"{today} 23:59:59"
                    ]]
                }
            )


            out_punch = frappe.db.exists(
                "Employee Checkin",
                {
                    "employee": emp.name,
                    "log_type": "OUT",
                    "time": ["between", [
                        f"{today} 00:00:00",
                        f"{today} 23:59:59"
                    ]]
                }
            )


            start_datetime = (
                datetime.combine(
                    today,
                    datetime.min.time()
                ) + start_time
            )

            end_datetime = (
                datetime.combine(
                    today,
                    datetime.min.time()
                ) + end_time
            )

            in_trigger = (
                start_datetime
                + timedelta(minutes=in_grace_minutes)
            ).time()

            out_trigger = (
                end_datetime
                + timedelta(minutes=out_grace_minutes)
            ).time()



            in_cache_key = (
                f"missing_in_{emp.name}_{today}"
            )

            out_cache_key = (
                f"missing_out_{emp.name}_{today}"
            )

 

            if (
                current_time > in_trigger
                and not in_punch
                and not frappe.cache().get_value(
                    in_cache_key
                )
            ):

                send_whatsapp_template(
                    emp,
                    "for_in_hq",
                    today
                )

                send_email_template(
                    emp,
                    "FOR IN",
                    today
                )

                frappe.cache().set_value(
                    in_cache_key,
                    1,
                    expires_in_sec=86400
                )

                frappe.logger().info(
                    f"IN notification sent - {emp.name}"
                )


            if (
                current_time > out_trigger
                and not out_punch
                and not frappe.cache().get_value(
                    out_cache_key
                )
            ):

                send_whatsapp_template(
                    emp,
                    "for_out",
                    today
                )

                send_email_template(
                    emp,
                    "FOR OUT",
                    today
                )

                frappe.cache().set_value(
                    out_cache_key,
                    1,
                    expires_in_sec=86400
                )

                frappe.logger().info(
                    f"OUT notification sent - {emp.name}"
                )

        except Exception:

            frappe.log_error(
                frappe.get_traceback(),
                f"Biometric Attendance Error - {emp.name}"
            )




def send_email_template(
    emp,
    template_name,
    today
):

    try:

        if not emp.company_email:
            return

        template_doc = frappe.get_doc(
            "Email Template",
            template_name
        )

        subject = frappe.render_template(
            template_doc.subject,
            {
                "employee_name": emp.employee_name,
                "date": today.strftime("%d-%m-%Y")
            }
        )

        message = frappe.render_template(
            template_doc.response_html,
            {
                "employee_name": emp.employee_name,
                "date": today.strftime("%d-%m-%Y")
            }
        )

        frappe.sendmail(
            recipients=[emp.company_email],
            subject=subject,
            message=message
        )

        frappe.logger().info(
            f"Email Sent - {emp.name}"
        )

    except Exception:

        frappe.log_error(
            frappe.get_traceback(),
            f"Email Error - {emp.name}"
        )



def send_whatsapp_template(
    emp,
    template_name,
    today
):

    try:

        settings = frappe.get_single(
            "WhatsApp Settings"
        )

        access_token = settings.access_token
        api_endpoint = settings.api_endpoint
        version = settings.version
        name_type = settings.name_type

        url = (
            f"{api_endpoint}/"
            f"{version}/"
            f"{name_type}/message/"
        )

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Basic {access_token}"
        }

        country_code = (
            str(emp.custom_country_code or "91")
            .replace("+", "")
            .strip()
        )

        number = (
            str(emp.custom_whatsapp_number or "")
            .replace(" ", "")
            .replace("-", "")
        )

        if number.startswith(f"+{country_code}"):
            number = number[len(country_code) + 1:]

        elif number.startswith(country_code):
            number = number[len(country_code):]

        full_number = f"{country_code}{number}"

        payload = {
            "fullPhoneNumber": full_number,
            "callbackData": emp.name,
            "type": "Template",
            "template": {
                "name": template_name,
                "languageCode": "en",
                "bodyValues": [
                    emp.employee_name,
                    today.strftime("%d-%m-%Y")
                ]
            }
        }

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30
        )

        frappe.log_error(
            title="WhatsApp API Debug",
            message=f"""
URL:
{url}

HEADERS:
{headers}

PAYLOAD:
{payload}

STATUS:
{response.status_code}

RESPONSE:
{response.text}
"""
        )

        try:

            response_data = response.json()

        except Exception:

            frappe.throw(
                f"""
Invalid JSON Response

Status:
{response.status_code}

Response:
{response.text}
"""
            )

        frappe.logger().info(
            f"WhatsApp Sent - {emp.name}"
        )

        return response_data

    except Exception:

        frappe.log_error(
            frappe.get_traceback(),
            f"WhatsApp Error - {emp.name}"
        )