# PingLine — Internet-ready real-time messenger

PingLine is an original web-based messaging application built with Flask, Flask-SocketIO, SQLAlchemy and PostgreSQL/SQLite. It is not connected to WhatsApp.

## Features
- User registration and login; passwords are stored as secure hashes (never plain text).
- Unique usernames and username search.
- Private one-to-one messages delivered live with Socket.IO.
- Messages saved in a database and loaded when a conversation is reopened.
- Online presence for users connected to the same running app instance.
- Profile about line, block user, and report action.
- Responsive WhatsApp-inspired chat layout.
- PostgreSQL for deployment; SQLite automatically used for local development.

## Run on Windows (PowerShell)
Open this folder in VS Code. In the VS Code terminal run:

```powershell
& 'C:\Users\User\AppData\Local\Microsoft\WindowsApps\python3.13.exe' -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:SECRET_KEY = 'replace-this-with-a-long-random-secret'
python app.py
```

Then open **http://127.0.0.1:5000** in your browser. Register two accounts (use a second browser/private window for the second user) and test real-time messaging.

If PowerShell blocks activation, run this once in the current terminal and activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Deploy so people can chat over the internet
The app code alone does not create a public website. Deploy it to a Python host that supports WebSockets, and attach a managed PostgreSQL database.

1. Create a Git repository and upload this project (do not upload `.env`, passwords, or a local database file).
2. Create a new web service from the repository on a host that supports Flask, WebSockets, and persistent environment variables.
3. Set the build command to `pip install -r requirements.txt`.
4. Set the start command to `gunicorn --worker-class gthread --threads 100 --bind 0.0.0.0:$PORT app:app`.
5. Add a PostgreSQL database and set `DATABASE_URL` to its connection string.
6. Set `SECRET_KEY` to a long, random, private value. Never share it or commit it to Git.
7. Deploy. Open the HTTPS public URL, register two separate accounts, and test live messages from two devices/networks.

**Important deployment note:** keep one web instance for this starter because online presence is held in process memory. For multiple instances, add a shared Socket.IO message queue (such as Redis) and shared presence handling. Use a managed persistent database; many hosts' local filesystems are temporary.

## Before inviting real users
This is a functional starter project, not a fully audited commercial messenger. It does **not** provide end-to-end encryption, media/file sharing, group chats, push notifications, account recovery, or a staffed moderation dashboard. Reports are currently written to server logs; configure a real review process before public launch. Use HTTPS, a strong `SECRET_KEY`, backups, abuse/rate limits, and a privacy policy. Do not send passwords, financial details, addresses, or other sensitive information in chats.

## Main files
- `app.py` — routes, database models, authentication, Socket.IO events
- `templates/` — landing, sign-in, sign-up and chat pages
- `static/style.css` — UI styling
- `static/app.js` — live chat, search, profile and conversation controls
- `requirements.txt` — Python dependencies
- `Procfile` — production start command
