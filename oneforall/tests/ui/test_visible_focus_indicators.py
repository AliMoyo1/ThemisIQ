"""
PLAN-36 T07 (step 8, "verify visible focus... no keyboard traps"): a
repo-wide scan for `outline:none`/`outline:0` without any `:focus` rule
providing a visible replacement in the same file found exactly two real
instances -- every other file already pairs its own `outline:none` with a
`:focus`/`:focus-visible` rule that sets a border-color/box-shadow, the
same pattern `base_shell.html`'s own shared `.form-input:focus` uses.
"""


def test_draft_editor_shows_a_visible_focus_ring(login_as, live_app):
    """#draftEditor itself only becomes visible after starting/opening a
    draft (a multi-step, possibly-AI-dependent flow well beyond what this
    fix is about, and behind at least one ancestor's own hide/show state
    this test doesn't need to reverse-engineer). Proves the shipped CSS
    rule instead, by injecting a throwaway element with the exact same
    class into the already-loaded page (same stylesheets, same cascade)
    and checking ITS focus state -- exercises the real rule as parsed by
    the real browser, not a re-implementation of it.

    Red proof for this test (temporarily removing the new
    .aria-draft-editor:focus rule from the template): computed boxShadow
    stays 'none' on focus, since the class also sets border:none and
    outline:none. Restored, a visible ring appears."""
    page = login_as("super_admin")
    page.goto(f"{live_app}/aria/ai-generator")
    box_shadow = page.evaluate("""() => {
        const el = document.createElement('textarea');
        el.className = 'aria-draft-editor';
        document.body.appendChild(el);
        el.focus();
        const result = getComputedStyle(el).boxShadow;
        el.remove();
        return result;
    }""")
    assert box_shadow not in ("none", ""), box_shadow


def test_timeline_module_filter_shows_a_visible_focus_ring(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/timeline")
    page.wait_for_selector("#tlModuleFilter")
    page.locator("#tlModuleFilter").focus()
    box_shadow = page.eval_on_selector(
        "#tlModuleFilter", "el => getComputedStyle(el).boxShadow"
    )
    assert box_shadow not in ("none", ""), box_shadow
