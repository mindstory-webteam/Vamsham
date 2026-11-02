# Vamsham — backend (Django + REST API)

This is your existing Vamsham Family website with a REST API added at `/api/`.
The **Vamsham app** (phones) and the **Vamsham dashboard** (browser) both talk to this API.

```
backend/
├── manage.py
├── vamshamproject/   settings + main urls
├── family/                  the 9 family tables (unchanged, + "Not a member" category)
├── app1/                    website: events, photos, memories, reports…
├── dashboard_web/           ★ the built web dashboard, served at /dashboard/
├── api/                     ★ the REST API (new)
│   ├── views/auth.py        phone OTP + committee sign-in
│   ├── views/family.py      tree, search, profiles, "how are we related"
│   ├── views/community.py   events, RSVP, albums, blood, notifications
│   ├── views/admin.py       dashboard, approvals, members, events, messages, payments
│   ├── views/settings_views.py  association settings, committee, photo uploads
│   ├── views/branch_views.py    create / rename / hide / delete family branches
│   ├── branches.py          where each branch keeps its people
│   └── tests.py             automatic tests
├── requirements.txt
└── .env.example             settings for going live
```

---

## A. Run it on your computer (step by step)

You need **Python 3.11 or newer** (`python --version`).

**1. Open a terminal in this `vamsham-backend` folder.**

**2. Make a virtual environment and install packages**

Windows (Command Prompt) — use `py`, not `python3`:
```bat
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```
Your prompt must start with `(.venv)` before you run `pip`. No Python? Install 3.12 from
python.org and tick **“Add python.exe to PATH”**.
Mac / Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**3. Put your data in place.** Copy your existing `db.sqlite3` and `media/` folder
from the live server into this `backend` folder. (They are not in the zip because they
contain the family's personal data.) No database yet? Skip this — step 4 creates an empty one.

**4. Update the database** (adds the new tables; your old data is kept):
```bash
python manage.py migrate
```

**5. Make a committee login** (skip if you already have an admin user):
```bash
python manage.py createsuperuser
```
Anyone with **Staff status** in Django admin can sign in to the dashboard.

**6. Start the server**
```bash
python manage.py runserver 0.0.0.0:8000
```
Check it works:
- http://localhost:8000/dashboard/ → ★ **the Vamsham dashboard** (sign in with the user from step 5)
- http://localhost:8000/ → your website
- http://localhost:8000/admin/ → Django admin (now titled Vamsham)
- http://localhost:8000/api/branches → `{"detail": "Authentication credentials were not provided."}` (that's correct — the API is protected)

**7. Phone sign-in codes:** while testing, the 6-digit code is **printed in this terminal**
(`SMS_BACKEND=console`). No SMS account is needed yet.

**8. Run the tests (optional)**
```bash
python manage.py test api
```
You should see `Ran 28 tests … OK` (the last line must say **OK**).

> On your own computer you **don't need a `.env` file** — safe development defaults are used.

---

## The dashboard inside the backend

The web dashboard (built from the React Native frontend) is already inside this folder in
`dashboard_web/`, and Django serves it at **/dashboard/** — so one server runs everything:

| Address | What |
|---|---|
| `/dashboard/` | Vamsham committee dashboard (light & teal design, Space Grotesk font) |
| `/api/` | REST API used by the dashboard and the phone app |
| `/admin/` | Django admin (same light & teal colours) |
| `/` | your existing website |

After you change the frontend, rebuild the dashboard from the **vamsham-frontend** folder:
```bash
npm run build:dashboard
```
It writes straight into `vamsham-backend/dashboard_web/` (both folders must sit side by side). Refresh the browser.

---

## Family branches

Branches are no longer fixed in the code. The committee manages them in the dashboard:

- **Add person → Branch → “+ New branch”** — type a name, click *Create branch*, and the new person goes into it.
- **Settings → Family branches** — add, rename, hide/show, or delete an empty branch.

How it is stored: the 9 original branches keep their own tables (nothing is moved, the old website keeps
working). Every branch created later keeps its people in one shared table, `api_branchmember`.
`python manage.py migrate` creates the branch list from the 9 originals the first time.

---

## B. Put it on the internet

1. Copy `.env.example` to `.env` (next to `manage.py`) and fill it in:
   - `DJANGO_SECRET_KEY` — a long random string. Make one with
     `python -c "import secrets; print(secrets.token_urlsafe(50))"`
   - `DJANGO_ALLOWED_HOSTS` — your domain(s)
   - `CORS_ALLOWED_ORIGINS` — only needed if you host the dashboard on a *different* domain
     (not needed for `/dashboard/` on this server)
   - `SMS_BACKEND=msg91`, `MSG91_AUTH_KEY`, `MSG91_TEMPLATE_ID` — for real SMS codes
     (Indian SMS needs a DLT-registered OTP template)
2. Install and prepare:
   ```bash
   pip install -r requirements.txt gunicorn
   ./build.sh            # installs, collects static files, migrates
   ```
3. Start: `gunicorn vamshamproject.wsgi --bind 0.0.0.0:8000`
   (behind Nginx, or use Render / Railway / a VPS).
4. **HTTPS is required** — the app sends login tokens.
5. Daily birthday & anniversary notifications at 7 am — add a cron job:
   ```
   0 7 * * * cd /srv/vamsham/backend && .venv/bin/python manage.py send_daily_greetings
   ```
6. Optional: PostgreSQL instead of SQLite — set `DB_ENGINE=postgres` and the `DB_*` values,
   and `pip install "psycopg[binary]"`.

---

## C. What changed compared with your original project

| Where | Change |
|---|---|
| `api/` | New app: the whole REST API |
| `dashboard_web/` + `vamshamproject/dashboard.py` | The built web dashboard, served at `/dashboard/` |
| `static/vamsham/admin.css` | Light & teal colours and Space Grotesk for Django admin |
| `vamshamproject/settings.py` | Reads secrets from `.env`, adds REST framework, JWT, CORS; admin titled **Vamsham** |
| `vamshamproject/urls.py` | `path("api/", include("api.urls"))` |
| `family/models.py` | New category **NM – Not a member**; membership numbers use *highest + 1* (no duplicates after deleting someone) |
| `app1/models.py` (Event) | New optional fields: place, start time, programme, RSVP on/off |
| `templates/settings.py` | **Removed** — it was an old copy with a secret key and DB password. Delete it from your server and git too, and use a new secret key. |

---

## D. API reference (all under `/api/`)

Send `Authorization: Bearer <access token>` on every request except sign-in.
Member endpoints need an **approved** account; `admin/*` needs a **committee (staff)** account.
Lists are paged: `?page=2&page_size=30` → `{count, page, page_size, has_next, results}`.
People are addressed as `branch:id`, e.g. `aipu:12`. Original branches: `aipu, lonappan, francis, varunny, thoma, chakoru, kochuvareed, porinchu, other`; new ones get a slug from their name.

| Method | Path | What it does |
|---|---|---|
| POST | `auth/otp/request` | `{phone}` → sends a 6-digit code |
| POST | `auth/otp/verify` | `{phone, code, name?}` → `{access, refresh, me}` |
| POST | `auth/login` | `{username, password}` — committee sign-in |
| POST | `auth/refresh` | `{refresh}` → new tokens |
| GET/PATCH | `me` | my account (+ this year’s fee status and missing details); PATCH `{name, show_phone, donor_available}` |
| GET | `settings` | app name, UPI ID, WhatsApp, fees (set by the committee) |
| GET | `branches` | the branches with counts |
| GET | `branch-names` | branch names for people still waiting for approval |
| GET | `members?q=&branch=&blood=&category=&living=1` | search people (each result in my branch has `relation_to_me`) |
| GET | `members/<branch>/<id>` | profile with parent, spouses, children, siblings |
| GET | `tree/<branch>?root=&depth=8` | nested family tree |
| GET | `relationship?a=&b=` | "First cousin once removed" + both paths |
| GET | `today` | today's birthdays, anniversaries, remembrance |
| POST | `requests/change`, `requests/new-member` | members suggest edits / new babies |
| GET/POST | `events`, `events/<id>`, `events/<id>/rsvp` | events and RSVP |
| GET | `albums`, `albums/<id>`, `memories`, `reports` | photos, memories, reports |
| GET/POST | `blood-requests`, `blood-donors?group=O%2B` | blood requests and donors (`can_give`, `rest_until`); without `group` → counts per blood group |
| GET/POST | `notifications` | my notifications; POST marks read |
| GET | `admin/dashboard` | numbers for the dashboard (incl. people + app users per branch) |
| GET | `admin/approvals` | sign-ups, edits and new people waiting |
| POST | `admin/approvals/<signup\|change\|new_member>/<id>/<approve\|decline>` | `{member_ref?, note?}` |
| GET/POST | `admin/members[/<branch>]?q=&missing=date_of_birth` | list (with completeness) / add |
| GET/PATCH/DELETE | `admin/members/<branch>/<id>` | edit (multipart for `photo`); delete needs `?force=1` if they have children |
| GET/POST | `admin/events`, GET/PATCH/DELETE `admin/events/<id>` | events + guest list |
| GET/POST | `admin/photos` | albums / upload (`photos` files + `event` or `year`) |
| DELETE | `admin/photos/<event\|family>/<id>` | delete a photo |
| GET/POST | `admin/broadcast?audience=all\|life_members\|branch:x\|blood:B+` | preview count / send message (`{first name}` is replaced for each person) |
| GET/POST | `admin/payments?year=2026` | receipts (auto `RC-0001`), totals by purpose and month |
| GET/PATCH | `admin/settings` | association settings |
| GET | `admin/committee` | committee members |
| GET/POST | `admin/branches` | all branches (hidden too) / create `{name}` |
| PATCH/DELETE | `admin/branches/<slug>` | `{name, hidden, sort_order}` / delete an empty branch |
