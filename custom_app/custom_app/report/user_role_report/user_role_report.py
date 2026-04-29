# Copyright (c) 2026, . and contributors
# For license information, please see license.txt

import frappe


def execute(filters=None):
    filters = filters or {}

    # ── 1. Fetch all roles (excluding internal system roles) ──────────────────
    excluded_roles = [
        "All", "Guest", "Administrator", "System Manager",
        "Desk User", "Script Manager",
    ]

    role_filter = {"disabled": 0, "name": ["not in", excluded_roles]}

    if filters.get("role"):
        role_filter["name"] = filters["role"]

    all_roles = frappe.get_all(
        "Role",
        filters=role_filter,
        fields=["name"],
        order_by="name asc",
    )
    role_names = [r.name for r in all_roles]

    if not role_names:
        frappe.msgprint("No roles found matching the filter.")
        return [], []

    # ── 2. Fetch users ────────────────────────────────────────────────────────
    user_filters = {"user_type": "System User"}

    if filters.get("user"):
        user_filters["name"] = filters["user"]

    users = frappe.get_all(
        "User",
        filters=user_filters,
        fields=["name", "full_name", "enabled", "user_type"],
        order_by="full_name asc",
    )

    # ── 3. Build a {user: set(roles)} mapping ────────────────────────────────
    user_roles_map = {}
    for user in users:
        user_roles_map[user.name] = set()

    if users:
        user_names = [u.name for u in users]
        has_roles = frappe.get_all(
            "Has Role",
            filters={"parent": ["in", user_names], "parenttype": "User"},
            fields=["parent", "role"],
        )
        for hr in has_roles:
            if hr.parent in user_roles_map:
                user_roles_map[hr.parent].add(hr.role)

    # ── 4. Build columns ──────────────────────────────────────────────────────
    columns = [
        {
            "fieldname": "user",
            "label": "User (Email)",
            "fieldtype": "Data",
            "width": 220,
        },
        {
            "fieldname": "full_name",
            "label": "Full Name",
            "fieldtype": "Data",
            "width": 160,
        },
        {
            "fieldname": "status",
            "label": "Status",
            "fieldtype": "Data",
            "width": 90,
        },
    ]

    for role in role_names:
        columns.append(
            {
                "fieldname": _role_fieldname(role),
                "label": role,
                "fieldtype": "Data",
                "width": 130,
            }
        )

    # ── 5. Build rows ─────────────────────────────────────────────────────────
    data = []
    for user in users:
        assigned = user_roles_map.get(user.name, set())
        row = {
            "user": user.name,
            "full_name": user.full_name or user.name,
            "status": "Active" if user.enabled else "Disabled",
        }
        for role in role_names:
            row[_role_fieldname(role)] = "✔" if role in assigned else "✘"
        data.append(row)

    return columns, data


# ── Helpers ───────────────────────────────────────────────────────────────────

def _role_fieldname(role_name: str) -> str:
    """Convert a role label into a safe fieldname (alphanumeric + underscore)."""
    return "role_" + "".join(c if c.isalnum() else "_" for c in role_name).lower()