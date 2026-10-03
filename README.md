# DomainTestAgent v2 - Domain-Based Intelligent Software Testing (Agentic AI)

## Run
1. Install Python 3.9+ (no other packages needed).
2. Windows: double-click `run.bat`  |  Linux/Mac: `./run.sh`  |  or `python main.py`
3. Open http://127.0.0.1:8765 and log in with the local demo account **admin / Admin@123** (or use *Sign up*).

## Google sign-up
1. In Google Cloud Console, create a **Web application** OAuth client and configure the OAuth consent screen. If the app is in testing mode, add the Google accounts that will test it.
2. Add this exact authorized redirect URI to the client:
   `http://127.0.0.1:8765/auth/google/callback`
3. Copy `.env.example` to `.env`, then enter your credentials in `.env`. The app loads this ignored local file on startup, and real environment variables take precedence. Never commit `.env` or share its client secret:
   ```powershell
   Copy-Item .env.example .env
   notepad .env
   python main.py
   ```
   Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` to the values from Google Cloud Console. `GOOGLE_REDIRECT_URI` must exactly match the URI registered in Google Cloud Console. For Render, set the credentials in the hosting provider's environment settings instead of putting them in the repository. If you only want Google sign-in and do not need to run the local copy, open the deployed app directly at https://domain-test-agent.onrender.com/.
4. Choose **Continue with Google** on the login screen (or **Sign up with Google** after selecting Sign up). Google accounts require a verified email.

## Deploy to Render (free)
1. Push this project to a GitHub repository. In Render, choose **New + -> Blueprint** and connect that repository; Render will read [render.yaml](./render.yaml) and create the web service.
2. In the service's **Environment** settings, enter `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. Keep the secret only in Render's environment settings.
3. After Render creates the service, copy its public HTTPS URL (for example, `https://your-service.onrender.com`). The app derives its Google callback from Render's `RENDER_EXTERNAL_URL`.
4. In Google Cloud Console, add this exact URL under the OAuth client's **Authorized redirect URIs**:
   `https://your-service.onrender.com/auth/google/callback`
   If the OAuth consent screen is in testing mode, add the Google accounts that will sign in as test users.
5. Save the Google OAuth settings, then redeploy/restart the Render service. Open its HTTPS URL and choose **Continue with Google**.

The free Render service has an ephemeral filesystem. This project uses SQLite, so user accounts and run history can be lost when Render restarts or redeploys the service. The public deployment also does not create the local demo `admin / Admin@123` account; use Sign up or Google instead. The free service may sleep when idle and take time to wake.

## Flow
Login page -> Home overview -> Test Lab or Run History. From Home, pick a domain (banking, ecommerce, healthcare, food delivery, travel, telecom, hotel), configure bug injections, then run agents or compare with baselines.

## Structure
- `main.py` - web server, login/signup (PBKDF2 hashed passwords, SQLite `data.db`, HttpOnly session cookie)
- `engine.py` - Planner, Generator, Executor, Analyzer/Oracle, Reporter, mutation and baseline evaluation
- `domains.py` - domain rules, system under test with injectable bugs, test scenarios (add new domains here)
- `static/index.html` - login page and dashboard
- `reports/` - markdown reports | `tests/generated/` - generated pytest suites

Run generated tests: `pytest tests/generated -q`; with bugs (Windows): `set BUGS=UPI_BOUNDARY,DECIMALS` then pytest.
Change the default admin password after first login by deleting `data.db` and editing `init()` in `main.py`.
