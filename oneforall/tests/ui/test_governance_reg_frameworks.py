"""HTTP regression for the Governance regulatory framework picker."""


def test_regulatory_framework_picker_returns_data(login_as, live_app):
    page = login_as("super_admin")
    response = page.request.get(f"{live_app}/governance/api/regulatory-frameworks")
    assert response.status == 200, response.text()[:200]
    assert isinstance(response.json(), list)
