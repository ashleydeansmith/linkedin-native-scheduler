# LinkedIn Native Scheduler

Write your LinkedIn posts as folders on your computer. This program books them into **LinkedIn's own scheduler**, the same one you get from the clock button in the post box. Your computer can be off when the posts go out.

- No API key, no developer app, no monthly fee.
- Text posts, picture posts (up to 9 pictures), PDF document posts (carousels) and video posts.
- A post only counts as booked once the program has **read it back off LinkedIn's Scheduled list**. If it can't, it says so and stops.

Works on Windows and Mac. Needs Python 3.9 or later and a LinkedIn account set to **English**.

> **Read this first.** LinkedIn's User Agreement, section 8.2, bans "bots or other unauthorized automated methods to access the Services" (https://www.linkedin.com/legal/user-agreement, in force from 3 November 2025). This program types into LinkedIn through a real browser at human speed, one post at a time, but it is still automation. LinkedIn can restrict accounts that use it. **You use it at your own risk, on your own account.**

---

## 1. Install (once)

1. Install Python 3.9 or later from https://www.python.org/downloads/. On Windows, tick **"Add python.exe to PATH"** during setup.
2. Download this repo: the green **Code** button, then **Download ZIP**. Unzip it somewhere you'll find it, for example your Documents folder.
3. Run the installer:
   - **Windows:** double-click `install.bat`.
   - **Mac:** open Terminal in the folder and run `chmod +x install.sh run.sh && ./install.sh`.

   It sets up a private copy of Python in a `.venv` folder and downloads the Firefox the program drives (about 90 MB). Nothing else on your computer is changed.

## 2. Log in to LinkedIn (once)

- **Windows:** open Command Prompt in the folder and run `run.bat login`
- **Mac:** `./run.sh login`

A Firefox window opens. Log in to LinkedIn as normal. When your feed appears, the program saves the login in the `.browser-profile` folder and closes. You won't have to log in again unless LinkedIn logs you out.

**`.browser-profile` holds your LinkedIn login. Never share that folder or upload it anywhere.**

## 3. Check it can see your Scheduled list

```
run.bat check          (Mac: ./run.sh check)
```

It should print `OK: LinkedIn's Scheduled list can be read`. If it prints `FAILED`, don't go any further. See *When it goes wrong* below.

## 4. Write a post

Each post is a folder inside `posts/`. **The folder's name is the time it goes out**, in your computer's own time zone:

```
posts/
  2026-11-03 08.30/
    post.txt
  2026-11-05 12.00 pricing carousel/
    post.txt
    pricing.pdf
    title.txt
```

- Name format: `YEAR-MONTH-DAY HOUR.MINUTE`, 24-hour clock, with a **dot** between hour and minute (Windows doesn't allow `:` in folder names). Anything after the time is a label for you and is ignored.
- `post.txt` holds the words of the post, exactly as you want them, line breaks included.
- Media is optional, **one kind per post**:
  - pictures: up to 9 `.jpg`, `.jpeg`, `.png` or `.gif` files, posted in the order of their file names
  - one `.pdf`: a document post. Its title comes from `title.txt`, or else the file name
  - one `.mp4` or `.mov` video
- The time has to be at least 15 minutes from now.

`posts/EXAMPLE 2099-01-01 09.00` is an example. It's never booked, because its name doesn't start with a date. Copy it to start a new post.

See what the program makes of your folders (no browser, books nothing):

```
run.bat list           (Mac: ./run.sh list)
```

## 5. Book them

Try a practice run first. It does everything except press **Confirm**, so nothing gets booked:

```
run.bat schedule --practice
```

Then book for real:

```
run.bat schedule                      books every waiting post, one at a time
run.bat schedule --only "2026-11-03 08.30"     books just that one
```

Add `--show` to watch the browser work.

For each post it:

1. opens the post box, adds the media and types the words
2. sets the date and time, then checks LinkedIn's line **"Posting at Tue, Nov 3, 8:30 AM"** reads exactly the right day and time. If it doesn't, it stops **before** Confirm
3. presses Schedule **once** (pressing it twice can book the post twice)
4. opens LinkedIn's Scheduled list and looks for the post's opening words
5. if they're there, writes `scheduled.txt` in the post's folder. A folder with `scheduled.txt` is never booked again

If any post can't be proven, the program **stops there** and books nothing after it.

## When it goes wrong

**`NOT PROVEN`**: the program pressed Schedule but couldn't find the post on the list afterwards. Look at your Scheduled list on LinkedIn (the clock button in the post box). If the post is there, the next run sees it and marks it done rather than booking it twice. If it isn't, run again.

**`SAFETY STOP: LinkedIn shows ...`**: the date or time didn't take. Nothing was booked.

**`FAILED` on `check`, or "does not look like the one this program knows"**: usually LinkedIn has changed the layout of the post box. It did this at least three times in 2026. Every copy of this program breaks when it does, until the code is updated. Check for a newer version of this repo, or open an issue.

**Your LinkedIn is not in English**: the program looks for English words on screen ("Posting at", "Scheduled", "Confirm"). Set LinkedIn to English under Settings → Account preferences → Language.

**Screenshots**: when a step fails, the program saves a screenshot in the `debug/` folder. **Those screenshots show your own LinkedIn feed and name.** Don't attach them to a public issue without cropping them.

**Duplicate check**: a post counts as already on the list when its first 25 characters (spaces squashed, any case) appear there. Two posts that start with the same 25 characters would be mistaken for each other, so start each post differently.

## What has been tested

- Unit tests for folder names, times, media rules and the duplicate check run on Windows and macOS on every push (`.github/workflows/tests.yml`).
- On Windows, against a live English LinkedIn account on 29 October 2026: `check`, plus `schedule --practice` for a text post and a picture post. Both reached the exact "Posting at" line and stopped before Confirm.
- The booking steps (pressing Confirm and Schedule, reading the post back) come unchanged from a script that booked 15 posts on 6 October 2026.
- **Not tested:** the browser steps on a Mac, and PDF and video posts through this version.

## Run the tests

```
pip install pytest
python -m pytest -q
```

## Licence

MIT. See `LICENSE`.
