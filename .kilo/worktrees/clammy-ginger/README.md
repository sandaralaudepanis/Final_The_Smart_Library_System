# Smart Library System

The existing HTML and CSS are served by Flask, which also provides the SQLite-backed API.

## Run locally on Windows

Use two PowerShell terminals: one for the main system and one for the camera station.

### 1. Prepare the main system

In the first terminal:

```powershell
cd C:\SmartLibrarySystem001
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Generate one private IoT key and keep the output locally; use the exact same value in both terminals:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Set it in the first terminal, then start Flask:

```powershell
$env:SMART_LIBRARY_IOT_KEY = "paste-your-generated-key-here"
python backend\app.py
```

Open `http://127.0.0.1:5000/` for the main Smart Library System. The database is created/migrated at `smart_library.db`; existing accounts and records are preserved.

### 2. Start Face Recognition / IoT

In the second PowerShell terminal:

```powershell
cd C:\SmartLibrarySystem001
python -m venv face_recognition_iot\.venv
face_recognition_iot\.venv\Scripts\Activate.ps1
python -m pip install -r face_recognition_iot\requirements.txt
$env:SMART_LIBRARY_IOT_KEY = "paste-the-same-generated-key-here"
$env:SMART_LIBRARY_API_URL = "http://127.0.0.1:5000"
python face_recognition_iot\app.py
```

Open `http://127.0.0.1:5001/` for the camera station. Allow camera access at the device level if prompted. The YuNet and SFace model files download the first time the station starts. Press `Q` in the camera window or stop the second terminal to exit; stop the first terminal to stop the main backend. Never commit or share the generated key.

## Empty-database starter accounts

These accounts are created only when the database contains no users. Existing accounts and passwords are preserved, and people records remain in their current database IDs.

- MIS Admin: `admin@smartlibrary.local` / `admin123`
- Librarian: `librarian@smartlibrary.local` / `librarian123`

Change these development passwords before exposing the system to a network. In a deployed environment, set a strong `SMART_LIBRARY_SECRET` and use HTTPS (`SMART_LIBRARY_HTTPS=1`).

## Roles and API

MIS Admin and Librarian accounts can use the dashboard, book catalog, borrowing/returns, attendance history, and reports. Only MIS Admins can manage people and system accounts. People records do not receive login passwords.

## Face Recognition / IoT

The main backend stores attendance sessions and face-registration metadata; use `/api/attendance/time-in` and `/api/attendance/time-out` through the camera client. See `face_recognition_iot/README.md` for its independent dependencies, models, and camera configuration. Camera frames and downloaded embeddings stay in memory; the main service stores compact face encodings and the uploaded registration image.