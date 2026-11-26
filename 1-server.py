import os, re, json, sqlite3, hashlib, secrets, time, threading, mimetypes, base64, ssl, traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    CAIRO = ZoneInfo("Africa/Cairo")
except Exception:
    CAIRO = timezone(timedelta(hours=2))

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
PG = DATABASE_URL.startswith("postgres")
SQLITE_PATH = os.environ.get("DB_PATH", "food.db")
HERE = os.path.dirname(os.path.abspath(__file__))
lock = threading.RLock()
VER = [int(time.time() * 1000)]


# ---------------------------------------------------------------- database
class DB:
    def __init__(self):
        self.c = None
        self.last_count = 0

    def connect(self):
        if PG:
            import pg8000.dbapi
            u = urlparse(DATABASE_URL)
            ctx = None if u.hostname in ("localhost", "127.0.0.1") else ssl.create_default_context()
            self.c = pg8000.dbapi.connect(user=unquote(u.username or ""), password=unquote(u.password or ""),
                                          host=u.hostname, port=u.port or 5432,
                                          database=(u.path or "/").lstrip("/"), ssl_context=ctx, timeout=30)
        else:
            self.c = sqlite3.connect(SQLITE_PATH, timeout=10, check_same_thread=False)
        return self.c

    def conn(self):
        return self.c or self.connect()

    def reset(self):
        try:
            if self.c:
                self.c.close()
        except Exception:
            pass
        self.c = None

    def q(self, sql, params=()):
        if PG:
            sql = sql.replace("?", "%s")
        cur = self.conn().cursor()
        cur.execute(sql, tuple(params))
        if cur.description:
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        else:
            rows = []
        self.last_count = cur.rowcount
        cur.close()
        return rows

    def one(self, sql, params=()):
        r = self.q(sql, params)
        return r[0] if r else None

    def insert(self, sql, params=()):
        r = self.q(sql + " returning id", params)
        return r[0]["id"]

    def commit(self):
        if self.c:
            self.c.commit()

    def rollback(self):
        try:
            if self.c:
                self.c.rollback()
        except Exception:
            self.reset()


db = DB()

SCHEMA = """
create table if not exists users(id AUTOID, phone text unique, pw text, salt text, role text, name text, token text, active integer default 1, contact text default '', created bigint default 0);
create table if not exists restaurants(id AUTOID, owner_id integer, name text, is_open integer default 1, fee double precision default 0, hours_from text default '', hours_to text default '', featured integer default 0);
create table if not exists items(id AUTOID, rest_id integer, name text, price double precision, avail integer default 1, category text default '', pv integer default 0, sold integer default 0);
create table if not exists photos(item_id integer primary key, data text);
create table if not exists orders(id AUTOID, customer_id integer, rest_id integer, name text, phone text, address text, lat double precision, lng double precision, note text default '', items text, subtotal double precision default 0, fee double precision default 0, discount double precision default 0, discount_code text default '', discount_by text default '', total double precision default 0, status text, reject_reason text default '', fail_reason text default '', prep_min integer default 0, courier_id integer, created bigint, accepted_at bigint default 0, picked_at bigint default 0, delivered_at bigint default 0);
create table if not exists discounts(id AUTOID, code text unique, amount double precision, borne_by text, max_uses integer default 0, uses integer default 0, active integer default 1, created bigint default 0);
create table if not exists settings(k text primary key, v text)
"""


def h(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 50000).hex()


def now():
    return int(time.time())


def mk(role, code, name, contact=""):
    salt = secrets.token_hex(8)
    return db.insert("insert into users(phone,pw,salt,role,name,token,contact,created) values(?,?,?,?,?,?,?,?)",
                     (code, h(code, salt), salt, role, name, secrets.token_hex(16), contact, now()))


def new_code():
    while True:
        c = str(secrets.randbelow(900000) + 100000)
        if not db.one("select 1 as x from users where phone=?", (c,)):
            return c


def init():
    with lock:
        ddl = SCHEMA.replace("AUTOID", "serial primary key" if PG else "integer primary key")
        for s in ddl.split(";\n"):
            if s.strip():
                db.q(s.strip().rstrip(";"))
        db.commit()
        if not db.one("select 1 as x from users where role='admin'"):
            code = os.environ.get("ADMIN_CODE") or new_code()
            mk("admin", code, "المدير")
            print("ADMIN created", flush=True)
            if not os.environ.get("ADMIN_CODE"):
                open("admin_login.txt", "w").write(code)
        for k, v in (("banner", ""), ("welcome", "أهلا بيك في 3mac delivery! اختار مطعمك واطلب، والدفع كاش عند الاستلام."), ("contact_phone", "01002992233")):
            if not db.one("select 1 as x from settings where k=?", (k,)):
                db.q("insert into settings(k,v) values(?,?)", (k, v))
        db.commit()


# ---------------------------------------------------------------- helpers
STATUS_GEN = {"new": "جديد", "accepted": "تم القبول", "ready": "جاهز للتوصيل", "picked": "الطيار في الطريق", "delivered": "تم التسليم", "rejected": "مرفوض", "cancelled": "ملغي", "failed": "تعذر التسليم"}
STATUS_CUST = {"new": "في انتظار قبول المطعم", "accepted": "المطعم بيجهز طلبك", "ready": "جاهز وفي انتظار الطيار", "picked": "الطيار في الطريق إليك", "delivered": "تم التسليم", "rejected": "المطعم رفض الطلب", "cancelled": "تم الإلغاء", "failed": "تعذر التسليم"}
OPEN_STATES = ("new", "accepted", "ready", "picked")
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def cairo_now():
    return datetime.now(CAIRO)


def day_start(days_back=0):
    d = cairo_now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_back)
    return int(d.timestamp())


def open_now(r):
    if not r["is_open"]:
        return False
    a, b = r.get("hours_from") or "", r.get("hours_to") or ""
    if not a or not b:
        return True
    t = cairo_now().strftime("%H:%M")
    if a <= b:
        return a <= t < b
    return t >= a or t < b


def setting(k):
    r = db.one("select v from settings where k=?", (k,))
    return r["v"] if r else ""


def fnum(v, lo=0, hi=100000):
    try:
        x = float(v)
    except Exception:
        return None
    if x != x or x < lo or x > hi:
        return None
    return round(x, 2)


def release_discount(o):
    if o.get("discount_code"):
        db.q("update discounts set uses=case when uses>0 then uses-1 else 0 end where code=?", (o["discount_code"],))


def order_out(o, role):
    o = dict(o)
    o["items"] = json.loads(o["items"] or "[]")
    st = o["status"]
    s = (STATUS_CUST if role == "customer" else STATUS_GEN).get(st, st)
    if st == "accepted" and o.get("prep_min"):
        s += " (حوالي %d دقيقة)" % o["prep_min"]
    o["status_ar"] = s
    return o


def sum_orders(rows):
    d = {"count": 0, "subtotal": 0.0, "fees": 0.0, "discount_owner": 0.0, "discount_rest": 0.0, "total": 0.0}
    for o in rows:
        d["count"] += 1
        d["subtotal"] += o["subtotal"] or 0
        d["fees"] += o["fee"] or 0
        d["total"] += o["total"] or 0
        if o["discount_by"] == "restaurant":
            d["discount_rest"] += o["discount"] or 0
        elif o["discount_by"] == "owner":
            d["discount_owner"] += o["discount"] or 0
    return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in d.items()}


BACKUP_TOKENS = {}


# ---------------------------------------------------------------- routes
class Err(Exception):
    def __init__(self, code, msg):
        self.code, self.msg = code, msg


def bad(msg, code=400):
    raise Err(code, msg)


def login_ok(phone, pw, role):
    u = db.one("select * from users where phone=?", (phone,))
    if not u or u["pw"] != h(pw, u["salt"]) or not u["active"] or (role and u["role"] != role):
        bad("الكود غلط أو الحساب موقوف", 401)
    t = secrets.token_hex(16)
    db.q("update users set token=? where id=?", (t, u["id"]))
    return {"token": t, "name": u["name"], "role": u["role"]}


def rest_row(rid):
    return db.one("select r.*, u.active as uactive from restaurants r join users u on u.id=r.owner_id where r.id=?", (rid,))


def route(m, p, d, qs, tok):
    # ---------- public
    if p == "/api/settings" and m == "GET":
        return {"banner": setting("banner"), "welcome": setting("welcome"), "contact_phone": setting("contact_phone")}
    if p == "/api/guest" and m == "POST":
        nm = str(d.get("name", "")).strip()[:60]
        ph = re.sub(r"[^0-9+]", "", str(d.get("phone", "")))[:20]
        if not nm or len(ph) < 6:
            bad("اكتب الاسم ورقم الموبايل")
        uid = mk("customer", "g" + secrets.token_hex(6), nm, ph)
        t = db.one("select token from users where id=?", (uid,))["token"]
        return {"token": t, "name": nm, "role": "customer"}
    if p == "/api/login" and m == "POST":
        return login_ok(str(d.get("phone", "")).strip(), str(d.get("password", "")), d.get("role"))
    mm = re.match(r"^/api/backup/([0-9a-f]{32})$", p)
    if mm and m == "GET":
        exp = BACKUP_TOKENS.pop(mm.group(1), 0)
        if exp < time.time():
            bad("الرابط انتهى، اطلبه تاني", 403)
        return ("BACKUP", None)

    u = db.one("select * from users where token=? and active=1", (tok,)) if tok else None
    if not u:
        bad("سجّل دخول", 401)
    role = u["role"]

    # ---------- shared / customer reads
    if p == "/api/restaurants" and m == "GET":
        rows = db.q("select r.*, u.active as uactive from restaurants r join users u on u.id=r.owner_id where u.active=1")
        out = []
        for r in rows:
            out.append({"id": r["id"], "name": r["name"], "fee": r["fee"], "open": open_now(r), "featured": r["featured"], "hours_from": r["hours_from"], "hours_to": r["hours_to"]})
        out.sort(key=lambda x: (-x["featured"], not x["open"], x["name"]))
        return out
    if p == "/api/search" and m == "GET":
        qq = re.sub(r"[%_\\]", "", (qs.get("q") or [""])[0].strip().lower())[:40]
        if not qq:
            return []
        pat = "%" + qq + "%"
        rows = db.q("select r.*, u.active as uactive from restaurants r join users u on u.id=r.owner_id where u.active=1")
        its = db.q("select rest_id, name from items where avail=1 and lower(name) like ?", (pat,))
        by = {}
        for i in its:
            by.setdefault(i["rest_id"], []).append(i["name"])
        out = []
        for r in rows:
            nm = qq in (r["name"] or "").lower()
            if nm or r["id"] in by:
                out.append({"id": r["id"], "name": r["name"], "fee": r["fee"], "open": open_now(r), "featured": r["featured"], "matches": by.get(r["id"], [])[:3]})
        out.sort(key=lambda x: (-x["featured"], not x["open"], x["name"]))
        return out
    mm = re.match(r"^/api/menu/(\d+)$", p)
    if mm and m == "GET":
        r = rest_row(int(mm.group(1)))
        if not r or not r["uactive"]:
            bad("المطعم غير موجود", 404)
        items = db.q("select id,name,price,category,pv,sold from items where rest_id=? and avail=1 order by category, id", (r["id"],))
        return {"restaurant": {"id": r["id"], "name": r["name"], "fee": r["fee"], "open": open_now(r), "hours_from": r["hours_from"], "hours_to": r["hours_to"]}, "items": items}
    if p == "/api/discount_check" and m == "POST":
        dc = db.one("select * from discounts where code=? and active=1", (str(d.get("code", "")).strip().upper(),))
        if not dc or (dc["max_uses"] and dc["uses"] >= dc["max_uses"]):
            bad("كود الخصم غير صحيح أو انتهى")
        return {"amount": dc["amount"]}

    # ---------- orders
    if p == "/api/order" and m == "POST":
        if role != "customer":
            bad("غير مسموح", 403)
        r = rest_row(int(d.get("rest_id", 0) or 0))
        if not r or not r["uactive"]:
            bad("المطعم غير موجود")
        if not open_now(r):
            bad("المطعم مقفول دلوقتي")
        addr = str(d.get("address", "")).strip()[:300]
        if len(addr) < 3:
            bad("اكتب العنوان")
        ph = re.sub(r"[^0-9+]", "", str(d.get("phone", "")))[:20] or u["contact"]
        if len(ph) < 6:
            bad("اكتب رقم موبايل صحيح")
        note = str(d.get("note", "")).strip()[:200]
        lat = lng = None
        if d.get("lat") not in (None, "") and d.get("lng") not in (None, ""):
            lat, lng = fnum(d["lat"], -90, 90), fnum(d["lng"], -180, 180)
            if lat is None or lng is None:
                lat = lng = None
        its, sub = [], 0.0
        raw_items = d.get("items", [])
        if not isinstance(raw_items, list):
            raw_items = []
        for it in raw_items[:40]:
            try:
                iid, q = int(it["id"]), int(it.get("qty", 1))
            except Exception:
                continue
            row = db.one("select * from items where id=? and rest_id=? and avail=1", (iid, r["id"]))
            if row and 0 < q < 50:
                its.append({"id": row["id"], "name": row["name"], "price": row["price"], "qty": q})
                sub += row["price"] * q
        if not its:
            bad("اختار أصناف")
        if db.one("select count(*) as n from orders where customer_id=? and status in ('new','accepted','ready','picked')", (u["id"],))["n"] >= 3:
            bad("عندك 3 طلبات شغالة، استنى لما تخلص")
        fee = r["fee"] or 0
        disc, dcode, dby = 0.0, "", ""
        code = str(d.get("discount_code", "")).strip().upper()
        if code:
            dc = db.one("select * from discounts where code=? and active=1", (code,))
            if not dc or (dc["max_uses"] and dc["uses"] >= dc["max_uses"]):
                bad("كود الخصم غير صحيح أو انتهى")
            disc = min(dc["amount"], sub + fee)
            dcode, dby = dc["code"], dc["borne_by"]
            db.q("update discounts set uses=uses+1 where id=?", (dc["id"],))
        total = round(sub + fee - disc, 2)
        oid = db.insert("insert into orders(customer_id,rest_id,name,phone,address,lat,lng,note,items,subtotal,fee,discount,discount_code,discount_by,total,status,created) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'new',?)",
                        (u["id"], r["id"], u["name"], ph, addr, lat, lng, note, json.dumps(its, ensure_ascii=False), round(sub, 2), fee, disc, dcode, dby, total, now()))
        for it in its:
            db.q("update items set sold=sold+? where id=?", (it["qty"], it["id"]))
        return {"id": oid, "total": total}

    if p == "/api/orders" and m == "GET":
        base = "select o.*, r.name as rest_name from orders o join restaurants r on r.id=o.rest_id "
        if role == "customer":
            rows = db.q(base + "where o.customer_id=? order by o.id desc limit 60", (u["id"],))
        elif role == "restaurant":
            rows = db.q(base + "where r.owner_id=? order by o.id desc limit 80", (u["id"],))
        elif role == "courier":
            rows = db.q(base + "where (o.status='ready' and o.courier_id is null) or (o.courier_id=? and o.status in ('picked','delivered','failed') and (o.status='picked' or o.picked_at>=?)) order by o.id desc limit 80", (u["id"], day_start()))
        else:
            st = (qs.get("status") or [""])[0]
            day = (qs.get("day") or [""])[0]
            cond, par = [], []
            if st in STATUS_GEN:
                cond.append("o.status=?")
                par.append(st)
            if day == "today":
                cond.append("o.created>=?")
                par.append(day_start())
            rows = db.q(base + ("where " + " and ".join(cond) + " " if cond else "") + "order by o.id desc limit 200", par)
        out = []
        for o in rows:
            o = order_out(o, role)
            if role == "restaurant":
                for k in ("phone", "address", "lat", "lng"):
                    o.pop(k, None)
            if role == "courier" and o["status"] == "ready":
                for k in ("phone", "address", "lat", "lng", "name"):
                    o.pop(k, None)
            if role == "customer":
                o.pop("courier_id", None)
            out.append(o)
        return out

    if p == "/api/order_action" and m == "POST":
        o = db.one("select o.*, r.owner_id from orders o join restaurants r on r.id=o.rest_id where o.id=?", (int(d.get("id", 0) or 0),))
        if not o:
            bad("الطلب مش موجود", 404)
        a, st = d.get("action"), o["status"]
        if role == "restaurant" and o["owner_id"] == u["id"]:
            if a == "accept" and st == "new":
                pm = int(d.get("prep_min", 0) or 0)
                if not 5 <= pm <= 180:
                    bad("اختار وقت التحضير")
                db.q("update orders set status='accepted', prep_min=?, accepted_at=? where id=? and status='new'", (pm, now(), o["id"]))
            elif a == "reject" and st == "new":
                reason = str(d.get("reason", "")).strip()[:100]
                if not reason:
                    bad("اختار سبب الرفض")
                db.q("update orders set status='rejected', reject_reason=? where id=? and status='new'", (reason, o["id"]))
                release_discount(o)
            elif a == "ready" and st == "accepted":
                db.q("update orders set status='ready' where id=? and status='accepted'", (o["id"],))
            else:
                bad("إجراء غير مناسب")
        elif role == "courier":
            if a == "take" and st == "ready" and o["courier_id"] is None:
                db.q("update orders set status='picked', courier_id=?, picked_at=? where id=? and status='ready' and courier_id is null", (u["id"], now(), o["id"]))
                if db.last_count != 1:
                    bad("الأوردر اتاخد")
            elif a == "deliver" and st == "picked" and o["courier_id"] == u["id"]:
                db.q("update orders set status='delivered', delivered_at=? where id=? and status='picked'", (now(), o["id"]))
            elif a == "fail" and st == "picked" and o["courier_id"] == u["id"]:
                reason = str(d.get("reason", "")).strip()[:100]
                if not reason:
                    bad("اختار سبب تعذر التسليم")
                db.q("update orders set status='failed', fail_reason=? where id=? and status='picked'", (reason, o["id"]))
            else:
                bad("إجراء غير مناسب")
        elif role == "customer" and o["customer_id"] == u["id"] and a == "cancel":
            if st != "new":
                bad("المطعم قبل الطلب، مينفعش تلغيه دلوقتي. كلمنا لو في مشكلة")
            db.q("update orders set status='cancelled' where id=? and status='new'", (o["id"],))
            release_discount(o)
        elif role == "admin" and a == "cancel" and st in OPEN_STATES:
            db.q("update orders set status='cancelled' where id=?", (o["id"],))
            release_discount(o)
        else:
            bad("غير مسموح", 403)
        return {"ok": True}

    # ---------- courier
    if p == "/api/my/record" and role == "courier" and m == "GET":
        rows = db.q("select * from orders where courier_id=? and status='delivered' and delivered_at>=? order by delivered_at desc", (u["id"], day_start()))
        failed = db.one("select count(*) as n from orders where courier_id=? and status='failed' and picked_at>=?", (u["id"], day_start()))["n"]
        s = sum_orders(rows)
        return {"delivered": s["count"], "cash": s["total"], "fees": s["fees"], "failed": failed,
                "orders": [{"id": o["id"], "total": o["total"], "fee": o["fee"], "at": o["delivered_at"]} for o in rows]}

    # ---------- restaurant
    if role == "restaurant":
        r = db.one("select * from restaurants where owner_id=?", (u["id"],))
        if not r:
            bad("لا يوجد مطعم", 404)
        if p == "/api/my/info" and m == "GET":
            return {"id": r["id"], "name": r["name"], "is_open": r["is_open"], "open_now": open_now(r), "fee": r["fee"], "hours_from": r["hours_from"], "hours_to": r["hours_to"]}
        if p == "/api/my/menu" and m == "GET":
            return db.q("select id,name,price,avail,category,pv from items where rest_id=? order by category, id", (r["id"],))
        if p == "/api/my/toggle" and m == "POST":
            db.q("update restaurants set is_open=1-is_open where id=?", (r["id"],))
            return {"ok": True}
        if p == "/api/my/hours" and m == "POST":
            a, b = str(d.get("from", "")).strip(), str(d.get("to", "")).strip()
            if (a or b) and not (HHMM.match(a) and HHMM.match(b)):
                bad("اكتب الوقت بالشكل 09:00")
            db.q("update restaurants set hours_from=?, hours_to=? where id=?", (a, b, r["id"]))
            return {"ok": True}
        if p == "/api/my/item" and m == "POST":
            nm = str(d.get("name", "")).strip()[:80]
            pr = fnum(d.get("price"), 0.01, 100000)
            if not nm or pr is None:
                bad("اكتب الاسم والسعر")
            iid = db.insert("insert into items(rest_id,name,price,category) values(?,?,?,?)", (r["id"], nm, pr, str(d.get("category", "")).strip()[:40]))
            return {"id": iid}
        if p in ("/api/my/item_edit", "/api/my/item_toggle", "/api/my/item_delete", "/api/my/photo", "/api/my/photo_delete") and m == "POST":
            mine = db.one("select * from items where id=? and rest_id=?", (int(d.get("id", 0) or 0), r["id"]))
            if not mine:
                bad("الصنف مش موجود", 404)
            if p == "/api/my/item_edit":
                nm = str(d.get("name", "")).strip()[:80]
                pr = fnum(d.get("price"), 0.01, 100000)
                if not nm or pr is None:
                    bad("اكتب الاسم والسعر")
                db.q("update items set name=?, price=?, category=? where id=?", (nm, pr, str(d.get("category", "")).strip()[:40], mine["id"]))
            elif p == "/api/my/item_toggle":
                db.q("update items set avail=1-avail where id=?", (mine["id"],))
            elif p == "/api/my/item_delete":
                db.q("delete from photos where item_id=?", (mine["id"],))
                db.q("delete from items where id=?", (mine["id"],))
            elif p == "/api/my/photo":
                data = str(d.get("data", ""))
                pre = "data:image/jpeg;base64,"
                if not data.startswith(pre) or len(data) > 250000:
                    bad("الصورة غير مناسبة")
                try:
                    raw = base64.b64decode(data[len(pre):], validate=True)
                except Exception:
                    bad("الصورة غير مناسبة")
                if raw[:3] != b"\xff\xd8\xff":
                    bad("الصورة غير مناسبة")
                db.q("delete from photos where item_id=?", (mine["id"],))
                db.q("insert into photos(item_id,data) values(?,?)", (mine["id"], data[len(pre):]))
                db.q("update items set pv=pv+1 where id=?", (mine["id"],))
            else:
                db.q("delete from photos where item_id=?", (mine["id"],))
                db.q("update items set pv=0 where id=?", (mine["id"],))
            return {"ok": True}

    # ---------- admin
    if role == "admin":
        if p == "/api/admin/add_restaurant" and m == "POST":
            nm = str(d.get("name", "")).strip()[:60]
            fee = fnum(d.get("fee", 0), 0, 1000)
            if not nm or fee is None:
                bad("اكتب الاسم ورسوم التوصيل")
            code = new_code()
            uid = mk("restaurant", code, nm)
            db.q("insert into restaurants(owner_id,name,fee) values(?,?,?)", (uid, nm, fee))
            return {"code": code}
        if p == "/api/admin/add_courier" and m == "POST":
            nm = str(d.get("name", "")).strip()[:60]
            if not nm:
                bad("اكتب الاسم")
            code = new_code()
            mk("courier", code, nm)
            return {"code": code}
        if p == "/api/admin/users" and m == "GET":
            return db.q("select u.id,u.phone as code,u.name,u.role,u.active,r.id as rid,r.fee,r.featured from users u left join restaurants r on r.owner_id=u.id where u.role in ('restaurant','courier') order by u.id desc")
        if p == "/api/admin/user_toggle" and m == "POST":
            db.q("update users set active=1-active, token=? where id=? and role in ('restaurant','courier')", (secrets.token_hex(16), int(d.get("id", 0) or 0)))
            return {"ok": True}
        if p == "/api/admin/restaurant_set" and m == "POST":
            fee = fnum(d.get("fee"), 0, 1000)
            if fee is None:
                bad("رسوم غير صحيحة")
            db.q("update restaurants set fee=?, featured=? where id=?", (fee, 1 if d.get("featured") else 0, int(d.get("id", 0) or 0)))
            return {"ok": True}
        if p == "/api/admin/settings" and m == "POST":
            for k, mx in (("banner", 200), ("welcome", 300), ("contact_phone", 20)):
                if k in d:
                    db.q("update settings set v=? where k=?", (str(d[k]).strip()[:mx], k))
            return {"ok": True}
        if p == "/api/admin/discounts" and m == "GET":
            return db.q("select * from discounts order by id desc")
        if p == "/api/admin/discount_add" and m == "POST":
            code = re.sub(r"[^A-Z0-9\u0600-\u06FF]", "", str(d.get("code", "")).strip().upper())[:20]
            amt = fnum(d.get("amount"), 1, 10000)
            by = d.get("borne_by")
            mu = int(d.get("max_uses", 0) or 0)
            if not code or amt is None or by not in ("owner", "restaurant") or mu < 0:
                bad("بيانات الكود ناقصة")
            if db.one("select 1 as x from discounts where code=?", (code,)):
                bad("الكود موجود قبل كده")
            db.q("insert into discounts(code,amount,borne_by,max_uses,created) values(?,?,?,?,?)", (code, amt, by, mu, now()))
            return {"ok": True}
        if p == "/api/admin/discount_toggle" and m == "POST":
            db.q("update discounts set active=1-active where id=?", (int(d.get("id", 0) or 0),))
            return {"ok": True}
        if p == "/api/admin/report" and m == "GET":
            def win(since):
                return db.q("select * from orders where status='delivered' and delivered_at>=?", (since,))
            td, wk, al = win(day_start()), win(day_start(6)), win(0)
            today_orders = db.q("select status from orders where created>=?", (day_start(),))
            bystatus = {}
            for o in today_orders:
                bystatus[o["status"]] = bystatus.get(o["status"], 0) + 1
            per_r = []
            for r in db.q("select id,name from restaurants"):
                rs = [o for o in td if o["rest_id"] == r["id"]]
                per_r.append({"name": r["name"], "delivered": len(rs), "subtotal": round(sum(o["subtotal"] for o in rs), 2)})
            per_c = []
            for c in db.q("select id,name from users where role='courier'"):
                cs = [o for o in td if o["courier_id"] == c["id"]]
                fl = db.one("select count(*) as n from orders where courier_id=? and status='failed' and picked_at>=?", (c["id"], day_start()))["n"]
                per_c.append({"name": c["name"], "delivered": len(cs), "failed": fl, "cash": round(sum(o["total"] for o in cs), 2)})
            return {"today": sum_orders(td), "week": sum_orders(wk), "all": sum_orders(al), "status_today": bystatus, "restaurants": per_r, "couriers": per_c}
        if p == "/api/admin/backup_link" and m == "GET":
            t = secrets.token_hex(16)
            BACKUP_TOKENS[t] = time.time() + 120
            return {"url": "/api/backup/" + t}
    bad("غير موجود", 404)


def backup_data():
    out = {"exported_at": now()}
    for t in ("users", "restaurants", "items", "orders", "discounts", "settings", "photos"):
        rows = db.q("select * from " + t)
        if t == "users":
            for r in rows:
                r.pop("token", None)
                r.pop("pw", None)
                r.pop("salt", None)
        out[t] = rows
    return out


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_json(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def empty(self, code):
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        if p == "/api/ver":
            return self.send_json(200, {"v": VER[0]})
        if p.startswith("/api/"):
            return self.api("GET", p, parse_qs(u.query))
        mm = re.match(r"^/photo/(\d+)$", p)
        if mm:
            r = None
            with lock:
                try:
                    r = db.one("select data from photos where item_id=?", (int(mm.group(1)),))
                    db.commit()
                except Exception:
                    db.rollback()
                    db.reset()
            if not r:
                return self.empty(404)
            b = base64.b64decode(r["data"])
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        if p == "/":
            p = "/index.html"
        if p in ("/customer", "/restaurant", "/courier", "/admin"):
            p += ".html"
        f = os.path.normpath(os.path.join(HERE, p.lstrip("/")))
        if not f.startswith(HERE) or not f.endswith((".html", ".js", ".png")) or not os.path.isfile(f):
            return self.empty(404)
        b = open(f, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", (mimetypes.guess_type(f)[0] or "text/plain") + ("; charset=utf-8" if not f.endswith(".png") else ""))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        u = urlparse(self.path)
        self.api("POST", u.path, parse_qs(u.query))

    def api(self, m, p, qs):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 400000:
                return self.send_json(413, {"error": "الحجم كبير"})
            raw = self.rfile.read(n) if n else b""
            d = json.loads(raw or b"{}") if m == "POST" else {}
            if not isinstance(d, dict):
                return self.send_json(400, {"error": "طلب غير صحيح"})
        except Exception:
            return self.send_json(400, {"error": "طلب غير صحيح"})
        tok = self.headers.get("X-Token", "")
        for attempt in (0, 1):
            with lock:
                try:
                    r = route(m, p, d, qs, tok)
                    if isinstance(r, tuple) and r[0] == "BACKUP":
                        data = backup_data()
                        db.commit()
                        b = json.dumps(data, ensure_ascii=False).encode()
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json; charset=utf-8")
                        self.send_header("Content-Disposition", 'attachment; filename="3mac-backup-%s.json"' % cairo_now().strftime("%Y%m%d"))
                        self.send_header("Content-Length", str(len(b)))
                        self.end_headers()
                        self.wfile.write(b)
                        return
                    db.commit()
                    if m == "POST" and p not in ("/api/login", "/api/guest", "/api/discount_check"):
                        VER[0] = int(time.time() * 1000)
                    return self.send_json(200, r)
                except Err as e:
                    db.rollback()
                    return self.send_json(e.code, {"error": e.msg})
                except (ValueError, TypeError, KeyError):
                    db.rollback()
                    traceback.print_exc()
                    return self.send_json(400, {"error": "بيانات غير صحيحة"})
                except Exception:
                    db.rollback()
                    traceback.print_exc()
                    db.reset()
                    if attempt == 1:
                        return self.send_json(500, {"error": "خطأ مؤقت، جرّب تاني"})


if __name__ == "__main__":
    for i in range(6):
        try:
            init()
            break
        except Exception:
            traceback.print_exc()
            db.reset()
            time.sleep(3)
    port = int(os.environ.get("PORT", "8000"))
    print("serving", port, "pg" if PG else "sqlite", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
