"""Unit tests for everything that does not need a browser: folder names, times, media rules,
the 'Posting at' line and the duplicate check."""

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import linkedin_scheduler as ls  # noqa: E402

NOW = datetime(2026, 11, 1, 12, 0)


def make(root, name, text='Hello world, this is a post.', files=()):
    folder = root / name
    folder.mkdir()
    if text is not None:
        (folder / 'post.txt').write_text(text, encoding='utf-8')
    for f in files:
        (folder / f).write_bytes(b'x')
    return folder


@pytest.mark.parametrize('name, want', [
    ('2026-11-03 08.30', datetime(2026, 11, 3, 8, 30)),
    ('2026-11-03 08.30 pricing post', datetime(2026, 11, 3, 8, 30)),
    ('2026-12-31 23.59', datetime(2026, 12, 31, 23, 59)),
])
def test_folder_time(name, want):
    assert ls.parse_folder_time(name) == want


@pytest.mark.parametrize('name', [
    'EXAMPLE 2099-01-01 09.00', '2026-11-03 08:30', '2026-11-03', '2026-02-30 08.30',
    '2026-11-03 25.00', '2026-11-03 08.30x', 'notes',
])
def test_not_a_time(name):
    assert ls.parse_folder_time(name) is None


@pytest.mark.parametrize('hour, minute, want', [
    (0, 5, '12:05 AM'), (8, 30, '8:30 AM'), (11, 59, '11:59 AM'),
    (12, 0, '12:00 PM'), (13, 15, '1:15 PM'), (23, 0, '11:00 PM'),
])
def test_time_label(hour, minute, want):
    assert ls.time_label(datetime(2026, 1, 1, hour, minute)) == want


def test_posting_line_matches_linkedin():
    # The line LinkedIn showed on 2026-10-06 for a post booked for Wednesday 7 October, 8:30 AM.
    assert ls.expected_posting_line(datetime(2026, 10, 7, 8, 30)) == 'Posting at Wed, Oct 7, 8:30 AM'


def test_posting_line_ignores_computer_language(monkeypatch):
    import locale
    for loc in ('de_DE.UTF-8', 'German_Germany.1252', 'fr_FR.UTF-8'):
        try:
            locale.setlocale(locale.LC_TIME, loc)
            break
        except locale.Error:
            continue
    try:
        assert ls.expected_posting_line(datetime(2026, 11, 4, 14, 0)) == 'Posting at Wed, Nov 4, 2:00 PM'
    finally:
        locale.setlocale(locale.LC_TIME, '')


def test_text_only_post(tmp_path):
    make(tmp_path, '2026-11-03 08.30')
    posts, ignored = ls.find_posts(tmp_path, now=NOW)
    assert len(posts) == 1 and not posts[0].problem
    assert not posts[0].images and not posts[0].document and not posts[0].video


def test_examples_and_odd_folders_are_ignored(tmp_path):
    make(tmp_path, 'EXAMPLE 2099-01-01 09.00')
    make(tmp_path, 'notes')
    posts, ignored = ls.find_posts(tmp_path, now=NOW)
    assert posts == [] and sorted(ignored) == ['EXAMPLE 2099-01-01 09.00', 'notes']


def test_time_order(tmp_path):
    make(tmp_path, '2026-11-05 09.00 b')
    make(tmp_path, '2026-11-03 09.00 a')
    posts, _ = ls.find_posts(tmp_path, now=NOW)
    assert [p.name for p in posts] == ['2026-11-03 09.00 a', '2026-11-05 09.00 b']


def test_past_and_too_soon(tmp_path):
    make(tmp_path, '2026-10-31 09.00')
    make(tmp_path, '2026-11-01 12.10')
    make(tmp_path, '2026-11-01 12.20')
    posts, _ = ls.find_posts(tmp_path, now=NOW)
    assert [bool(p.problem) for p in posts] == [True, True, False]


@pytest.mark.parametrize('files, problem', [
    (['a.png', 'b.pdf'], 'more than one kind'),
    ([f'{i}.jpg' for i in range(10)], 'at most 9'),
    (['a.pdf', 'b.pdf'], '2 PDFs'),
    (['a.mp4', 'b.mov'], '2 videos'),
])
def test_media_rules(tmp_path, files, problem):
    make(tmp_path, '2026-11-03 08.30', files=files)
    post = ls.find_posts(tmp_path, now=NOW)[0][0]
    assert problem in post.problem


def test_pictures_sorted_by_name(tmp_path):
    make(tmp_path, '2026-11-03 08.30', files=['2.jpg', '1.PNG', '3.gif'])
    post = ls.find_posts(tmp_path, now=NOW)[0][0]
    assert [p.name for p in post.images] == ['1.PNG', '2.jpg', '3.gif']


def test_pdf_title(tmp_path):
    folder = make(tmp_path, '2026-11-03 08.30', files=['my-deck.pdf'])
    assert ls.load_post(folder).document_title == 'my-deck'
    (folder / 'title.txt').write_text('Five pricing mistakes\n', encoding='utf-8')
    assert ls.load_post(folder).document_title == 'Five pricing mistakes'


def test_missing_or_empty_text(tmp_path):
    a = make(tmp_path, '2026-11-03 08.30', text=None)
    b = make(tmp_path, '2026-11-04 08.30', text='   \n')
    assert 'no post.txt' in ls.load_post(a).problem
    assert 'empty' in ls.load_post(b).problem


def test_receipt_marks_done(tmp_path):
    folder = make(tmp_path, '2026-11-03 08.30')
    post = ls.load_post(folder)
    assert not post.done
    ls.write_receipt(post, 'proof')
    assert post.done and 'proof' in (folder / 'scheduled.txt').read_text(encoding='utf-8')
    assert not (folder / 'scheduled.txt.tmp').exists()


def test_already_listed():
    text = 'Most founders price\non hope.\n\nHere is why.'
    listed = 'Scheduled (2)\nPosting Wed, Nov 4, 2026 at 8:30 AM\nMost founders price on hope. Here is…'
    assert ls.already_listed(text, listed)
    assert not ls.already_listed('A different post entirely', listed)
    assert not ls.already_listed('', listed)
