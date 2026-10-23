"""Keep the public-site headers when updating the protected application proxy."""

from pathlib import Path


def test_checked_in_site_retains_app_limits_and_health_only_monitor():
    site = (Path(__file__).resolve().parents[1] / "scripts" / "nginx" / "themisiq").read_text(
        encoding="utf-8"
    )
    assert 'server_name themisiq.net www.themisiq.net;' in site
    assert 'add_header Content-Security-Policy "frame-ancestors' in site
    assert 'add_header X-Frame-Options "DENY" always;' in site

    assert 'server_name monitor.themisiq.net;' in site
    assert 'server_name app.themisiq.net;' in site
    assert 'server_name app.themisiq.net monitor.themisiq.net;' not in site
    monitor = site.split('server_name monitor.themisiq.net;', 1)[1].split(
        'server_name app.themisiq.net;', 1
    )[0]
    assert 'location = /health' in monitor
    assert 'location /' in monitor and 'return 404;' in monitor

    app = site.split('server_name app.themisiq.net;', 1)[1]
    assert 'limit_req           zone=login' in app
    assert 'limit_req           zone=api' in app
    assert 'client_max_body_size 5m;' in app
    assert 'client_max_body_size 105m;' in app
