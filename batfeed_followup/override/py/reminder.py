import frappe
from frappe import _
from frappe.utils.data import add_to_date, get_datetime, now_datetime
from frappe.model.document import Document
from datetime import timedelta
import json


class CustomReminder(Document):

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		description: DF.SmallText
		notified: DF.Check
		remind_at: DF.Datetime
		reminder_docname: DF.DynamicLink | None
		reminder_doctype: DF.Link | None
		user: DF.Link
	
	@staticmethod
	def clear_old_logs(days=30):
		from frappe.query_builder import Interval
		from frappe.query_builder.functions import Now

		table = frappe.qb.DocType("Reminder")
		frappe.db.delete(table, filters=(table.remind_at < (Now() - Interval(days=days))))

	def validate(self):
		self.user = frappe.session.user
		if get_datetime(self.remind_at) < now_datetime():
			frappe.throw(_("Reminder cannot be created in past."))

		if (
			not self.is_new()
			and self.has_value_changed("custom_closed")
			and self.custom_closed
		):

			if self.owner != frappe.session.user:

				frappe.throw(
					_("Only creator can close the reminder.")
				)

	def send_reminder(self):
		if self.custom_closed:
			return

		self.db_set("notified", 1, update_modified=False)
		next_day = self.remind_at + timedelta(days=1)
		frappe.log_error(self.remind_at + timedelta(days=1))
		self.db_set("remind_at", next_day, update_modified=False)


		try:
			if self.custom_user :
            
				for row in self.custom_user:

					notification = frappe.new_doc("Notification Log")

					notification.for_user = row.user
					notification.type = "Alert"
					notification.document_type = self.reminder_doctype
					notification.document_name = self.reminder_docname
					notification.subject = self.description

					notification.insert(ignore_permissions=True)
					self.send_email(row.user)
					self.send_whatsapp(row.user)
			else:
				notification = frappe.new_doc("Notification Log")

				notification.for_user = self.user
				notification.type = "Alert"
				notification.document_type = self.reminder_doctype
				notification.document_name = self.reminder_docname
				notification.subject = self.description

				notification.insert(ignore_permissions=True)
				self.send_email(row.user)
				self.send_whatsapp(row.user)
		except Exception:
			self.log_error("Failed to send reminder")

	def send_email(self, user):

		try:

			user_doc = frappe.get_doc("User", user)

			if not user_doc.email:

				self.create_reminder_log(
					user=user,
					channel="Email",
					status="Failed",
					response_message="Email not found"
				)

				return

			message = f"""
			<p>Dear {user_doc.full_name or user_doc.name},</p>

			<p>You have the following reminder.....</p>

			<table border="1" cellpadding="6" cellspacing="0">

				<tr>
					<td><b>Document Type</b></td>
					<td>{self.reminder_doctype}</td>
				</tr>

				<tr>
					<td><b>Document Number</b></td>
					<td>{self.reminder_docname}</td>
				</tr>

				<tr>
					<td><b>Description</b></td>
					<td>{self.description}</td>
				</tr>

			</table>

			<br>

			<p>
				Regards,<br>
				BATFEED
			</p>
			"""

			frappe.sendmail(
				recipients=[user_doc.email],
				subject=f"Reminder - {self.reminder_docname}",
				message=message
			)

			self.create_reminder_log(
				user=user,
				channel="Email",
				status="Sent",
				response_message="Email Sent Successfully"
			)

		except Exception:

			self.create_reminder_log(
				user=user,
				channel="Email",
				status="Failed",
				response_message=frappe.get_traceback()
			)



	def send_whatsapp(self, user):

		import requests

		try:

			user_doc = frappe.get_doc("User", user)

			# if not user_doc.mobile_no:
			# 	self.create_reminder_log(
			# 	user=user,
			# 	channel="WhatsApp",
			# 	status="Failed",
			# 	response_message="Mobile number not found"
			# 	)
			# 	return

		

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

			employee = frappe.db.get_value(
                "Employee",
                {"user_id": user},
                ["custom_whatsapp_number", "custom_whatsapp_country_code"],
                as_dict=True
            )

			if employee and employee.custom_whatsapp_number :
				number = str(employee.custom_whatsapp_number).strip()
				country_code = str(employee.custom_whatsapp_country_code or "91").replace("+", "").strip()
			else :
				number = str(user_doc.mobile_no or "").strip()
				country_code = "91"

			if not number:
				self.create_reminder_log(
					user=user,
					channel="WhatsApp",
					status="Failed",
					response_message="WhatsApp number not found in Employee/User"
				)
				return

			number = number.replace("+", "")

			if number.startswith(country_code):
				number = number[len(country_code):]

			full_number = f"{country_code}{number}"

			template_name = "reminder"

			
			base_url = frappe.utils.get_url()

			route = frappe.scrub(
				self.reminder_doctype
			).replace("_", "-")

			document_link = (
				f"{frappe.utils.get_url()}/app/"
				f"{route}/"
				f"{self.reminder_docname}"
			)
			payload = {
				"fullPhoneNumber": full_number,
				"callbackData": self.name,
				"type": "Template",
				"template": {
					"name": "reminder",
					"languageCode": "en",

					"bodyValues": [
						user_doc.full_name or user_doc.name,
						self.reminder_doctype,
						self.reminder_docname,
						self.description
					],

					"buttonValues": {
						"0": [
							document_link
						]
					}
				}
			}
			

			response = requests.post(
				url,
				headers=headers,
				json=payload,
				timeout=30
			)
			self.create_reminder_log(
			user=user,
			channel="WhatsApp",
			status="Sent",
			response_message=response.text
			)

			

			frappe.log_error(
				title="WhatsApp Reminder Debug",
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
				f"WhatsApp Reminder Sent - {user_doc.name}"
			)

			return response_data

		except Exception:

			self.create_reminder_log(
			user=user,
			channel="WhatsApp",
			status="Failed",
			response_message=frappe.get_traceback()
			)

	def create_reminder_log(self,user,channel,status,response_message=None):

		log = frappe.new_doc(
			"Reminder Notification Log"
		)

		log.reminder = self.name
		log.user = user
		log.channel = channel
		log.status = status
		log.response_message = response_message
		log.sent_on = now_datetime()

		log.reference_doctype = self.reminder_doctype
		log.reference_document = self.reminder_docname

		log.insert(ignore_permissions=True)
@frappe.whitelist()
def create_new_reminder(
	remind_at: str,
	description: str,
	custom_user : str | None = None,
	reminder_doctype: str | None = None,
	reminder_docname: str | None = None,
):
    if custom_user :
        import json
        users = json.loads(custom_user)
        reminder = frappe.new_doc("Reminder")

        reminder.description = description
        reminder.remind_at = remind_at
        reminder.reminder_doctype = reminder_doctype
        reminder.reminder_docname = reminder_docname
        for row in users:
            reminder.append("custom_user", {
                "user": row.get("user")
            })
    else:
        reminder = frappe.new_doc("Reminder")

        reminder.description = description
        reminder.remind_at = remind_at
        reminder.reminder_doctype = reminder_doctype
        reminder.reminder_docname = reminder_docname
    reminder.insert(ignore_permissions=True)

    return reminder


def custom_send_reminders():
	# Ensure that we send all reminders that might be before next job execution.
	job_freq = 15 * 60  # 15 minutes, as specified in hooks.py
	upper_threshold = add_to_date(now_datetime(), seconds=job_freq, as_string=True, as_datetime=True)
	lower_threshold = add_to_date(now_datetime(), hours=-1, as_string=True, as_datetime=True)
	
	pending_reminders = frappe.get_all(
		"Reminder",
		filters=[
			("remind_at", "<=", upper_threshold),
			("remind_at", ">=", lower_threshold),  # dont send too old reminders if failed to send
			("custom_closed", "=", 0),
		],
		pluck="name",
		ignore_ifnull=True,
	)

	for reminder in pending_reminders:
		frappe.get_doc("Reminder", reminder).send_reminder()







def get_permission_query_conditions(user):

	if not user:
		user = frappe.session.user

	# System Manager can access all
	if "System Manager" in frappe.get_roles(user):
		return ""

	return f"""
	(
		`tabReminder`.`owner` = {frappe.db.escape(user)}
		OR
		`tabReminder`.`user` = {frappe.db.escape(user)}
		OR
		EXISTS (
			SELECT 1
			FROM `tabReminder User` ru
			WHERE
				ru.parent = `tabReminder`.`name`
				AND ru.user = {frappe.db.escape(user)}
		)
	)
	"""


# --------------------------------------------------------
# DOCUMENT PERMISSION
# --------------------------------------------------------

def has_reminder_permission(
	doc,
	user=None,
	permission_type=None
):

	if not user:
		user = frappe.session.user

	# ----------------------------------------------------
	# SYSTEM MANAGER FULL ACCESS
	# ----------------------------------------------------

	if "System Manager" in frappe.get_roles(user):
		return True

	# ----------------------------------------------------
	# OWNER FULL ACCESS
	# ----------------------------------------------------

	if doc.owner == user:
		return True

	# ----------------------------------------------------
	# ASSIGNED USER
	# ----------------------------------------------------

	is_assigned_user = frappe.db.exists(
		"Reminder User",
		{
			"parent": doc.name,
			"user": user
		}
	)

	# ----------------------------------------------------
	# VIEW PERMISSION
	# ----------------------------------------------------

	if permission_type in ["read", "print", "email", None]:

		if (
			doc.user == user
			or is_assigned_user
		):
			return True

	# ----------------------------------------------------
	# WRITE PERMISSION
	# ----------------------------------------------------

	if permission_type == "write":

		if (
			doc.user == user
			or is_assigned_user
		):

			# Assigned users can edit
			return True

	# ----------------------------------------------------
	# DELETE / SUBMIT / CANCEL
	# ----------------------------------------------------

	if permission_type in [
		"delete",
		"submit",
		"cancel"
	]:

		# Only Owner Allowed
		if doc.owner == user:
			return True

	# ----------------------------------------------------
	# CLOSE REMINDER CONTROL
	# ----------------------------------------------------

	if permission_type == "write":

		# Assigned user cannot close reminder
		if (
			is_assigned_user
			and frappe.form_dict.get("custom_closed")
		):
			return False

	return False