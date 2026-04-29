// Copyright (c) 2026, . and contributors
// For license information, please see license.txt

frappe.query_reports["User Role Report"] = {
	// ── Filters ───────────────────────────────────────────────────────────────
    filters: [
        {
            fieldname: "user",
            label: __("User"),
            fieldtype: "Link",
            options: "User",
            width: "200px",
        },
        {
            fieldname: "role",
            label: __("Role"),
            fieldtype: "Link",
            options: "Role",
            width: "200px",
        },
    ],
 
    // ── Column formatter ──────────────────────────────────────────────────────
    formatter: function (value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);
 
        if (!data) return value;
 
        // Status column: Active = green badge, Disabled = grey badge
        if (column.fieldname === "status") {
            if (data.status === "Active") {
                return `<span style="
                    background:#d1fae5;color:#065f46;
                    padding:2px 8px;border-radius:10px;
                    font-size:11px;font-weight:600;">Active</span>`;
            } else {
                return `<span style="
                    background:#f3f4f6;color:#6b7280;
                    padding:2px 8px;border-radius:10px;
                    font-size:11px;font-weight:600;">Disabled</span>`;
            }
        }
 
        // Role columns: ✔ green, ✘ red
        if (column.fieldname && column.fieldname.startsWith("role_")) {
            const raw = (data[column.fieldname] || "").toString().trim();
 
            if (raw === "✔") {
                return `<span style="
                    color:#059669;font-size:15px;
                    font-weight:bold;display:block;text-align:center;"
                    title="Role assigned">✔</span>`;
            }
            if (raw === "✘") {
                return `<span style="
                    color:#dc2626;font-size:15px;
                    opacity:0.45;display:block;text-align:center;"
                    title="Role not assigned">✘</span>`;
            }
        }
 
        return value;
    },
 
    // ── After-render hook ─────────────────────────────────────────────────────
    onload: function (report) {
        if (document.getElementById("urm-style")) return;
 
        const style = document.createElement("style");
        style.id = "urm-style";
        style.textContent = `
            /* Subtle alternating column tint for wide matrices */
            .dt-scrollable .dt-row .dt-cell:nth-child(even) {
                background: rgba(0,0,0,0.018);
            }
        `;
        document.head.appendChild(style);
    },
};
 