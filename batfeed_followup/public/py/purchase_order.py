import frappe
import requests

from frappe.utils import now_datetime, getdate, get_url


def send_overdue_purchase_order_reminders():
    today = getdate()

    po_list = frappe.get_all(
        "Purchase Order",
        filters={
            "docstatus": 1,
            "status": ["not in", ["Completed", "Closed", "Cancelled"]],
            "schedule_date": ["<", today]
        },
        fields=["name"]
    )


    for po in po_list:
        # send_whatsapp_template(po.name, "po_pending", today)
        send_email_template(po.name, "po_pending", today)


def send_whatsapp_template(po_name, template_name, today):
    try:
        settings = frappe.get_single("WhatsApp Settings")

        access_token = settings.access_token
        api_endpoint = settings.api_endpoint
        version = settings.version
        name_type = settings.name_type

        po_doc = frappe.get_doc("Purchase Order", po_name)

        
        users = []
        for row in po_doc.custom_notification_users:
            
            if getattr(row, "user", None):
                users.append(row.user)

        if not users:
            frappe.log_error(f"No notification users found in PO {po_name}", "PO Reminder")
            return

        for user in users:
            employee = frappe.db.get_value(
                "Employee",
                {"user_id": user},
                ["name", "custom_whatsapp_number", "custom_whatsapp_country_code"],
                as_dict=True
            )

            if not employee:
                frappe.log_error(
                    f"No Employee found for user {user} in PO {po_name}",
                    "PO WhatsApp Reminder"
                )
                continue

            mobile_no = employee.custom_whatsapp_number
            wp_country_code = employee.custom_whatsapp_country_code

            country_code = str(wp_country_code or "91").replace("+", "").strip()
            number = str(mobile_no or "").replace(" ", "").replace("-", "").strip()

            if not number:
                frappe.log_error(
                    f"No WhatsApp number found for user {user} / employee {employee.name}",
                    "PO WhatsApp Reminder"
                )
                continue

            
            if number.startswith(f"+{country_code}"):
                number = number[len(country_code) + 1:]
            elif number.startswith(country_code):
                number = number[len(country_code):]

            full_number = f"{country_code}{number}"

            url = f"{api_endpoint}/{version}/{name_type}/message/"

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Basic {access_token}"
            }

            document_link = f"{get_url()}/app/purchase-order/{po_doc.name}"

            payload = {
                "fullPhoneNumber": full_number,
                "callbackData": po_name,
                "type": "Template",
                "template": {
                    "name": template_name,
                    "languageCode": "en",
                    "bodyValues": [
                        po_doc.name,
                        po_doc.schedule_date.strftime("%d-%m-%Y") if po_doc.schedule_date else "",
                        po_doc.supplier or "",
                        po_doc.status or ""
                    ],
                    "buttonValues": {
                        "0": [document_link]
                    }
                }
            }

            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=30
            )

            try:
                response_data = response.json()
            except Exception:
                response_data = {"raw_response": response.text}

            status = "Sent" if response.ok else "Failed"

            frappe.get_doc({
                "doctype": "WhatsApp Notification Log",
                "receiver": full_number,
                "whatsapp_template": template_name,
                "document_type": "Purchase Order",
                "docname": po_doc.name,
                "message_timestamp": now_datetime(),
                "status": status,
                "api_response": frappe.as_json(response_data)
            }).insert(ignore_permissions=True)

            frappe.db.commit()

            frappe.logger().info(
                f"WhatsApp {status} for PO {po_doc.name} to {full_number}"
            )

        return True

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            f"WhatsApp Error - PO {po_name}"
        )
        return False

def send_email_template(po_name, template_name, today):
    try:
        po_doc = frappe.get_doc("Purchase Order", po_name)

        
        users = []
        for row in po_doc.custom_notification_users:
            if getattr(row, "user", None):
                users.append(row.user)

        if not users:
            frappe.log_error(f"No notification users found in PO {po_name}", "PO Email Reminder")
            return

        for user in users:
            employee = frappe.db.get_value(
                "Employee",
                {"user_id": user},
                ["name", "company_email"],
                as_dict=True
            )

            if not employee:
                frappe.log_error(
                    f"No Employee found for user {user} in PO {po_name}",
                    "PO Email Reminder"
                )
                continue

            email = employee.company_email

            template_doc = frappe.get_doc("Email Template",template_name )
            context = {"name": po_name,
            "schedule_date": po_doc.schedule_date.strftime("%d-%m-%Y") if po_doc.schedule_date else "",
            "supplier": po_doc.supplier or "",
            "status": po_doc.status or ""
            }
            subject = frappe.render_template(template_doc.subject, context)
            message = frappe.render_template(template_doc.response_html,context)

            frappe.sendmail(
                recipients=email,
                subject=subject,
                message=message
            )

            frappe.logger().info(
                f"Email sent for PO {po_doc.name} to {email}"
            )

        return True

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            f"Email Error - PO {po_name}"
        )
        return False