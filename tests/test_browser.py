"""End-to-end tests in Chromium against a real server. Skipped if Playwright isn't installed."""

import threading

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from werkzeug.serving import make_server  # noqa: E402

from scheduler import create_app  # noqa: E402

pytestmark = pytest.mark.browser
D = 28  # slots per day


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    app = create_app(str(tmp_path_factory.mktemp("db") / "e2e.db"))
    srv = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # Chromium not downloaded
            pytest.skip(f"Chromium unavailable: {e}")
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("console", lambda m: m.type == "error" and pg.errors.append(m.text))
    yield pg
    ctx.close()


def cell(page, slot):
    return page.locator(f'#grid button[data-slot="{slot}"]')


def drag(page, first, last):
    a, b = cell(page, first).bounding_box(), cell(page, last).bounding_box()
    page.mouse.move(a["x"] + a["width"] / 2, a["y"] + a["height"] / 2)
    page.mouse.down()
    page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2, steps=12)
    page.mouse.up()


def create_group(page, server, name="Exam prep"):
    page.goto(server)
    page.fill("#group-name", name)
    page.click("text=Create group")
    page.wait_for_url("**/g/**")
    return page.url


def join(page, name):
    page.fill("#member-name", name)
    page.click("#join button")
    page.wait_for_selector(f"text=You are {name}")


def save(page):
    page.click("#save")
    page.wait_for_selector("#save-status:has-text('Saved')")


def test_two_people_find_a_common_time(page, browser, server):
    url = create_group(page, server)
    join(page, "Dana")
    drag(page, D + 4, D + 11)                    # Mon 10:00-14:00
    assert page.locator("#save-status").inner_text() == "Unsaved changes"
    save(page)
    assert page.locator('#grid button[aria-pressed="true"]').count() == 8

    other = browser.new_context().new_page()
    other.goto(url)
    join(other, "Omar")
    drag(other, D + 6, D + 13)                   # Mon 11:00-15:00
    save(other)
    other.context.close()

    page.reload()
    page.wait_for_selector("#results li")
    first = page.locator("#results li").first.inner_text()
    assert first.startswith("Mon 11:00–14:00") and "2 of 2: Dana, Omar" in first

    # Clicking a suggestion shows it on the heatmap.
    page.locator("#results button").first.click()
    assert page.locator("#grid.heat button.picked").count() == 6
    label = cell(page, D + 6).get_attribute("aria-label")
    assert label == "Mon 11:00–11:30: 2 of 2 free (Dana, Omar)"
    assert page.errors == []


def test_single_click_toggles_once(page, server):
    create_group(page, server)
    join(page, "Noa")
    cell(page, 10).click()
    assert cell(page, 10).get_attribute("aria-pressed") == "true"
    cell(page, 10).click()
    assert cell(page, 10).get_attribute("aria-pressed") == "false"


def test_controls_hide_when_they_dont_apply(page, server):
    create_group(page, server)
    assert page.locator("#join").is_visible()
    assert not page.locator("#save-bar").is_visible()      # nothing to save before joining
    join(page, "Eli")
    assert not page.locator("#join").is_visible()          # already a member
    assert page.locator("#save-bar").is_visible()
    page.click("#mode-heat")
    assert not page.locator("#save-bar").is_visible()      # the heatmap isn't editable


def test_dragging_back_erases(page, server):
    create_group(page, server)
    join(page, "Lina")
    drag(page, 0, 5)
    drag(page, 2, 3)          # starting on a free cell paints "busy"
    pressed = [int(b.get_attribute("data-slot")) for b in page.locator('#grid button[aria-pressed="true"]').all()]
    assert pressed == [0, 1, 4, 5]


def test_keyboard_editing(page, server):
    create_group(page, server)
    join(page, "Sam")
    cell(page, 0).focus()
    page.keyboard.press("ArrowRight")        # Monday 08:00
    page.keyboard.press("ArrowDown")         # Monday 08:30
    page.keyboard.press("Space")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    focused = page.evaluate("document.activeElement.dataset.slot")
    assert focused == str(D + 2)
    pressed = [b.get_attribute("data-slot") for b in page.locator('#grid button[aria-pressed="true"]').all()]
    assert pressed == [str(D + 1), str(D + 2)]
    save(page)
    page.reload()
    page.wait_for_selector("#grid button")
    assert page.locator('#grid button[aria-pressed="true"]').count() == 2   # persisted, still "me"


def test_names_are_shown_as_text_not_html(page, server):
    create_group(page, server, name="<i>group</i>")
    join(page, "<img src=x onerror=window.__xss=1>")
    assert page.locator("#group-name").inner_text() == "<i>group</i>"
    assert "<img src=x" in page.locator("#members").inner_text()
    assert page.evaluate("window.__xss") is None
    assert page.locator("#members img").count() == 0


def test_rejected_key_is_reported(page, server):
    url = create_group(page, server)
    join(page, "Kim")
    slug = url.rsplit("/", 1)[1]
    page.evaluate(f"""() => {{
        const k = 'scheduler:{slug}';
        const me = JSON.parse(localStorage.getItem(k)); me.key = 'tampered';
        localStorage.setItem(k, JSON.stringify(me));
    }}""")
    page.reload()
    page.wait_for_selector("text=You are Kim")
    cell(page, 3).click()
    page.click("#save")
    page.wait_for_selector("#save-status:has-text('Not saved')")
    assert "only the member can change" in page.locator("#save-status").inner_text()


def test_leave_group(page, server):
    create_group(page, server)
    join(page, "Ari")
    page.click("#leave")
    page.wait_for_selector("#join:not([hidden])")
    assert "Nobody has joined yet" in page.locator("#members").inner_text()


def test_unknown_group_page(page, server):
    r = page.goto(server + "/g/does-not-exist")
    assert r.status == 404


def test_phone_width_has_no_page_scroll(browser, server):
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    pg = ctx.new_page()
    pg.goto(server)
    pg.fill("#group-name", "Phone")
    pg.click("text=Create group")
    pg.wait_for_selector("#grid button")
    assert pg.evaluate("document.documentElement.scrollWidth") <= 390
    ctx.close()
