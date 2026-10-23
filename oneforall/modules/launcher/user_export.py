"""
The user list as a workbook on the shared report kit: a cover, a summary with charts, and the `Users` sheet.

The `Users` sheet keeps the importer's own column names (Full Name, Email, Username, Roles, Business Unit, Status, and
Organization for a super administrator), so an exported file can still be edited and imported again. The importer reads the sheet
named `Users`, so the cover can come first.
"""
from core.report_kit import theme
from core.report_kit.model import Actor, Chart, Col, Heading, Kpi, Kpis, Meta, Report, Table
from core.report_kit import identity
from core.timeutils import utcnow


def users_report(rows, role_map, is_super, admin, org_name="") -> Report:
    """`rows` are user rows (full_name, email, username, id, is_active, bu_name, org_name for a super admin), `role_map`
    {user id: [role keys]}."""
    table_rows = []
    for r in rows:
        row = {"full_name": r["full_name"], "email": r["email"], "username": r["username"],
               "roles": ",".join(role_map.get(r["id"], [])), "bu": r["bu_name"] or "", "status": "Active" if r["is_active"] else "Inactive"}
        if is_super:
            row["org"] = r["org_name"] or ""
        table_rows.append(row)
    columns = [Col("Full Name", "full_name", weight=2), Col("Email", "email", weight=3), Col("Username", "username", weight=1.6),
               Col("Roles", "roles", weight=2.5), Col("Business Unit", "bu", weight=2), Col("Status", "status", weight=1)]
    if is_super:
        columns.insert(0, Col("Organization", "org", weight=2))
    total = len(table_rows)
    active = sum(1 for r in table_rows if r["status"] == "Active")
    by_unit = {}
    for r in table_rows:
        key = r["bu"] or "No business unit"
        by_unit[key] = by_unit.get(key, 0) + 1
    by_role = {}
    for r in table_rows:
        for role in [x for x in r["roles"].split(",") if x]:
            by_role[role] = by_role.get(role, 0) + 1
    units = sorted(by_unit.items(), key=lambda kv: (-kv[1], kv[0]))
    roles = sorted(by_role.items(), key=lambda kv: (-kv[1], kv[0]))
    now = utcnow()
    meta = Meta(title="User accounts", module="platform", section="Users", tier=theme.OPERATIONAL, org_name=org_name,
                subtitle="Every account in scope with its roles and business unit, for seat and access review",
                scope="All organizations (super administrator)" if is_super else "Your organization",
                period=f"As of {now.day} {now.strftime('%b %Y')}", generated_at=now, generated_by=Actor.of_user(admin))
    report = Report(meta)
    report.add(
        Heading("Headline measures"),
        Kpis([Kpi("Accounts", identity.fmt_int(total)), Kpi("Active", identity.fmt_int(active),
                                                           f"{identity.pct(active, total)}% of accounts" if total else "", "good" if active else "neutral"),
              Kpi("Inactive", identity.fmt_int(total - active))]),
        Heading("At a glance"),
        Chart("donut", "Accounts by status", [("Active", active), ("Inactive", total - active)], unit="accounts", half=True,
              centre=identity.fmt_int(total), colours=[theme.GRAPHITE, theme.SILVER],
              takeaway=f"{identity.fmt_int(active)} of {identity.fmt_int(total)} accounts are active." if total else "",
              empty_text="There is no account in scope."),
        Chart("bar", "Accounts by business unit", units[:10], x_label="Number of accounts", y_label="Business unit", unit="accounts", half=True,
              takeaway=(f"{units[0][0]} has the most accounts: {identity.fmt_int(units[0][1])} of {identity.fmt_int(total)}." if units else ""),
              empty_text="There is no account in scope."),
        Chart("bar", "Role assignments", roles[:10], x_label="Number of accounts holding the role", y_label="Role", unit="accounts",
              takeaway=(f"{roles[0][0]} is the most common role: {identity.fmt_int(roles[0][1])} accounts. An account can hold more than one role."
                        if roles else ""), empty_text="No role is assigned."),
        Table("Users", columns, table_rows, sheet_name="Users", empty_text="There is no account in scope."))
    return report
