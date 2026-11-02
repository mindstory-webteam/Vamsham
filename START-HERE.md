# Vamsham — start here

Two separate parts:

| Package | What | Language |
|---|---|---|
| **vamsham-backend** | Website + REST API + database | Python · Django |
| **vamsham-frontend** | Family app + committee app + web dashboard | React Native · Expo · TypeScript |

## Quick start (your own computer)

**1. Backend** — in the `vamsham-backend` folder:
```bash
py -m venv .venv                  # Windows  (Mac/Linux: python3 -m venv .venv)
.venv\Scripts\activate            # Windows  (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
# copy your db.sqlite3 and media/ here (optional)
python manage.py migrate
python manage.py createsuperuser  # your committee login
python manage.py runserver 0.0.0.0:8000
```

**→ Open http://localhost:8000/dashboard/ — the dashboard is already built in.** Sign in with the user from `createsuperuser`.

**2. Frontend (only for the phone app, or to change the design)** — in the `vamsham-frontend` folder (new terminal):
```bash
npm install
copy .env.example .env            # Mac/Linux: cp .env.example .env
npx expo start                    # press w for the browser, or scan the QR with Expo Go
```

After changing the design, run `npm run build:dashboard` to update the dashboard inside the backend.

Full steps (going live, Play Store builds, API list) are in each folder's `README.md`.
