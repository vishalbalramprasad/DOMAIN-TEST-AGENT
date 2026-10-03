"""Web server with login. Run:  python main.py   then open http://127.0.0.1:8765"""
import base64, json, os, re, secrets, sqlite3, hashlib, hmac, time, webbrowser
from contextlib import contextmanager
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen
import engine
from domains import DOMAINS
ROOT = os.path.dirname(os.path.abspath(__file__)); DB = os.path.join(ROOT, "data.db"); SESS = {}; GOOGLE_PENDING = {}
GOOGLE_REDIRECT_DEFAULT = "http://127.0.0.1:8765/auth/google/callback"

@contextmanager
def db():
    connection = sqlite3.connect(DB)
    try:
        yield connection
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()
    finally:
        connection.close()

def ph(pw, salt): return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 120000).hex()
def add_user(n, pw):
    s = secrets.token_hex(16)
    with db() as c: c.execute("insert into users(name,salt,hash) values(?,?,?)", (n, s, ph(pw, s)))

def google_config():
    redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI", "").strip()
    if not redirect_uri:
        public_url = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
        redirect_uri = (public_url + "/auth/google/callback") if public_url else GOOGLE_REDIRECT_DEFAULT
    return (os.environ.get("GOOGLE_CLIENT_ID", "").strip(),
            os.environ.get("GOOGLE_CLIENT_SECRET", "").strip(),
            redirect_uri)

def secure_cookie():
    return "; Secure" if os.environ.get("APP_ENV", "").lower() == "production" or os.environ.get("RENDER") else ""

def google_authorization_url(client_id, redirect_uri, state, verifier):
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    params = {"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
              "scope": "openid email profile", "state": state, "code_challenge": challenge,
              "code_challenge_method": "S256", "prompt": "select_account"}
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)

def google_profile(code, verifier, client_id, client_secret, redirect_uri):
    token_request = Request("https://oauth2.googleapis.com/token",
        data=urlencode({"code": code, "client_id": client_id, "client_secret": client_secret,
                        "redirect_uri": redirect_uri, "grant_type": "authorization_code",
                        "code_verifier": verifier}).encode("ascii"),
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urlopen(token_request, timeout=10) as response:
        token = json.loads(response.read().decode("utf-8"))
    if not isinstance(token, dict):
        raise ValueError("Google returned an invalid token response")
    access_token = token.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise ValueError("Google did not return an access token")
    profile_request = Request("https://openidconnect.googleapis.com/v1/userinfo",
                              headers={"Authorization": "Bearer " + access_token})
    with urlopen(profile_request, timeout=10) as response:
        profile = json.loads(response.read().decode("utf-8"))
    if not isinstance(profile, dict):
        raise ValueError("Google returned an invalid profile response")
    subject, email = profile.get("sub"), profile.get("email")
    if not isinstance(subject, str) or not subject or not isinstance(email, str) or not email:
        raise ValueError("Google profile is missing the account identity")
    if profile.get("email_verified") is not True:
        raise PermissionError("Google email is not verified")
    return subject, email

def create_google_user(subject, email):
    with db() as c:
        row = c.execute("select name from users where google_sub=?", (subject,)).fetchone()
        if row:
            return row[0]

        local = re.sub(r"[^A-Za-z0-9_]", "_", email.split("@", 1)[0]).strip("_")[:20]
        if len(local) < 3:
            local = "google_user"
        name = local
        if c.execute("select 1 from users where name=?", (name,)).fetchone():
            prefix = local[:13]
            for attempt in range(100):
                suffix = hashlib.sha256(("%s:%d" % (subject, attempt)).encode("utf-8")).hexdigest()[:6]
                name = prefix + "_" + suffix
                if not c.execute("select 1 from users where name=?", (name,)).fetchone():
                    break
            else:
                raise RuntimeError("Could not allocate a unique username for the Google account")
        salt = secrets.token_hex(16)
        password = secrets.token_urlsafe(32)
        c.execute("insert into users(name,salt,hash,google_sub) values(?,?,?,?)",
                  (name, salt, ph(password, salt), subject))
        return name

def init():
    with db() as c:
        c.execute("create table if not exists users(name text primary key, salt text, hash text)")
        columns = {row[1] for row in c.execute("pragma table_info(users)")}
        if "google_sub" not in columns:
            c.execute("alter table users add column google_sub text")
        c.execute("create unique index if not exists users_google_sub on users(google_sub) where google_sub is not null")
        c.execute("create table if not exists runs(id integer primary key autoincrement, user text, domain text, ts text, kpi text, report text)")
        production = os.environ.get("APP_ENV", "").lower() == "production" or bool(os.environ.get("RENDER"))
        admin_name = os.environ.get("ADMIN_USERNAME", "admin").strip()
        admin_password = os.environ.get("ADMIN_INITIAL_PASSWORD", "")
        if not c.execute("select 1 from users where name=?", (admin_name,)).fetchone() and admin_password:
            if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", admin_name) or len(admin_password) < 12:
                raise RuntimeError("ADMIN_USERNAME must be 3-20 letters/digits/_, and ADMIN_INITIAL_PASSWORD must be at least 12 characters")
            salt = secrets.token_hex(16)
            c.execute("insert into users(name,salt,hash) values(?,?,?)", (admin_name, salt, ph(admin_password, salt)))
        elif not production and not c.execute("select 1 from users where name='admin'").fetchone():
            salt = secrets.token_hex(16)
            c.execute("insert into users(name,salt,hash) values(?,?,?)", ("admin", salt, ph("Admin@123", salt)))
        elif production and not c.execute("select 1 from users where name=?", (admin_name,)).fetchone():
            print("Production mode: default admin account is disabled; use Sign up or Google.")

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def redirect(self, location, cookies=None):
        self.send_response(303); self.send_header("Location", location)
        self.send_header("Content-Length", "0"); self.send_header("Cache-Control", "no-store")
        for cookie in cookies or []: self.send_header("Set-Cookie", cookie)
        self.end_headers()
    def google_start(self):
        client_id, client_secret, redirect_uri = google_config()
        if not client_id or not client_secret:
            return self.redirect("/?google_error=google_not_configured")
        parts = urlsplit(redirect_uri)
        if (parts.scheme not in ("http", "https") or not parts.netloc
                or parts.path != "/auth/google/callback" or parts.query or parts.fragment):
            return self.redirect("/?google_error=google_misconfigured")
        now = time.time()
        for old_state, entry in list(GOOGLE_PENDING.items()):
            if entry["exp"] <= now:
                GOOGLE_PENDING.pop(old_state, None)
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        GOOGLE_PENDING[state] = {"verifier": verifier, "exp": now + 600}
        secure = "; Secure" if parts.scheme == "https" else ""
        cookie = "google_oauth_state=%s; HttpOnly; SameSite=Lax; Path=/auth/google/callback; Max-Age=600%s" % (state, secure)
        return self.redirect(google_authorization_url(client_id, redirect_uri, state, verifier), [cookie])
    def google_callback(self):
        query = parse_qs(urlsplit(self.path).query)
        state = query.get("state", [""])[0]
        cookie = SimpleCookie(self.headers.get("Cookie", "")).get("google_oauth_state")
        entry = GOOGLE_PENDING.pop(state, None) if state and cookie and hmac.compare_digest(state, cookie.value) else None
        clear_cookie = "google_oauth_state=; HttpOnly; SameSite=Lax; Path=/auth/google/callback; Max-Age=0"
        if not entry or entry["exp"] <= time.time():
            return self.redirect("/?google_error=google_invalid_state", [clear_cookie])
        if query.get("error"):
            return self.redirect("/?google_error=google_cancelled", [clear_cookie])
        code = query.get("code", [""])[0]
        if not code:
            return self.redirect("/?google_error=google_failed", [clear_cookie])
        client_id, client_secret, redirect_uri = google_config()
        try:
            subject, email = google_profile(code, entry["verifier"], client_id, client_secret, redirect_uri)
            name = create_google_user(subject, email)
        except PermissionError:
            return self.redirect("/?google_error=google_unverified_email", [clear_cookie])
        except (HTTPError, URLError, TimeoutError, ValueError, sqlite3.Error, RuntimeError):
            print("Google sign-in failed; check OAuth configuration and server connectivity.")
            return self.redirect("/?google_error=google_failed", [clear_cookie])
        token = secrets.token_hex(24)
        SESS[token] = dict(user=name, exp=time.time() + 8 * 3600)
        parts = urlsplit(redirect_uri)
        secure = "; Secure" if parts.scheme == "https" else ""
        session_cookie = "sid=%s; HttpOnly; SameSite=Strict; Path=/%s" % (token, secure)
        return self.redirect("/", [clear_cookie, session_cookie])
    def user(self):
        t = SimpleCookie(self.headers.get("Cookie", "")).get("sid"); s = SESS.get(t.value) if t else None
        return s["user"] if s and s["exp"] > time.time() else None
    def out(self, code, body, ctype="application/json", extra=None):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store"); self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/": return self.out(200, open(os.path.join(ROOT, "static", "index.html"), "rb").read(), "text/html; charset=utf-8")
        if p == "/auth/google": return self.google_start()
        if p == "/auth/google/callback": return self.google_callback()
        u = self.user()
        if p == "/api/me": return self.out(200, {"user": u})
        if not u: return self.out(401, {"error": "Please log in"})
        if p == "/api/domains":
            return self.out(200, {k: dict(title=v["title"], rules={r: dict(sev=a, text=t) for r, (a, t) in v["rules"].items()}, bugs=v["bugs"]) for k, v in DOMAINS.items()})
        if p == "/api/history":
            with db() as c: rows = c.execute("select id,domain,ts,kpi from runs where user=? order by id desc limit 50", (u,)).fetchall()
            return self.out(200, [dict(id=r[0], domain=r[1], ts=r[2], kpi=json.loads(r[3])) for r in rows])
        m = re.match(r"/api/report/(\d+)$", p)
        if m:
            with db() as c: r = c.execute("select report from runs where id=? and user=?", (m.group(1), u)).fetchone()
            if r: return self.out(200, r[0].encode(), "text/markdown; charset=utf-8", {"Content-Disposition": "attachment; filename=report_%s.md" % m.group(1)})
        self.out(404, {"error": "Not found"})
    def do_POST(self):
        try: d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except ValueError: return self.out(400, {"error": "Bad request"})
        p = self.path; name = str(d.get("name", "")).strip(); pw = str(d.get("password", ""))
        if p in ("/api/login", "/api/signup"):
            if p == "/api/signup":
                if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", name) or len(pw) < 6: return self.out(400, {"error": "Username: 3-20 letters/digits/_. Password: min 6 characters."})
                try: add_user(name, pw)
                except sqlite3.IntegrityError: return self.out(400, {"error": "Username already taken"})
            else:
                with db() as c: r = c.execute("select salt,hash from users where name=?", (name,)).fetchone()
                if not r or not hmac.compare_digest(ph(pw, r[0]), r[1]): time.sleep(0.5); return self.out(401, {"error": "Invalid username or password"})
            t = secrets.token_hex(24); SESS[t] = dict(user=name, exp=time.time() + 8 * 3600)
            return self.out(200, {"user": name}, extra={"Set-Cookie": "sid=%s; HttpOnly; SameSite=Strict; Path=/%s" % (t, secure_cookie())})
        if p == "/api/logout":
            t = SimpleCookie(self.headers.get("Cookie", "")).get("sid"); SESS.pop(t.value if t else "", None)
            return self.out(200, {"ok": True}, extra={"Set-Cookie": "sid=; HttpOnly; SameSite=Strict; Max-Age=0; Path=/%s" % secure_cookie()})
        u = self.user()
        if not u: return self.out(401, {"error": "Please log in"})
        dom = d.get("domain")
        if dom not in DOMAINS: return self.out(400, {"error": "Unknown domain"})
        if p == "/api/compare": return self.out(200, engine.compare(dom))
        if p == "/api/run":
            bugs = [b for b in d.get("bugs", []) if b in DOMAINS[dom]["bugs"]]
            r = engine.run(dom, bugs, bool(d.get("mutation", True)))
            with db() as c: r["run_id"] = c.execute("insert into runs(user,domain,ts,kpi,report) values(?,?,?,?,?)", (u, dom, time.strftime("%Y-%m-%d %H:%M"), json.dumps(r["kpi"]), r["report"])).lastrowid
            os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
            open(os.path.join(ROOT, "reports", "report_%s_%s.md" % (dom, r["run_id"])), "w", encoding="utf-8").write(r["report"])
            return self.out(200, r)
        self.out(404, {"error": "Not found"})

if __name__ == "__main__":
    init(); port = int(os.environ.get("PORT", 8765)); s = ThreadingHTTPServer(("0.0.0.0", port), H)
    print("DomainTestAgent running at http://127.0.0.1:%d  (default login: admin / Admin@123)  Ctrl+C to stop" % port)
    try: webbrowser.open("http://127.0.0.1:%d" % port)
    except Exception: pass
    s.serve_forever()
