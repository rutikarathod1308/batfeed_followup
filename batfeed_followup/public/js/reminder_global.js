$(document).on(
	"form-refresh",
	function(e, frm) {

		if (!frm) {
			frm = cur_frm;
		}

		if (!frm) {
			return;
		}


		if (frm.meta.issingle) {
			return;
		}

		
		if (frm.is_new()) {
			return;
		}


		if (frm.doctype === "Reminder") {
			return;
		}

		
		if (frm.__reminder_button_added) {
			return;
		}

		frm.__reminder_button_added = true;

		frm.add_custom_button(
			__("Set Reminder"),
			function () {

				let reminder =
					new frappe.ui.ReminderManager({
						frm: frm
					});

				reminder.show();
			}
		);
	}
);