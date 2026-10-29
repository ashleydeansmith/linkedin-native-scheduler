"""
linkedin_scheduler.py: books posts into LinkedIn's own scheduler, using your logged-in Firefox.

No API key and no developer app. The posts sit in LinkedIn's own "Scheduled" list, so your
computer can be off when they go out.

Commands (run them through run.bat on Windows or ./run.sh on Mac):
  login                       Opens Firefox so you can log in to LinkedIn once.
  check                       Reads LinkedIn's Scheduled list and prints it. Books nothing.
  list                        Shows which post folders would be booked. Opens no browser.
  schedule                    Books every waiting post, one at a time, in time order.
                              Stops at the first post it cannot prove was booked.
  schedule --practice         Does everything except press Confirm. Books nothing.
  schedule --only "<folder>"  Books one post folder.
  add --show to check/schedule to watch the browser work.

A post is a folder inside posts/ named with its time, for example:
  posts/2026-11-03 08.30/post.txt
  posts/2026-11-03 08.30 pricing post/post.txt      (anything after the time is a label)
Optional media in the same folder, one kind only:
  up to 9 pictures (.jpg .jpeg .png .gif), or one .pdf (a document post; its title comes
  from title.txt, or else the file name), or one video (.mp4 .mov).
The time is your computer's own clock.

Safety rules:
  - Confirm is pressed only when LinkedIn's "Posting at ..." line reads exactly the target
    day and time. Anything else stops before Confirm.
  - Schedule is never clicked twice (a slow save plus a second click can book it twice).
  - A post only counts as booked when its opening words read back off LinkedIn's
    Scheduled list. Then scheduled.txt is written in its folder and it is never booked again.
  - Before booking, the Scheduled list is read once. A post whose opening words are already
    on it is marked done instead of booked again, so a rerun after a failure is safe.

LinkedIn layout this matches (2026-10-06): the composer clock is a link "Scheduled (N)"; the
schedule panel has a typed Date box (M/D/YYYY), a Time box, a "Posting at Wed, Oct 7, 8:30 AM"
line and Confirm; then the composer button reads exactly "Schedule". Your LinkedIn must be set
to English.
"""

import argparse
import os
import random
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
except ImportError:  # the unit tests run without a browser
    sync_playwright = None

    class PlaywrightTimeout(Exception):
        pass


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HERE        = Path(__file__).resolve().parent
POSTS_DIR   = HERE / 'posts'
PROFILE_DIR = HERE / '.browser-profile'
DEBUG_DIR   = HERE / 'debug'
RECEIPT     = 'scheduled.txt'

LOGIN_URL = 'https://www.linkedin.com/login'
FEED_URL  = 'https://www.linkedin.com/feed/'

MIN_LEAD   = timedelta(minutes=15)
MAX_IMAGES = 9
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif'}
VIDEO_EXTS = {'.mp4', '.mov'}

# Typed in, never taken from the computer's language: LinkedIn shows English names whatever
# language the computer runs in, and strftime('%a') on a German Mac gives "Mi.".
DAYS   = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

FOLDER_RE = re.compile(r'^(\d{4})-(\d{2})-(\d{2}) (\d{2})\.(\d{2})(?:\s.*)?$')


# ---------------------------------------------------------------------------
# Post folders (no browser needed; this is what the unit tests cover)
# ---------------------------------------------------------------------------

@dataclass
class Post:
    folder: Path
    when: datetime
    text: str = ''
    images: list = field(default_factory=list)
    document: Path = None
    document_title: str = ''
    video: Path = None
    problem: str = ''

    @property
    def name(self):
        return self.folder.name

    @property
    def done(self):
        return (self.folder / RECEIPT).exists()


def parse_folder_time(name):
    """'2026-11-03 08.30 label' -> datetime(2026, 11, 3, 8, 30). None if the name is not a time."""
    m = FOLDER_RE.match(name)
    if not m:
        return None
    try:
        return datetime(*(int(g) for g in m.groups()))
    except ValueError:  # 2026-02-30 and the like
        return None


def time_label(dt):
    """LinkedIn's way of writing a time: '8:30 AM', '12:05 PM'."""
    h = dt.hour % 12 or 12
    return f'{h}:{dt.minute:02d} {"AM" if dt.hour < 12 else "PM"}'


def expected_posting_line(dt):
    """The exact line LinkedIn shows once the date and time are set: 'Posting at Wed, Oct 7, 8:30 AM'."""
    return f'Posting at {DAYS[dt.weekday()]}, {MONTHS[dt.month - 1]} {dt.day}, {time_label(dt)}'


def opening_words(text, n=25):
    """The first n characters of the post, spaces squashed, lower case: what the read-back looks for."""
    return ' '.join(text.split())[:n].lower()


def already_listed(text, listed):
    """True when this post's opening words appear in the text read off LinkedIn's Scheduled list."""
    needle = opening_words(text)
    return bool(needle) and needle in ' '.join(listed.split()).lower()


def load_post(folder):
    """Read one post folder. Problems go in post.problem rather than raising."""
    when = parse_folder_time(folder.name)
    post = Post(folder=folder, when=when)
    txt = folder / 'post.txt'
    if not txt.exists():
        post.problem = 'no post.txt in the folder'
        return post
    post.text = txt.read_text(encoding='utf-8-sig').strip()
    if not post.text:
        post.problem = 'post.txt is empty'
        return post

    files = sorted(p for p in folder.iterdir() if p.is_file())
    post.images = [p for p in files if p.suffix.lower() in IMAGE_EXTS]
    pdfs   = [p for p in files if p.suffix.lower() == '.pdf']
    videos = [p for p in files if p.suffix.lower() in VIDEO_EXTS]

    kinds = [k for k, v in (('pictures', post.images), ('PDF', pdfs), ('video', videos)) if v]
    if len(kinds) > 1:
        post.problem = f'more than one kind of media ({" and ".join(kinds)}); a post takes one'
    elif len(post.images) > MAX_IMAGES:
        post.problem = f'{len(post.images)} pictures; LinkedIn takes at most {MAX_IMAGES}'
    elif len(pdfs) > 1:
        post.problem = f'{len(pdfs)} PDFs; a post takes one'
    elif len(videos) > 1:
        post.problem = f'{len(videos)} videos; a post takes one'
    if pdfs:
        post.document = pdfs[0]
        title_file = folder / 'title.txt'
        post.document_title = (title_file.read_text(encoding='utf-8-sig').strip()
                               if title_file.exists() else '') or pdfs[0].stem
    if videos:
        post.video = videos[0]
    return post


def find_posts(posts_dir=POSTS_DIR, now=None):
    """Every post folder, in time order, plus the names of folders that are not posts."""
    now = now or datetime.now()
    posts, ignored = [], []
    if not posts_dir.exists():
        return posts, ignored
    for folder in sorted(p for p in posts_dir.iterdir() if p.is_dir()):
        if parse_folder_time(folder.name) is None:
            ignored.append(folder.name)
            continue
        post = load_post(folder)
        if not post.problem and not post.done and post.when < now + MIN_LEAD:
            post.problem = 'the time is in the past or less than 15 minutes away'
        posts.append(post)
    posts.sort(key=lambda p: p.when)
    return posts, ignored


def write_receipt(post, detail):
    """Write scheduled.txt without ever leaving a half-written file."""
    tmp = post.folder / (RECEIPT + '.tmp')
    tmp.write_text(f'Booked on LinkedIn for {post.when:%Y-%m-%d %H:%M}\n'
                   f'Checked at {datetime.now():%Y-%m-%d %H:%M}\n{detail}\n', encoding='utf-8')
    os.replace(tmp, post.folder / RECEIPT)


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------

def _pause(page, min_ms=800, max_ms=2200):
    page.wait_for_timeout(random.randint(min_ms, max_ms))


def _shot(page, name):
    DEBUG_DIR.mkdir(exist_ok=True)
    path = DEBUG_DIR / name
    try:
        page.screenshot(path=str(path))
    except Exception:
        pass
    return path


def _launch(pw, headless):
    """Open Firefox on this folder's own profile, where the LinkedIn login is kept."""
    PROFILE_DIR.mkdir(exist_ok=True)
    # Firefox saves window size and position on shutdown. A launch that reads a stale one
    # (a window on a monitor that is no longer plugged in) never finishes starting. These two
    # files hold nothing worth keeping; the login lives elsewhere in the profile.
    for stale in ('xulstore.json', 'sessionstore.jsonlz4'):
        try:
            (PROFILE_DIR / stale).unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            print(f'  [WARN] could not clear {stale}: {e}')
    context = pw.firefox.launch_persistent_context(
        str(PROFILE_DIR), headless=headless,
        viewport={'width': 1280, 'height': 900}, locale='en-GB')
    page = context.pages[0] if context.pages else context.new_page()
    return context, page


def _logged_in(page):
    page.goto(LOGIN_URL, wait_until='domcontentloaded', timeout=30_000)
    _pause(page, 1000, 2000)
    return '/feed' in page.url


# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------

def _open_composer(page):
    """Click 'Start a post'. The aria-label selector is the one that works on the 2026 feed;
    the older ones stay underneath because LinkedIn's markup moves back and forth."""
    for selector in ['[aria-label*="Start a post" i]', 'button[aria-label*="post" i]']:
        try:
            el = page.wait_for_selector(selector, timeout=6_000)
            if el:
                el.click()
                _pause(page, 1500, 2500)
                print('  Composer opened.')
                return
        except Exception:
            continue
    for txt in ['Start a post', 'Start a Post', 'What do you want to talk about?']:
        try:
            loc = page.get_by_text(txt, exact=False).first
            loc.wait_for(timeout=4_000)
            loc.click()
            _pause(page, 1500, 2500)
            print('  Composer opened.')
            return
        except Exception:
            continue
    for selector in ['button.share-box-feed-entry__trigger',
                     'div.share-box-feed-entry__top-bar button',
                     'button[class*="share"][class*="trigger"]',
                     'div[class*="share-box"] button']:
        try:
            el = page.wait_for_selector(selector, timeout=4_000)
            if el:
                el.click()
                _pause(page, 1500, 2500)
                print('  Composer opened.')
                return
        except PlaywrightTimeout:
            continue
    raise RuntimeError(f'Could not open the post composer. Screenshot: {_shot(page, "composer.png")}')


def _type_post_text(page, text):
    text_area = None
    for selector in ['div.ql-editor[contenteditable="true"]',
                     'div[contenteditable="true"][data-placeholder]',
                     'div[aria-label*="post" i][contenteditable="true"]',
                     '.share-creation-state__text-editor div[contenteditable="true"]',
                     'div[contenteditable="true"]']:
        try:
            text_area = page.wait_for_selector(selector, timeout=6_000)
            if text_area:
                break
        except PlaywrightTimeout:
            continue
    if not text_area:
        raise RuntimeError(f'Could not find the post text box. Screenshot: {_shot(page, "textbox.png")}')
    text_area.click()
    _pause(page, 500, 1000)
    for i, line in enumerate(text.split('\n')):
        if i > 0:
            page.keyboard.press('Shift+Enter')
        if line:
            page.keyboard.type(line, delay=random.randint(8, 25))
    _pause(page, 800, 1500)
    print('  Text typed.')


def _click_next(page):
    """Click Next after a picture upload, or carry on if the picture sits inline with no Next
    (LinkedIn's composer has done both in 2026)."""
    for selector in ['button:has-text("Next")', 'button[aria-label*="Next" i]',
                     'button.share-creation-state__next-btn', 'button[class*="next" i]']:
        try:
            btn = page.wait_for_selector(selector, timeout=8_000)
            if btn and btn.is_enabled():
                btn.click()
                _pause(page, 1500, 2500)
                return
        except PlaywrightTimeout:
            continue
    has_editor = page.locator('[role="dialog"] div[contenteditable="true"]').count() > 0
    has_preview = page.locator('[role="dialog"] img[src^="blob:"], [role="dialog"] img[alt*="image" i], '
                               '[role="dialog"] [class*="image-preview" i], [role="dialog"] [class*="media" i] img').count() > 0
    if has_editor and has_preview:
        print('  No Next button: picture attached inline, carrying on.')
        return
    raise RuntimeError(f'Could not find Next after the picture upload. Screenshot: {_shot(page, "next.png")}')


def _upload_images(page, images):
    """Upload all pictures in one go; uploading them one at a time replaces the previous one."""
    _pause(page, 1000, 1500)
    files = [str(p) for p in images]
    try:
        if page.query_selector_all('input[type="file"]'):
            page.set_input_files('input[type="file"]', files)
            _pause(page, 2000, 3500)
            print(f'  {len(files)} picture(s) uploaded.')
            return
    except Exception:
        pass
    for selector in ['button[aria-label="Add a photo"]', 'button[aria-label="Photo"]',
                     'button[aria-label="Add media"]', 'button[aria-label="Media"]',
                     'button[aria-label*="photo" i]', 'button[aria-label*="image" i]',
                     'button[aria-label*="media" i]', '.share-creation-state__toolbar button',
                     '.share-box-footer button']:
        try:
            btn = page.wait_for_selector(selector, timeout=2_000)
            if btn:
                with page.expect_file_chooser(timeout=5_000) as fc_info:
                    btn.click()
                fc_info.value.set_files(files)
                _pause(page, 2000, 3500)
                print(f'  {len(files)} picture(s) uploaded.')
                return
        except Exception:
            continue
    # A post with pictures must never go out as text only.
    raise RuntimeError(f'Could not upload the pictures. Screenshot: {_shot(page, "pictures.png")}')


def _upload_document(page, doc_path, doc_title):
    """PDF document post: More (+) -> Add a document -> Choose file -> title -> Done."""
    _pause(page, 1000, 1500)
    try:
        page.click('button.share-promoted-detour-button[aria-label="More"]', timeout=6_000)
        _pause(page, 1000, 1600)
    except Exception:
        raise RuntimeError(f'Could not click the composer More (+) button. Screenshot: {_shot(page, "document.png")}')
    opened = False
    for selector in ['button.share-promoted-detour-button[aria-label="Add a document"]',
                     'button[aria-label="Add a document"]', '[aria-label="Add a document"]']:
        try:
            page.click(selector, timeout=3_000)
            opened = True
            break
        except Exception:
            continue
    if not opened:
        raise RuntimeError(f'"Add a document" was not found. Screenshot: {_shot(page, "document.png")}')
    _pause(page, 1200, 1800)
    uploaded = False
    for selector in ['button:has-text("Choose file")', 'label:has-text("Choose file")',
                     'button:has-text("Upload from device")']:
        try:
            with page.expect_file_chooser(timeout=8_000) as fc_info:
                page.click(selector, timeout=4_000)
            fc_info.value.set_files(str(doc_path))
            uploaded = True
            break
        except Exception:
            continue
    if not uploaded:
        try:
            page.set_input_files('input[type="file"]', str(doc_path))
            uploaded = True
        except Exception:
            pass
    if not uploaded:
        raise RuntimeError(f'Could not open the file picker for the PDF. Screenshot: {_shot(page, "document.png")}')
    print(f'  PDF uploaded: {doc_path.name}')
    _pause(page, 4000, 6000)  # LinkedIn renders each page before the title box appears
    title_ok = False
    for tsel in ['input[aria-label="Document title"]', 'input[aria-label*="title" i]',
                 'input[placeholder*="title" i]', 'input[name*="title" i]', 'input[id*="title" i]']:
        try:
            fld = page.wait_for_selector(tsel, timeout=10_000)
            if fld:
                fld.click()
                fld.fill(doc_title)
                title_ok = True
                break
        except Exception:
            continue
    if not title_ok:
        raise RuntimeError(f'The PDF uploaded but the title box was not found. Screenshot: {_shot(page, "document.png")}')
    _pause(page, 800, 1200)
    for dsel in ['button:has-text("Done"):not([disabled])', 'button[aria-label="Done"]',
                 'button:has-text("Next"):not([disabled])']:
        try:
            btn = page.wait_for_selector(dsel, timeout=5_000)
            if btn and btn.is_enabled():
                btn.click()
                _pause(page, 2500, 3500)
                print(f'  Document title set: {doc_title!r}')
                return
        except Exception:
            continue
    raise RuntimeError(f'Could not press Done on the PDF. Screenshot: {_shot(page, "document.png")}')


def _upload_video(page, video_path):
    """Video post: Media -> file -> wait (up to 2.5 minutes) for LinkedIn to process it -> Next."""
    _pause(page, 1000, 1500)
    uploaded = False
    for selector in ['button.share-promoted-detour-button[aria-label="Add media"]',
                     'button[aria-label="Media"]', 'button[aria-label="Add media"]',
                     'button[aria-label="Add a video"]', 'button[aria-label*="video" i]']:
        try:
            with page.expect_file_chooser(timeout=8_000) as fc_info:
                page.click(selector, timeout=3_000)
            fc_info.value.set_files(str(video_path))
            uploaded = True
            break
        except Exception:
            continue
    if not uploaded:
        try:
            page.set_input_files('input[type="file"]', str(video_path))
            uploaded = True
        except Exception:
            pass
    if not uploaded:
        raise RuntimeError(f'Could not open the video uploader. Screenshot: {_shot(page, "video.png")}')
    print(f'  Video uploaded: {video_path.name}. Waiting for LinkedIn to process it...')
    for _ in range(30):
        for nsel in ['button:has-text("Next"):not([disabled])', 'button[aria-label="Next"]:not([disabled])',
                     'button:has-text("Done"):not([disabled])']:
            try:
                btn = page.query_selector(nsel)
                if btn and btn.is_enabled():
                    btn.click()
                    _pause(page, 2000, 3000)
                    print('  Video processed.')
                    return
            except Exception:
                continue
        page.wait_for_timeout(5_000)
    raise RuntimeError(f'The video did not finish processing in 2.5 minutes. Screenshot: {_shot(page, "video.png")}')


# ---------------------------------------------------------------------------
# Schedule panel
# ---------------------------------------------------------------------------

def _open_schedule_panel(page):
    """Click the composer's clock: a link labelled 'Scheduled (N)' since 2026-10-06."""
    for sel in ['[role="dialog"] button[aria-label="Schedule post"]',
                'button[aria-label="Schedule post"]',
                'button[aria-label*="schedule" i]',
                'SCHEDULED_LINK']:
        cand = (page.get_by_role('link', name=re.compile(r'Scheduled \(\d+\)')).first
                if sel == 'SCHEDULED_LINK' else page.locator(sel).first)
        try:
            cand.wait_for(state='visible', timeout=4_000)
            cand.click()
            _pause(page, 1500, 2000)
            print('  Schedule panel opened.')
            return
        except Exception:
            continue
    raise RuntimeError(f'Could not find the schedule (clock) button. Screenshot: {_shot(page, "schedule.png")}')


def _set_date_time(page, dt, practice):
    """Fill the Date and Time boxes, check the 'Posting at' line, then press Confirm.

    SAFETY: Confirm is pressed only when 'Posting at' reads exactly the target day and time.
    A wrong or unchanged date would publish at LinkedIn's default slot, so anything else stops.
    """
    time_str = time_label(dt)
    expected = expected_posting_line(dt)
    print(f'  Setting {dt:%Y-%m-%d} {time_str}')
    try:
        page.locator('text=/Posting at/').first.wait_for(state='visible', timeout=6_000)
    except Exception:
        raise RuntimeError('The schedule panel does not look like the one this program knows '
                           '(no "Posting at" line). LinkedIn may have changed its layout, or your '
                           f'LinkedIn is not set to English. Nothing booked. Screenshot: {_shot(page, "panel.png")}')
    try:
        date_box = page.get_by_label('Date', exact=False).first
        date_box.click()
        date_box.fill(f'{dt.month}/{dt.day}/{dt.year}')
        page.keyboard.press('Tab')
        _pause(page, 500, 800)
        time_box = page.get_by_label('Time', exact=False).first
        time_box.click()
        time_box.fill(time_str)
        _pause(page, 600, 900)
        # The time list opens over Confirm; pick the matching item so it closes.
        picked = False
        for loc in (page.locator(f'[role="option"]:has-text("{time_str}")'),
                    page.get_by_text(time_str, exact=True)):
            try:
                item = loc.last
                item.wait_for(state='visible', timeout=1_500)
                item.click()
                picked = True
                break
            except Exception:
                continue
        if not picked:
            page.keyboard.press('Tab')
        _pause(page, 700, 1000)
        shown = page.locator('text=/Posting at/').first.inner_text(timeout=3_000).strip()
    except Exception as e:
        raise RuntimeError(f'Could not fill the date and time: {e}. Screenshot: {_shot(page, "datetime.png")}')
    print(f'  LinkedIn shows: {shown!r}  (want {expected!r})')
    if ' '.join(shown.split()) != expected:
        raise RuntimeError(f'SAFETY STOP: LinkedIn shows {shown!r}, not {expected!r}. Nothing booked. '
                           f'Screenshot: {_shot(page, "datetime.png")}')
    if practice:
        _shot(page, 'practice.png')
        return False
    for loc in (page.get_by_role('button', name='Confirm'),
                page.get_by_role('link', name='Confirm'),
                page.get_by_text('Confirm', exact=True)):
        try:
            el = loc.first
            el.wait_for(state='visible', timeout=4_000)
            el.click()
            _pause(page, 1500, 2000)
            return True
        except Exception:
            continue
    raise RuntimeError(f'Could not press Confirm. Screenshot: {_shot(page, "confirm.png")}')


def _press_schedule(page):
    """Press the composer's 'Schedule' button ONCE and wait for the composer to close.

    Never click it a second time: while LinkedIn saves, the button turns into a spinner, and a
    second click can book the post twice. Leaving during the spinner can abort the save, so
    wait up to 60 seconds for the text box to go.
    """
    b = page.get_by_role('button', name='Schedule', exact=True).first
    try:
        b.wait_for(state='visible', timeout=6_000)
    except Exception:
        raise RuntimeError(f'Could not find the Schedule button. Screenshot: {_shot(page, "schedule-button.png")}')
    if not b.is_enabled():
        raise RuntimeError(f'The Schedule button is greyed out. Screenshot: {_shot(page, "schedule-button.png")}')
    b.click()
    for _ in range(60):
        page.wait_for_timeout(1000)
        if not page.locator('div[contenteditable="true"]').count():
            break
    print('  Schedule pressed. Checking LinkedIn actually has it...')


# ---------------------------------------------------------------------------
# Read-back: is the post really on LinkedIn's Scheduled list?
# ---------------------------------------------------------------------------

def _open_scheduled_list(page):
    """Open the composer's 'Scheduled (N)' tab. Returns True when it is on screen."""
    try:
        page.goto(FEED_URL, wait_until='domcontentloaded', timeout=30_000)
        _pause(page, 1500, 2500)
        _open_composer(page)
        page.get_by_role('link', name=re.compile(r'Scheduled \(\d+\)')).first.click(timeout=8_000)
        _pause(page, 1500, 2500)
        page.locator(r'text=/Scheduled \(\d+\)/').first.click(timeout=5_000)
        _pause(page, 2000, 3000)
        return True
    except Exception as e:
        print(f'  (could not open the Scheduled list: {str(e)[:160]})')
        _shot(page, 'scheduled-list.png')
        return False


def _read_scheduled_list(page):
    """Read only the box holding the 'Scheduled (N)' tab, never the whole page: the feed and
    sidebar match almost anything and would turn the check into a rubber stamp. The list only
    draws what fits, so scroll it and keep every line seen."""
    tab = page.locator(r'text=/Scheduled \(\d+\)/').first
    if not tab.count():
        return None
    seen, order = set(), []
    for _ in range(15):
        for up in (4, 5, 6):
            try:
                txt = tab.locator(f'xpath=ancestor::div[{up}]').inner_text(timeout=4_000)
            except Exception:
                continue
            if txt and len(txt.strip()) > 40 and len(txt) < 20000:
                for ln in txt.split('\n'):
                    if ln.strip() and ln not in seen:
                        seen.add(ln)
                        order.append(ln)
                break
        bb = tab.bounding_box()
        if bb:
            page.mouse.move(bb['x'] + bb['width'] / 2, bb['y'] + 300)
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(600)
    return '\n'.join(order) if order else None


def _scheduled_list_text(page):
    if not _open_scheduled_list(page):
        return None
    return _read_scheduled_list(page)


# ---------------------------------------------------------------------------
# One post
# ---------------------------------------------------------------------------

def book(page, post, practice):
    """Book one post. Returns (proven, detail)."""
    page.goto(FEED_URL, wait_until='domcontentloaded', timeout=30_000)
    _pause(page, 2000, 3500)
    _open_composer(page)
    if post.document:
        _upload_document(page, post.document, post.document_title)
    elif post.video:
        _upload_video(page, post.video)
    elif post.images:
        _upload_images(page, post.images)
        _click_next(page)
    _type_post_text(page, post.text)
    _open_schedule_panel(page)
    if not _set_date_time(page, post.when, practice):
        return False, 'PRACTICE: stopped before Confirm, as asked. Nothing booked.'
    _press_schedule(page)

    listed = _scheduled_list_text(page)
    if listed is None:
        return False, f'could not read LinkedIn\'s Scheduled list. Screenshot: {_shot(page, "readback.png")}'
    if already_listed(post.text, listed):
        return True, 'Read back off LinkedIn\'s Scheduled list: the opening words matched.'
    return False, ('the Scheduled list opened but this post was not on it. '
                   f'Screenshot: {_shot(page, "readback.png")}')


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list(_args):
    posts, ignored = find_posts()
    if not posts:
        print(f'No post folders in {POSTS_DIR}. See the README for how to make one.')
    for p in posts:
        if p.done:
            state = 'DONE (scheduled.txt is there)'
        elif p.problem:
            state = f'WILL SKIP: {p.problem}'
        else:
            media = (f'{len(p.images)} picture(s)' if p.images else
                     f'PDF "{p.document_title}"' if p.document else
                     'video' if p.video else 'text only')
            state = f'waiting, {media}'
        print(f'  {p.when:%a %d %b %Y %H:%M}  {p.name}  ->  {state}')
    for name in ignored:
        print(f'  (ignored, the name is not a time: {name})')


def cmd_login(_args):
    with sync_playwright() as pw:
        context, page = _launch(pw, headless=False)
        if _logged_in(page):
            print('Already logged in to LinkedIn. Nothing to do.')
        else:
            print('Log in to LinkedIn in the Firefox window. You have 5 minutes.')
            try:
                page.wait_for_url(lambda url: '/feed' in url, timeout=300_000)
                page.wait_for_load_state('domcontentloaded')
                _pause(page, 2000, 3000)
                print('Logged in. You can now run "check" and "schedule".')
            except PlaywrightTimeout:
                print('Timed out waiting for the login. Run "login" again.')
        context.close()


def _start(pw, args):
    context, page = _launch(pw, headless=not args.show)
    if not _logged_in(page):
        context.close()
        print('Not logged in to LinkedIn. Run "login" first.')
        sys.exit(1)
    return context, page


def cmd_check(args):
    with sync_playwright() as pw:
        context, page = _start(pw, args)
        listed = _scheduled_list_text(page)
        context.close()
    if listed is None:
        print('FAILED: could not read LinkedIn\'s Scheduled list. LinkedIn may have changed its '
              f'layout, or your LinkedIn is not in English. Screenshots are in {DEBUG_DIR}.')
        print('Do not run "schedule" until this works: without the list nothing can be proven.')
        sys.exit(1)
    print('OK: LinkedIn\'s Scheduled list can be read. It says:')
    for line in [x.strip() for x in listed.split('\n') if x.strip()][:200]:
        print('   ', line[:110])


def cmd_schedule(args):
    posts, _ = find_posts()
    if args.only:
        posts = [p for p in posts if p.name == args.only]
        if not posts:
            print(f'No post folder named {args.only!r} in {POSTS_DIR}.')
            sys.exit(1)
    waiting = [p for p in posts if not p.done]
    for p in waiting:
        if p.problem:
            print(f'  SKIP {p.name}: {p.problem}')
    waiting = [p for p in waiting if not p.problem]
    if not waiting:
        print('Nothing waiting to be booked.')
        return
    print(f'{"Practising" if args.practice else "Booking"} {len(waiting)} post(s), one at a time.')

    with sync_playwright() as pw:
        context, page = _start(pw, args)
        try:
            listed = _scheduled_list_text(page)
            if listed is None:
                print('STOPPED: could not read LinkedIn\'s Scheduled list, so nothing could be '
                      'proven. Run "check" to see why. Nothing booked.')
                sys.exit(1)
            for i, post in enumerate(waiting):
                print(f'\n[{post.name}]  {" ".join(post.text.split())[:60]}')
                if already_listed(post.text, listed):
                    if not args.practice:
                        write_receipt(post, 'Already on LinkedIn\'s Scheduled list before this run; not booked again.')
                    print('  ALREADY ON LINKEDIN: its opening words are on the Scheduled list. Not booked again.')
                    continue
                try:
                    proven, detail = book(page, post, args.practice)
                except Exception as e:
                    proven, detail = False, str(e)
                if args.practice and detail.startswith('PRACTICE'):
                    print(f'  OK  {detail}')
                elif proven:
                    write_receipt(post, detail)
                    print(f'  BOOKED for {post.when:%a %d %b %Y %H:%M}. {detail}')
                else:
                    print(f'  NOT PROVEN: {detail}')
                    print('  Stopping here. Look at your LinkedIn Scheduled list before running again.')
                    print('  If the post IS there, the next run will see it and will not book it twice.')
                    sys.exit(1)
                if i < len(waiting) - 1:
                    _pause(page, 8000, 15000)
        finally:
            context.close()


def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Book posts into LinkedIn\'s own scheduler.')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('login', help='Open Firefox and log in to LinkedIn once.')
    sub.add_parser('list', help='Show the post folders and what would happen to each. No browser.')
    p_check = sub.add_parser('check', help='Read LinkedIn\'s Scheduled list. Books nothing.')
    p_check.add_argument('--show', action='store_true', help='Show the browser window.')
    p_sched = sub.add_parser('schedule', help='Book the waiting posts, one at a time.')
    p_sched.add_argument('--show', action='store_true', help='Show the browser window.')
    p_sched.add_argument('--practice', action='store_true',
                         help='Do everything except press Confirm. Books nothing.')
    p_sched.add_argument('--only', metavar='FOLDER', help='Book only this post folder.')
    args = parser.parse_args()

    if args.command != 'list' and sync_playwright is None:
        print('Playwright is not installed. Run install.bat (Windows) or ./install.sh (Mac) first.')
        sys.exit(1)
    {'login': cmd_login, 'list': cmd_list, 'check': cmd_check, 'schedule': cmd_schedule}[args.command](args)


if __name__ == '__main__':
    main()
