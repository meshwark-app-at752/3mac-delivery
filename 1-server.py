import os, json, sqlite3, hashlib, secrets, time, threading, mimetypes
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
DB = os.environ.get("DB_PATH", "food.db")
WEB = os.path.dirname(os.path.abspath(__file__))
lock = threading.Lock()
def db():
    c = sqlite3.connect(DB, timeout=10); c.row_factory = sqlite3.Row; return c
def init():
    c = db()
    c.executescript("""
    create table if not exists users(id integer primary key, phone text unique, pw text, salt text, role text, name text, token text, active integer default 1);
    create table if not exists restaurants(id integer primary key, owner_id integer, name text, is_open integer default 1);
    create table if not exists items(id integer primary key, rest_id integer, name text, price real, avail integer default 1);
    create table if not exists orders(id integer primary key, customer_id integer, rest_id integer, name text, phone text, address text, items text, total real, status text, courier_id integer, created integer);
    """)
    apw = os.environ.get("ADMIN_CODE"); ap = apw
    if not c.execute("select 1 from users where role='admin'").fetchone():
        apw = apw or str(secrets.randbelow(900000) + 100000); ap = apw
        mk(c, ap, apw, "admin", "المدير")
        print("ADMIN LOGIN phone=%s pass=%s" % (ap, apw), flush=True)
        open("admin_login.txt", "w").write("%s %s" % (ap, apw))
    c.commit(); c.close()
def h(pw, salt): return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 50000).hex()
def mk(c, phone, pw, role, name):
    salt = secrets.token_hex(8)
    cur = c.execute("insert into users(phone,pw,salt,role,name,token) values(?,?,?,?,?,?)", (phone, h(pw, salt), salt, role, name, secrets.token_hex(16)))
    return cur.lastrowid
STATUS_AR = {"new": "جديد", "accepted": "مقبول", "ready": "جاهز للتوصيل", "picked": "في الطريق", "delivered": "تم التسليم", "rejected": "مرفوض", "cancelled": "ملغي"}
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def user(self, c):
        t = self.headers.get("X-Token", "")
        if not t: return None
        u = c.execute("select * from users where token=? and active=1", (t,)).fetchone()
        return u
    def do_GET(self):
        p = urlparse(self.path).path
        if p.startswith("/api/"): return self.api("GET", p)
        if p == "/" : p = "/index.html"
        if p in ("/customer", "/restaurant", "/courier", "/admin"): p += ".html"
        f = os.path.normpath(os.path.join(WEB, p.lstrip("/")))
        if not f.startswith(WEB) or not f.endswith((".html", ".js", ".png")) or not os.path.isfile(f):
            self.send_response(404); self.end_headers(); return
        b = open(f, "rb").read()
        self.send_response(200); self.send_header("Content-Type", (mimetypes.guess_type(f)[0] or "text/plain") + "; charset=utf-8"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_POST(self): self.api("POST", urlparse(self.path).path)
    def api(self, m, p):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            d = json.loads(self.rfile.read(n) or b"{}") if m == "POST" else {}
            with lock:
                c = db()
                try:
                    r = self.route(c, m, p, d); c.commit()
                finally: c.close()
            if isinstance(r, tuple): return self.send(*r)
            self.send(200, r)
        except Exception as e:
            self.send(500, {"error": "خطأ"})
    def route(self, c, m, p, d):
        if p == "/api/guest" and m == "POST":
            nm = str(d.get("name", "")).strip(); ph = str(d.get("phone", "")).strip()
            if not nm or len(ph) < 6: return 400, {"error": "اكتب الاسم والموبايل"}
            code = "g" + secrets.token_hex(6); uid = mk(c, code, secrets.token_hex(8), "customer", nm)
            t = c.execute("select token from users where id=?", (uid,)).fetchone()[0]
            return {"token": t, "name": nm, "role": "customer"}
        if p == "/api/register" and m == "POST":
            return 400, {"error": "غير متاح"}
        if False:
            ph = str(d.get("phone", "")).strip(); pw = str(d.get("password", "")); nm = str(d.get("name", "")).strip()
            role = d.get("role")
            if role not in ("customer", "courier") or len(ph) < 6 or len(pw) < 4 or not nm: return 400, {"error": "بيانات ناقصة (الباسورد 4 أحرف على الأقل)"}
            if c.execute("select 1 from users where phone=?", (ph,)).fetchone(): return 400, {"error": "الرقم مسجل قبل كده"}
            mk(c, ph, pw, role, nm)
            return self.login(c, ph, pw, role)
        if p == "/api/login" and m == "POST":
            return self.login(c, str(d.get("phone", "")).strip(), str(d.get("password", "")), d.get("role"))
        u = self.user(c)
        if not u: return 401, {"error": "سجّل دخول"}
        role = u["role"]
        if p == "/api/restaurants" and m == "GET":
            rs = [dict(r) for r in c.execute("select id,name,is_open from restaurants where is_open=1")]
            return rs
        if p.startswith("/api/menu/") and m == "GET":
            rid = int(p.split("/")[-1])
            return [dict(r) for r in c.execute("select id,name,price from items where rest_id=? and avail=1", (rid,))]
        if p == "/api/order" and role == "customer" and m == "POST":
            rid = int(d["rest_id"]); its = []; total = 0
            for it in d.get("items", []):
                row = c.execute("select * from items where id=? and rest_id=? and avail=1", (int(it["id"]), rid)).fetchone()
                q = int(it.get("qty", 1))
                if row and 0 < q < 50: its.append({"name": row["name"], "price": row["price"], "qty": q}); total += row["price"] * q
            addr = str(d.get("address", "")).strip(); ph = str(d.get("phone", "")).strip() or u["phone"]
            if not its or not addr: return 400, {"error": "اختار أصناف واكتب العنوان"}
            if not c.execute("select 1 from restaurants where id=? and is_open=1", (rid,)).fetchone(): return 400, {"error": "المطعم مقفول"}
            cur = c.execute("insert into orders(customer_id,rest_id,name,phone,address,items,total,status,created) values(?,?,?,?,?,?,?, 'new',?)", (u["id"], rid, u["name"], ph, addr, json.dumps(its, ensure_ascii=False), total, int(time.time())))
            return {"id": cur.lastrowid, "total": total}
        if p == "/api/orders" and m == "GET":
            q = "select o.*, r.name as rest_name from orders o join restaurants r on r.id=o.rest_id "
            if role == "customer": rows = c.execute(q + "where o.customer_id=? order by o.id desc limit 30", (u["id"],))
            elif role == "restaurant":
                rows = c.execute(q + "where r.owner_id=? order by o.id desc limit 50", (u["id"],))
            elif role == "courier":
                rows = c.execute(q + "where (o.status='ready' and o.courier_id is null) or (o.courier_id=? and o.status in ('picked','delivered')) order by o.id desc limit 50", (u["id"],))
            else: rows = c.execute(q + "order by o.id desc limit 200")
            out = []
            for o in rows:
                o = dict(o); o["items"] = json.loads(o["items"]); o["status_ar"] = STATUS_AR.get(o["status"], o["status"])
                if role == "courier" and o["status"] == "ready": pass
                out.append(o)
            return out
        if p == "/api/order_action" and m == "POST":
            o = c.execute("select o.*, r.owner_id from orders o join restaurants r on r.id=o.rest_id where o.id=?", (int(d["id"]),)).fetchone()
            if not o: return 404, {"error": "مش موجود"}
            a = d.get("action"); st = o["status"]
            if role == "restaurant" and o["owner_id"] == u["id"]:
                if a == "accept" and st == "new": c.execute("update orders set status='accepted' where id=?", (o["id"],))
                elif a == "reject" and st == "new": c.execute("update orders set status='rejected' where id=?", (o["id"],))
                elif a == "ready" and st == "accepted": c.execute("update orders set status='ready' where id=?", (o["id"],))
                else: return 400, {"error": "إجراء غير مناسب"}
            elif role == "courier":
                if a == "take" and st == "ready" and o["courier_id"] is None: c.execute("update orders set status='picked', courier_id=? where id=? and courier_id is null", (u["id"], o["id"]))
                elif a == "deliver" and st == "picked" and o["courier_id"] == u["id"]: c.execute("update orders set status='delivered' where id=?", (o["id"],))
                else: return 400, {"error": "إجراء غير مناسب"}
            elif role == "customer" and o["customer_id"] == u["id"] and a == "cancel" and st == "new": c.execute("update orders set status='cancelled' where id=?", (o["id"],))
            elif role == "admin" and a == "cancel" and st not in ("delivered",): c.execute("update orders set status='cancelled' where id=?", (o["id"],))
            else: return 403, {"error": "غير مسموح"}
            return {"ok": True}
        if role == "restaurant":
            r = c.execute("select * from restaurants where owner_id=?", (u["id"],)).fetchone()
            if not r: return 404, {"error": "لا يوجد مطعم"}
            if p == "/api/my/menu" and m == "GET": return [dict(x) for x in c.execute("select * from items where rest_id=?", (r["id"],))]
            if p == "/api/my/item" and m == "POST":
                nm = str(d.get("name", "")).strip(); pr = float(d.get("price", 0))
                if not nm or pr <= 0: return 400, {"error": "اكتب الاسم والسعر"}
                c.execute("insert into items(rest_id,name,price) values(?,?,?)", (r["id"], nm, pr)); return {"ok": True}
            if p == "/api/my/item_toggle" and m == "POST": c.execute("update items set avail=1-avail where id=? and rest_id=?", (int(d["id"]), r["id"])); return {"ok": True}
            if p == "/api/my/item_delete" and m == "POST": c.execute("delete from items where id=? and rest_id=?", (int(d["id"]), r["id"])); return {"ok": True}
            if p == "/api/my/toggle" and m == "POST": c.execute("update restaurants set is_open=1-is_open where id=?", (r["id"],)); return {"ok": True}
            if p == "/api/my/info" and m == "GET": return dict(r)
        if role == "admin":
            if p == "/api/admin/add_restaurant" and m == "POST":
                nm = str(d.get("name", "")).strip()
                if not nm: return 400, {"error": "اكتب الاسم"}
                code = str(secrets.randbelow(900000) + 100000)
                uid = mk(c, code, code, "restaurant", nm); c.execute("insert into restaurants(owner_id,name) values(?,?)", (uid, nm)); return {"code": code}
            if p == "/api/admin/add_courier" and m == "POST":
                nm = str(d.get("name", "")).strip()
                if not nm: return 400, {"error": "اكتب الاسم"}
                code = str(secrets.randbelow(900000) + 100000); mk(c, code, code, "courier", nm); return {"code": code}
            if p == "/api/admin/users" and m == "GET": return [dict(x) for x in c.execute("select id,phone as code,name,role,active from users where role!='customer' and role!='admin' order by id desc")]
            if p == "/api/admin/user_toggle" and m == "POST": c.execute("update users set active=1-active, token=? where id=? and role!='admin'", (secrets.token_hex(16), int(d["id"]))); return {"ok": True}
            if p == "/api/admin/stats" and m == "GET":
                g = lambda q: c.execute(q).fetchone()[0]
                return {"orders": g("select count(*) from orders"), "delivered": g("select count(*) from orders where status='delivered'"), "active": g("select count(*) from orders where status in ('new','accepted','ready','picked')"), "sales": g("select coalesce(sum(total),0) from orders where status='delivered'"), "customers": g("select count(*) from users where role='customer'"), "couriers": g("select count(*) from users where role='courier'"), "restaurants": g("select count(*) from restaurants")}
        return 404, {"error": "غير موجود"}
    def login(self, c, ph, pw, role):
        u = c.execute("select * from users where phone=?", (ph,)).fetchone()
        if not u or u["pw"] != h(pw, u["salt"]) or not u["active"] or (role and u["role"] != role): return 401, {"error": "الرقم أو كلمة السر غلط"}
        t = secrets.token_hex(16); c.execute("update users set token=? where id=?", (t, u["id"]))
        return {"token": t, "name": u["name"], "role": u["role"]}
if __name__ == "__main__":
    init()
    port = int(os.environ.get("PORT", "8000"))
    print("serving", port, flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
