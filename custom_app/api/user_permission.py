import frappe

def manage_user_permissions(doc, method):
    role_profile = doc.role_profile_name

    # Find linked Employee record
    employee = frappe.db.get_value(
        "Employee",
        {"user_id": doc.name},
        ["name", "company"],
        as_dict=True
    )

    # -------------------------------
    # CASE 1: Employee / Blank / Any non-HR/Admin role
    # -------------------------------
    if role_profile not in ["HR", "Admin"]:
        if not employee:
            frappe.logger().info(f"No Employee record found for user {doc.name}")
            return

        # ✅ Ensure Employee permission exists
        existing = frappe.db.exists(
            "User Permission",
            {"user": doc.name, "allow": "Employee", "for_value": employee.name}
        )
        if not existing:
            perm = frappe.get_doc({
                "doctype": "User Permission",
                "user": doc.name,
                "allow": "Employee",
                "for_value": employee.name,
                "apply_to_all_doctypes": 1
            })
            perm.insert(ignore_permissions=True)

        # 🗑️ Remove all company permissions except the employee’s own company
        existing_company_perms = frappe.get_all(
            "User Permission",
            filters={"user": doc.name, "allow": "Company"},
            pluck="name"
        )

        for perm_name in existing_company_perms:
            perm_company = frappe.db.get_value("User Permission", perm_name, "for_value")
            if perm_company != employee.company:
                frappe.delete_doc("User Permission", perm_name, ignore_permissions=True)

    # -------------------------------
    # CASE 2: HR / Admin Role Profile
    # -------------------------------
    elif role_profile in ["HR", "Admin"]:
        # 🗑️ Remove Employee permission if exists
        frappe.db.delete("User Permission", {"user": doc.name, "allow": "Employee"})

        # ✅ Get all companies except employee’s company
        all_companies = frappe.get_all("Company", pluck="name")
        if employee and employee.company in all_companies:
            all_companies.remove(employee.company)

        # ✅ Add missing Company permissions (don’t remove existing)
        for company_name in all_companies:
            exists = frappe.db.exists(
                "User Permission",
                {
                    "user": doc.name,
                    "allow": "Company",
                    "for_value": company_name,
                    "applicable_for": "Email Account"
                }
            )
            if not exists:
                perm = frappe.get_doc({
                    "doctype": "User Permission",
                    "user": doc.name,
                    "allow": "Company",
                    "for_value": company_name,
                    "apply_to_all_doctypes": 0,
                    "applicable_for": "Email Account"
                })
                perm.insert(ignore_permissions=True)