"""The real MFA setup page must load under the enforced script policy."""


def test_mfa_setup_loads_under_strict_script_policy(page, login_as, live_app):
    login = page.goto(f"{live_app}/login")
    assert login.status == 200
    assert "script-src-attr 'none'" in login.headers["content-security-policy"]
    login_as("employee")
    # The disposable user has no authenticator. Insert inert controls before
    # DOMContentLoaded so the real page script can bind without changing MFA state.
    page.add_init_script("""
        document.addEventListener('DOMContentLoaded', () => {
          const form = document.createElement('form');
          form.id = 'test-mfa-disable';
          form.dataset.mfaDisable = '';
          form.innerHTML = '<button type="submit">Test disable</button>';
          document.body.append(form);
          const print = document.createElement('button');
          print.id = 'test-mfa-print';
          print.type = 'button';
          print.dataset.mfaPrint = '';
          document.body.append(print);
        }, {once: true});
    """)
    response = page.goto(f"{live_app}/mfa/setup")
    assert response.status == 200
    policy = response.headers["content-security-policy"]
    assert "script-src-attr 'none'" in policy
    assert "'unsafe-inline'" not in policy.split("style-src")[0]
    assert page.locator("h1").inner_text() == "Two-Factor Authentication"
    assert page.locator('script[src="/static/js/mfa_setup.js"]').count() == 1
    assert page.evaluate("() => performance.getEntriesByType('resource').some(r => r.name.endsWith('/static/js/mfa_setup.js'))")
    assert page.evaluate("""() => {
      window.confirm = () => false;
      const form = document.getElementById('test-mfa-disable');
      let prevented = false;
      form.addEventListener('submit', event => { prevented = event.defaultPrevented; });
      form.requestSubmit();
      return prevented;
    }""")
    assert page.evaluate("""() => {
      let printed = false;
      window.print = () => { printed = true; };
      document.getElementById('test-mfa-print').click();
      return printed;
    }""")


def test_password_strength_hint_runs_under_strict_script_policy(page, login_as, live_app):
    login_as("employee")
    response = page.goto(f"{live_app}/change-password")
    assert response.status == 200
    assert "script-src-attr 'none'" in response.headers["content-security-policy"]
    assert page.locator('script[src="/static/js/change_password.js"]').count() == 1
    page.locator("#new_password").fill("Strong-Password-1!")
    assert page.locator("#strengthLabel").inner_text() == "Excellent"
    assert page.locator("#strengthFill").evaluate("element => element.style.width") == "100%"
