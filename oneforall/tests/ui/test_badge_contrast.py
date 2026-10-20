"""
The status and severity badges are 10 pixel bold text on a tinted fill, so they need 4.5:1. The amber, green and red
tints were used as text colours and fell to about 3:1, which showed up on a page only once it held rows with those
badges (an empty register passes). This seeds one of each and asks axe about both themes.
"""
import database

INCIDENTS = (("critical", "active"), ("high", "open"), ("medium", "investigating"), ("low", "resolved"),
             ("critical", "closed"))
RISKS = (("open", 4, 4), ("under_review", 3, 3), ("mitigated", 2, 2), ("closed", 1, 1))


def _seed():
    db = database.get_db()
    ids = {"bcm_incidents": [], "erm_enterprise_risks": []}
    try:
        for i, (severity, status) in enumerate(INCIDENTS):
            cur = db.execute("INSERT INTO bcm_incidents (title, description, severity, status) VALUES (%s, 'x', %s, %s)",
                             (f"Badge probe incident {i}", severity, status))
            ids["bcm_incidents"].append(cur.lastrowid)
        for i, (status, likelihood, impact) in enumerate(RISKS):
            cur = db.execute("INSERT INTO erm_enterprise_risks (title, category, likelihood, impact, status) "
                             "VALUES (%s, 'operational', %s, %s, %s)", (f"Badge probe risk {i}", likelihood, impact, status))
            ids["erm_enterprise_risks"].append(cur.lastrowid)
        db.commit()
    finally:
        db.close()
    return ids


def _remove(ids):
    db = database.get_db()
    try:
        for table, rows in ids.items():
            for row_id in rows:
                db.execute(f"DELETE FROM {table} WHERE id = %s", (row_id,))
        db.commit()
    finally:
        db.close()


def _badge_contrast_findings(violations):
    out = []
    for violation in violations:
        if violation["id"] != "color-contrast":
            continue
        for node in violation["nodes"]:
            if 'class="badge' in node["html"] or " badge" in node["html"]:
                out.append((node["html"][:90], node["failureSummary"].replace("\n", " ")[:140]))
    return out


def test_badges_on_a_page_with_rows_meet_the_contrast_minimum_in_both_themes(login_as, live_app, run_axe):
    ids = _seed()
    try:
        page = login_as("super_admin")
        for theme in ("light", "dark"):
            for route, ready in (("/bcm/incidents", "tr:has-text('Badge probe incident 0')"),
                                 ("/erm/register", "text=Badge probe risk 0")):
                page.goto(f"{live_app}/")
                page.evaluate(f"localStorage.setItem('ofa-theme', '{theme}')")
                page.goto(f"{live_app}{route}")
                page.wait_for_selector(ready, timeout=15000)
                page.wait_for_selector(".badge", timeout=8000)
                page.wait_for_timeout(1200)  # the page fades in; axe reads colours mid fade otherwise
                found = _badge_contrast_findings(run_axe())
                assert not found, f"{route} in the {theme} theme: {found}"
    finally:
        _remove(ids)
