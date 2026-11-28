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
create table if not exists settings(k text primary key, v text);
create table if not exists rest_photos(rest_id integer primary key, data text, pv integer default 0);
create table if not exists courier_loc(uid integer primary key, lat double precision, lng double precision, acc double precision, ts bigint default 0, seen bigint default 0);
create table if not exists courier_issues(id AUTOID, kind text, order_id integer, courier_id integer, created bigint default 0, offline_since bigint default 0, data text default '', notified integer default 0, resolved_at bigint default 0, resolution text default '');
create table if not exists order_offers(id AUTOID, order_id integer, courier_id integer, round integer default 1, offered_at bigint default 0, state text default 'offered', dist double precision);
create table if not exists order_events(id AUTOID, order_id integer, kind text, actor_uid integer default 0, actor_role text default '', actor_name text default '', note text default '', prev text default '', courier_id integer default 0, courier_name text default '', prep integer default 0, ts bigint default 0)
"""


# ================= unified status vocabulary: ONE central place =================
VOC = {
    "placed": "تم إرسال الطلب #{n}",
    "payreq": "تم إرسال الطلب #{n}، في انتظار تأكيد الدفع",
    "paid": "تم تأكيد استلام الدفع للطلب #{n}",
    "accepted": "المطعم قبل الطلب #{n}، مدة التجهيز {prep} دقيقة",
    "ready": "الطلب جاهز، جاري البحث عن طيار",
    "ready_taken": "الطلب جاهز، الطيار {c} في الطريق لاستلامه",
    "picked": "الطيار {c} قبل الطلب وفي الطريق للمطعم",
    "collected": "الطيار {c} استلم الطلب وفي الطريق إلى العميل",
    "collected_cust": "الطيار {c} استلم طلبك وفي الطريق إليك",
    "delivered": "تم تسليم الطلب #{n}",
    "rejected": "المطعم رفض الطلب #{n}، السبب: {note}",
    "cancelled": "تم إلغاء الطلب #{n} من {who}",
    "cancelled_why": "، السبب: {note}",
    "released": "تم سحب الطلب من الطيار {c}، جاري البحث عن طيار آخر",
    "released_why": "، السبب: {note}",
    "released_you": "تم سحب الأوردر منك",
    "failed": "تعذر التسليم، السبب: {note}",
}
WHO_AR = {"customer": "العميل", "restaurant": "المطعم", "admin": "الإدارة", "courier": "الطيار"}
# what the reader must do (empty = nothing)
NEED = {
    "customer": "برجاء الانتظار",
    "restaurant_new": "اقبل الطلب",
    "admin_pay": "تأكد من وصول الفلوس في المحفظة ثم اضغط تم استلام الدفع",
    "customer_pay": "برجاء الانتظار، سيتم تأكيد الدفع قريبا",
    "restaurant_accepted": "جهز الطلب واضغط جاهز",
    "courier_free": "اقبل الأوردر",
    "courier_to_rest": "توجه إلى المطعم الآن",
    "courier_to_cust": "توجه إلى العميل لتسليم الطلب",
}
PROB = {  # admin problem lines, {m} = minutes (filled in the page)
    "new": "تدخل الآن: مستني قبول المطعم من {m} دقيقة",
    "nocourier": "تدخل الآن: مستني طيار من {m} دقيقة",
    "failed": "تدخل الآن: تعذر التسليم، السبب: {note}",
    "held": "تدخل الآن: الطيار استلم الأكل من {m} دقيقة ولسه متسلمش",
    "released": "تدخل الآن: الأوردر مستني طيار جديد",
}
STUCK_S, HELD_S = 120, 2400
KINDS = ("placed", "payreq", "paid", "accepted", "ready", "picked", "collected", "delivered", "rejected", "cancelled", "released", "failed", "offer")
EVRING, EVSEQ, EVC, EVINIT = [], [0], threading.Condition(), [False]


def vsay(e, role=None):
    k = e["kind"]
    if k == "ready" and e.get("courier_name"):
        k = "ready_taken"
    t = VOC[k].format(n=e["order_id"], prep=e.get("prep") or "", c=e.get("courier_name") or "", note=e.get("note") or "", who=WHO_AR.get(e.get("actor_role"), ""))
    if k == "cancelled" and e.get("note"):
        t += VOC["cancelled_why"].format(note=e["note"])
    if k == "collected" and role == "customer":
        t = VOC["collected_cust"].format(c=e.get("courier_name") or "")
    if k == "released" and role == "customer":
        t = "جاري البحث عن طيار آخر لطلبك"
    elif k == "released" and e.get("note"):
        t += VOC["released_why"].format(note=e["note"])
    if role == "courier" and k == "released" and e.get("courier_id") == (e.get("_viewer") or -1):
        t = VOC["released_you"] + ((VOC["released_why"].format(note=e["note"])) if e.get("note") else "")
    if "#" not in VOC[k]:
        t = "طلب #%d، %s" % (e["order_id"], t)
    return t


def was_withdrawn(oid, cid):
    return bool(db.one("select 1 as x from order_events where order_id=? and kind='released' and courier_id=?", (oid, cid)))


def ev(o, kind, u, note="", prep=0):
    """record an order event (DB history + in-memory ring for instant delivery). o = order row before the change."""
    cid, cname = 0, ""
    if kind in ("picked", "collected", "delivered", "failed") and u["role"] == "courier":
        cid, cname = u["id"], u["name"]
    elif kind in ("ready", "cancelled", "released") and o.get("courier_id"):
        cid = o["courier_id"]
        r = db.one("select name from users where id=?", (cid,))
        cname = r["name"] if r else ""
    an = u["name"]
    if u["role"] == "restaurant":
        r = db.one("select name from restaurants where id=?", (o["rest_id"],))
        an = r["name"] if r else an
    ts = now()
    eid = db.insert("insert into order_events(order_id,kind,actor_uid,actor_role,actor_name,note,prev,courier_id,courier_name,prep,ts) values(?,?,?,?,?,?,?,?,?,?,?)",
                    (o["id"], kind, u["id"], u["role"], an, note, o["status"], cid, cname, prep, ts))
    r = db.one("select r.name as rname, r.owner_id from restaurants r where r.id=?", (o["rest_id"],))
    e = {"id": eid, "ts": ts, "order_id": o["id"], "kind": kind, "actor_uid": u["id"], "actor_role": u["role"], "actor_name": an,
         "note": note, "prev": o["status"], "courier_id": cid, "courier_name": cname, "prep": prep,
         "cust_id": o["customer_id"], "owner_id": r["owner_id"] if r else 0, "rest": r["rname"] if r else "", "cust_name": o.get("name") or ""}
    with EVC:
        EVRING.append(e)
        del EVRING[:-500]
        EVSEQ[0] = max(EVSEQ[0], eid)
        EVC.notify_all()


def ev_for(role, u, e):
    """None or {text,snd,warn,oid} for this reader (everyone involved except the actor)."""
    if e["actor_uid"] == u["id"]:
        return None
    if e["kind"] == "offer":
        if role != "courier" or str(u["id"]) != str(e.get("note")):
            return None
        if now() - e["ts"] > PRI_S + 5:
            return None
        return {"text": "أوردر جديد متاح (%s)" % e["rest"], "need": NEED["courier_free"], "snd": True, "warn": False, "oid": e["order_id"], "k": "widen"}
    if role == "admin" and e.get("actor_role") == "system":
        return None
    k = e["kind"]
    ok, snd = False, True
    if k == "cancelled":
        free = e["prev"] in ("accepted", "ready") and not e["courier_id"]
    elif k in ("ready", "accepted"):
        free = not e["courier_id"]
    else:
        free = k == "released"
    if role == "customer":
        ok = e["cust_id"] == u["id"]
    elif role == "restaurant":
        ok = e["owner_id"] == u["id"] and k not in ("accepted", "rejected", "ready", "payreq")
    elif role == "courier":
        if k in ("accepted", "ready", "released"):
            ok = (k == "released") or free or (k == "ready" and e["courier_id"] == u["id"])
        elif k == "cancelled":
            ok = e["courier_id"] == u["id"] or free
        else:
            ok = False
    elif role == "admin":
        ok = True
        snd = k in ("failed", "cancelled", "released", "payreq")
    if ok and role == "courier" and k in ("accepted", "ready") and free and e.get("order_id") and was_withdrawn(e["order_id"], u["id"]):
        ok = False
    if ok and role == "courier" and k in ("accepted", "ready", "released") and free and e.get("order_id"):
        with lock:
            try:
                _o = db.one("select * from orders where id=?", (e["order_id"],))
                _pb = bool(_o) and priority_block(_o, u["id"])
                db.commit()
            except Exception:
                db.rollback()
                db.reset()
                _pb = False
        if _pb:
            ok = False
    if not ok:
        return None
    mine_rel = role == "courier" and k == "released" and e["courier_id"] == u["id"]
    if mine_rel:
        free = False
    t = vsay(dict(e, _viewer=u["id"]), role)
    if role in ("courier", "admin"):
        t += " (%s)" % e["rest"]
    need = ""
    if role == "customer" and k not in ("delivered", "rejected", "cancelled", "failed"):
        need = NEED["customer"]
    elif role == "customer" and k == "payreq":
        need = NEED["customer_pay"]
    elif role == "admin" and k == "payreq":
        need = NEED["admin_pay"]
    elif role == "restaurant" and k in ("placed", "paid"):
        need = NEED["restaurant_new"]
    elif role == "courier" and k in ("accepted", "ready", "released") and free:
        need = NEED["courier_free"]
    elif role == "admin" and k == "released":
        need = PROB["released"]
    elif role == "admin" and k == "failed":
        need = PROB["failed"].replace("{note}", e.get("note") or "")
    return {"text": t, "need": need, "snd": snd, "warn": k in ("rejected", "cancelled", "released", "failed"), "oid": e["order_id"], "k": k}


TOKC = {}


def tok_ok(t):
    return bool(t) and len(t) == 32 and all(c in "0123456789abcdef" for c in t)


def ev_user(tok):
    c = TOKC.get(tok)
    if c and time.time() - c[0] < 60:
        return c[1]
    u = None
    with lock:
        try:
            u = db.one("select id,role,name from users where (' '||token||' ') like ? and active=1", ("% " + tok + " %",)) if tok_ok(tok) else None
        except Exception:
            db.rollback()
            db.reset()
    TOKC[tok] = (time.time(), u)
    if len(TOKC) > 500:
        TOKC.clear()
    return u


def order_extras(rows, role):
    """adds line / need / stage / tl / prob / ages to each order dict (rows are order_out dicts)."""
    ids = [o["id"] for o in rows]
    byo = {}
    if ids:
        for e in db.q("select * from order_events where order_id in (%s) and kind<>'offer' order by id" % ",".join(str(int(i)) for i in ids)):
            byo.setdefault(e["order_id"], []).append(dict(e))
    t_now = now()
    for o in rows:
        evs = byo.get(o["id"], [])
        if not evs:  # old order from before events existed: rebuild from stored timestamps
            cn = o.get("courier_name") or ""
            for kind, ts in (("placed", o.get("created")), ("accepted", o.get("accepted_at")), ("ready", o.get("ready_at")), ("picked", o.get("picked_at")), ("collected", o.get("collected_at")), ("delivered", o.get("delivered_at"))):
                if ts:
                    evs.append({"order_id": o["id"], "kind": kind, "ts": ts, "actor_role": "", "actor_name": "", "note": "", "prep": o.get("prep_min") or 0,
                                "courier_name": cn if kind in ("picked", "collected", "delivered") else ""})
        tl = []
        for ei, e in enumerate(evs):
            anon = role == "customer" and e["kind"] == "picked" and any(x["kind"] == "released" and x.get("courier_id") == e.get("courier_id") for x in evs[ei + 1:])
            who = e.get("actor_name") or ""
            if e.get("actor_role") == "courier":
                who = "" if (role == "customer" and e["kind"] == "picked" and any(x["kind"] == "released" and x.get("courier_id") == e.get("courier_id") for x in evs[ei + 1:])) else "الطيار " + who
            elif e.get("actor_role") == "customer":
                who = "العميل " + who
            elif e.get("actor_role") == "admin":
                who = "الإدارة"
            hide = role == "customer" and e["kind"] == "released"
            tl.append({"ts": e["ts"], "k": e["kind"], "who": "" if hide else who, "text": ("طلب #%d، تم تعيين طيار لطلبك" % e["order_id"]) if anon else vsay(e, role), "note": "" if hide else (e.get("note") or ""), "prep": e.get("prep") or 0, "c": "" if (hide or anon) else (e.get("courier_name") or ""), "r": e.get("actor_role") or ""})
        o["tl"] = tl
        st = o["status"]
        last = evs[-1] if evs else None
        if st in ("delivered", "rejected", "cancelled", "failed") or not last:
            if st == "rejected":
                o["line"] = VOC["rejected"].format(n=o["id"], note=o.get("reject_reason") or "")
            elif st == "failed":
                o["line"] = VOC["failed"].format(note=o.get("fail_reason") or "")
            elif st == "delivered":
                o["line"] = VOC["delivered"].format(n=o["id"])
            elif st == "cancelled":
                o["line"] = VOC["cancelled"].format(n=o["id"], who="الإدارة") if not last else vsay(last, role)
            else:
                o["line"] = VOC["placed"].format(n=o["id"])
        else:
            o["line"] = vsay(last, role)
        o["stage"] = {"pay": 0, "new": 0, "accepted": 1, "ready": 2, "picked": 3, "delivered": 4}.get(st, -1)
        need = ""
        if role == "customer":
            need = (NEED["customer_pay"] if st == "pay" else NEED["customer"]) if st in OPEN_STATES else ""
        elif role == "admin" and st == "pay":
            need = NEED["admin_pay"]
        elif role == "restaurant":
            need = NEED["restaurant_new"] if st == "new" else (NEED["restaurant_accepted"] if st == "accepted" or (st == "picked" and not o.get("ready_at")) else "")
        elif role == "courier":
            if st in ("accepted", "ready") and not o.get("courier_id"):
                need = NEED["courier_free"]
            elif st == "picked":
                need = NEED["courier_to_cust"] if o.get("collected_at") else NEED["courier_to_rest"]
        o["need"] = need
        # when it became available to couriers (first alert for the 2/5/10 min reminders)
        av = 0
        if st in ("accepted", "ready") and not o.get("courier_id"):
            for e in evs:
                if e["kind"] in ("accepted", "released"):
                    av = e["ts"]
            av = av or o.get("accepted_at") or o.get("created") or t_now
        o["avail_age"] = (t_now - av) if av else None
        o["created_age"] = t_now - (o.get("created") or t_now)
        o["held_age"] = (t_now - o["collected_at"]) if st == "picked" and o.get("collected_at") else None
        o["rel_n"] = sum(1 for e in evs if e["kind"] == "released")
    if role == "admin" and rows:
        rows[0]["pt"] = {"tpl": PROB, "stuck": STUCK_S, "held": HELD_S}
    return rows


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
        try:
            db.q("alter table orders add column ready_at bigint default 0")
            db.commit()
        except Exception:
            db.rollback()
        try:
            db.q("alter table orders add column collected_at bigint default 0")
            db.commit()
            db.q("update orders set collected_at=picked_at where picked_at>0 and (status in ('delivered','failed') or (status='picked' and ready_at>0))")
            db.commit()
        except Exception:
            db.rollback()
        try:
            db.q("alter table restaurants add column promo text default ''")
            db.commit()
        except Exception:
            db.rollback()
        try:
            db.q("alter table restaurants add column cat text default 'rest'")
            db.commit()
        except Exception:
            db.rollback()
        try:
            db.q("alter table orders add column loc_acc double precision")
            db.commit()
        except Exception:
            db.rollback()
        try:
            db.q("alter table restaurants add column show_fee integer default 1")
            db.commit()
        except Exception:
            db.rollback()
        for _c in ("lat", "lng"):
            try:
                db.q("alter table restaurants add column %s double precision" % _c)
                db.commit()
            except Exception:
                db.rollback()
        try:
            db.q("alter table orders add column loc_note text default ''")
            db.commit()
        except Exception:
            db.rollback()
        for _col in ("pay_method text default 'cash'", "pay_ref text default ''", "pay_img text default ''"):
            try:
                db.q("alter table orders add column " + _col)
                db.commit()
            except Exception:
                db.rollback()
        _ac = os.environ.get("ADMIN_CODE")
        _ad = db.one("select * from users where role='admin' order by id limit 1")
        if _ac and _ad and _ad["phone"] != _ac and not db.one("select 1 as x from users where phone=? and id<>?", (_ac, _ad["id"])):
            _sl = secrets.token_hex(8)
            db.q("update users set phone=?, pw=?, salt=?, token=? where id=?", (_ac, h(_ac, _sl), _sl, secrets.token_hex(16), _ad["id"]))
            db.commit()
            print("ADMIN code updated from ADMIN_CODE", flush=True)
        if not db.one("select 1 as x from users where role='admin'"):
            code = os.environ.get("ADMIN_CODE") or new_code()
            mk("admin", code, "المدير")
            print("ADMIN created", flush=True)
            if not os.environ.get("ADMIN_CODE"):
                open("admin_login.txt", "w").write(code)
        for k, v in (("banner", ""), ("welcome", "يسعدنا خدمتك. اختر المطعم الذي تفضله وسنوصل طلبك في أسرع وقت."), ("contact_phone", "01002992233"), ("pay_on", "1"), ("pay_vf", "01002992233"), ("pay_ip", "atta752@instapay"), ("pay_link", "https://ipn.eg/S/atta752/instapay/15bdnp"), ("pay_name", "محمود أحمد عطا")):
            if not db.one("select 1 as x from settings where k=?", (k,)):
                db.q("insert into settings(k,v) values(?,?)", (k, v))
        db.commit()


# ---------------------------------------------------------------- helpers
STATUS_GEN = {"pay": "في انتظار الدفع", "new": "جديد", "accepted": "تم القبول", "ready": "الأوردر جاهز", "picked": "الطيار في الطريق", "delivered": "تم التسليم", "rejected": "مرفوض", "cancelled": "ملغي", "failed": "تعذر التسليم"}
STATUS_CUST = {"pay": "في انتظار تأكيد الدفع", "new": "في انتظار قبول المطعم", "accepted": "المطعم بيجهز طلبك", "ready": "جاهز وفي انتظار الطيار", "picked": "الطيار في الطريق إليك", "delivered": "تم التسليم", "rejected": "المطعم رفض الطلب", "cancelled": "تم الإلغاء", "failed": "تعذر التسليم"}
OPEN_STATES = ("pay", "new", "accepted", "ready", "picked")
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


def fnum(v, lo=0, hi=100000, nd=2):
    try:
        x = float(v)
    except Exception:
        return None
    if x != x or x < lo or x > hi:
        return None
    return round(x, nd)


def release_discount(o):
    if o.get("discount_code"):
        db.q("update discounts set uses=case when uses>0 then uses-1 else 0 end where code=?", (o["discount_code"],))


def release_items(o):
    try:
        for it in json.loads(o.get("items") or "[]"):
            db.q("update items set sold=case when sold>=? then sold-? else 0 end where id=?", (it["qty"], it["qty"], it["id"]))
    except Exception:
        pass


def order_out(o, role):
    o = dict(o)
    o["items"] = json.loads(o["items"] or "[]")
    o["has_img"] = 1 if o.get("pay_img") else 0
    o.pop("pay_img", None)
    st = o["status"]
    s = (STATUS_CUST if role == "customer" else STATUS_GEN).get(st, st)
    if st == "accepted" and o.get("prep_min"):
        s = ("جاري التجهيز" if role == "courier" else s) + " (حوالي %d دقيقة)" % o["prep_min"]
    if st == "picked" and not o.get("collected_at"):
        if not o.get("ready_at"):
            s = "وصل مندوب التوصيل إلى المطعم، وينتظر تجهيز طلبك لاستلامه." if role == "customer" else "جاري التجهيز، توجه إلى المطعم الآن"
        else:
            s = "مندوب التوصيل في طريقه إلى المطعم لاستلام طلبك." if role == "customer" else "الأوردر جاهز"
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


FAILS = {}
LOCK_N, LOCK_WIN, LOCK_S = 5, 600, 300


def login_ok(phone, pw, role):
    tn = time.time()
    fl = [x for x in FAILS.get(phone, []) if tn - x < LOCK_WIN]
    if len(fl) >= LOCK_N and tn - fl[-1] < LOCK_S:
        FAILS[phone] = fl
        bad("محاولات كثيرة غير صحيحة. برجاء المحاولة بعد %d دقائق" % max(1, int((LOCK_S - (tn - fl[-1])) // 60) + 1), 429)
    u = db.one("select * from users where phone=?", (phone,))
    if not u or u["pw"] != h(pw, u["salt"]) or not u["active"] or (role and u["role"] != role):
        fl.append(tn)
        FAILS[phone] = fl[-LOCK_N:]
        if len(FAILS) > 5000:
            FAILS.clear()
        bad("الكود غلط أو الحساب موقوف", 401)
    FAILS.pop(phone, None)
    t = secrets.token_hex(16)
    keep = {"restaurant": 3, "admin": 2}.get(u["role"], 1)
    old = [x for x in (u["token"] or "").split() if tok_ok(x)]
    db.q("update users set token=? where id=?", (" ".join((old + [t])[-keep:]), u["id"]))
    return {"token": t, "name": u["name"], "role": u["role"]}


def rest_pv():
    return {x["rest_id"]: x["pv"] for x in db.q("select rest_id, pv from rest_photos")}


def clean_promo(v):
    t = re.sub(r"[\x00-\x1f\x7f<>]", " ", str(v or ""))
    return re.sub(r"\s+", " ", t).strip()[:40]


CATS = ("rest", "groc", "pharm", "shop")


def rest_row(rid):
    return db.one("select r.*, u.active as uactive from restaurants r join users u on u.id=r.owner_id where r.id=?", (rid,))



# ================= courier location, nearest-courier priority, disconnect guard =================
MAXACT = int(os.environ.get("T_MAXACT", 2))
RETRY_S = int(os.environ.get("T_RETRY", 600))
PRI_S, FRESH_S, CUT_S, LONG_S = [int(os.environ.get(k, v)) for k, v in (("T_PRI", 45), ("T_FRESH", 120), ("T_CUT", 300), ("T_LONG", 1200))]
SYSTEM = {"id": 0, "role": "system", "name": "النظام"}


def hav(a, b, c, d):
    import math
    r = 6371.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = p2 - p1, math.radians(d - b)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x))


def avail_since(o):
    r = db.one("select max(ts) as t from order_events where order_id=? and kind in ('accepted','released')", (o["id"],))
    return (r and r["t"]) or o.get("accepted_at") or o.get("created") or now()


def cur_offer(o):
    return db.one("select * from order_offers where order_id=? and state='offered' and offered_at>? order by id desc limit 1", (o["id"], now() - PRI_S))


def priority_block(o, cid):
    """A free order is visible/takeable only for the courier it is currently offered to."""
    if o["status"] not in ("accepted", "ready") or o.get("courier_id"):
        return False
    c = cur_offer(o)
    return not (c and c["courier_id"] == cid)


def active_count(cid):
    r = db.one("select count(*) as n from orders where courier_id=? and status='picked'", (cid,))
    return (r and r["n"]) or 0


def pick_next(o, rnd):
    """next courier for this round: nearest by straight line; couriers with a heartbeat but no fresh fix come last."""
    r = db.one("select lat,lng from restaurants where id=?", (o["rest_id"],))
    has = bool(r and r["lat"] is not None and r["lng"] is not None)
    done = set(x["courier_id"] for x in db.q("select courier_id from order_offers where order_id=? and round=?", (o["id"], rnd)))
    cands = []
    wd = set(x["courier_id"] for x in db.q("select courier_id from order_events where order_id=? and kind='released'", (o["id"],)))
    act = {x["courier_id"]: x["n"] for x in db.q("select courier_id, count(*) as n from orders where status='picked' and courier_id is not null group by courier_id")}
    for c in db.q("select l.uid,l.lat,l.lng,l.ts from courier_loc l join users u on u.id=l.uid where u.active=1 and u.role='courier' and l.seen>=?", (now() - FRESH_S,)):
        if c["uid"] in done or c["uid"] in wd:
            continue
        if act.get(c["uid"], 0) >= MAXACT:
            continue
        fix = has and c["lat"] is not None and c["ts"] >= now() - FRESH_S
        d = hav(r["lat"], r["lng"], c["lat"], c["lng"]) if fix else None
        cands.append((0 if fix else 1, d if d is not None else 0, c["uid"], d))
    cands.sort()
    return cands[0] if cands else None


def log_once(kind, o, why):
    if not db.one("select 1 as x from courier_issues where order_id=? and kind=? and resolved_at=0", (o["id"], kind)):
        add_issue(kind, o, 0, 0, {"rule": why})


def order_snapshot(o):
    o = dict(o)
    for k in ("pay_img",):
        o.pop(k, None)
    try:
        o["items"] = json.loads(o.get("items") or "[]")
    except Exception:
        pass
    o["events"] = [{"ts": e["ts"], "kind": e["kind"], "who": e.get("actor_name") or "", "courier": e.get("courier_name") or "", "note": e.get("note") or ""}
                   for e in db.q("select * from order_events where order_id=? and kind<>'offer' order by id", (o["id"],))]
    rr = db.one("select name,lat,lng from restaurants where id=?", (o["rest_id"],))
    o["restaurant"] = dict(rr) if rr else {}
    return o


def add_issue(kind, o, cid, offline_since, extra=None):
    c = (db.one("select id,name,contact from users where id=?", (cid,)) if cid else None) or {}
    l = (db.one("select lat,lng,acc,ts,seen from courier_loc where uid=?", (cid,)) if cid else None) or {}
    cj = {"id": cid, "name": c.get("name", ""), "contact": c.get("contact", ""), "last_lat": l.get("lat"), "last_lng": l.get("lng"), "last_fix_at": l.get("ts"), "last_seen_at": l.get("seen")}
    data = {"courier": cj, "order": order_snapshot(o), "extra": extra or {}}
    db.insert("insert into courier_issues(kind,order_id,courier_id,created,offline_since,data) values(?,?,?,?,?,?)",
              (kind, o["id"], cid, now(), offline_since, json.dumps(data, ensure_ascii=False, default=str)))


SUSP = {}


SUSC = {}


def sus(o, u, a, why, need=1):
    """silently log a suspicious courier request (throttled: one per courier/order/action per minute); never raises."""
    try:
        k = (o["id"], u["id"], a)
        if need > 1:  # a stale button press is normal: only repeated attempts count
            SUSC[k] = [x for x in SUSC.get(k, []) if now() - x < 600] + [now()]
            if len(SUSC[k]) < need:
                return
        if now() - SUSP.get(k, 0) < 60:
            return
        SUSP[k] = now()
        if len(SUSP) > 5000:
            SUSP.clear()
        add_issue("suspicious_action", o, u["id"], 0, {"rule": "محاولة مش مسموحة من الطيار: " + why, "action": str(a)[:30]})
        db.commit()
    except Exception:
        traceback.print_exc()
        try:
            db.rollback()
            db.reset()
        except Exception:
            pass


def guard_once():
    t = now()
    with lock:
        try:
            # 1) courier took the order, restaurant pressed ready, courier not collected, offline >= CUT_S: back to every courier
            for o in db.q("select * from orders where status='picked' and (collected_at is null or collected_at=0) and courier_id is not null"):
                l = db.one("select seen from courier_loc where uid=?", (o["courier_id"],))
                seen = (l and l["seen"]) or 0
                if t - max(seen, o.get("picked_at") or 0) > CUT_S:
                    db.q("update orders set status=(case when ready_at>0 then 'ready' else 'accepted' end), courier_id=null, picked_at=0 where id=? and status='picked' and courier_id=? and (collected_at is null or collected_at=0)", (o["id"], o["courier_id"]))
                    if db.last_count == 1:
                        add_issue("released_offline", o, o["courier_id"], seen, {"rule": "الطيار قبل الأوردر وانقطع 5 دقايق قبل ما يستلم، فالأوردر اتسحب منه واتعرض على الأقرب التالي"})
                        ev(o, "released", SYSTEM, note="انقطاع اتصال الطيار")
                        VER[0] = int(time.time() * 1000)
            # 2) picked up the food and offline >= LONG_S: keep going, only log
            for o in db.q("select * from orders where status='picked' and collected_at>0 and courier_id is not null"):
                l = db.one("select seen from courier_loc where uid=?", (o["courier_id"],))
                seen = (l and l["seen"]) or 0
                if t - max(seen, o["collected_at"]) > LONG_S and not db.one("select 1 as x from courier_issues where order_id=? and kind='offline_after_pickup'", (o["id"],)):
                    add_issue("offline_after_pickup", o, o["courier_id"], max(seen, o["collected_at"]), {"rule": "الطيار استلم الأكل وانقطع 20 دقيقة. الأوردر فاضل معاه ومفيش تدخل، والتسليم هيتسجل أول ما النت يرجع"})
            # resolve open logs when the order is closed
            for i in db.q("select i.id, o.status, o.delivered_at from courier_issues i join orders o on o.id=i.order_id where i.resolved_at=0 and i.kind='offline_after_pickup' and o.status in ('delivered','failed')"):
                db.q("update courier_issues set resolved_at=?, resolution=? where id=?", (t, "اتسلم بعد رجوع الاتصال" if i["status"] == "delivered" else "اتسجل تعذر التوصيل", i["id"]))
            # 3) sequential offers: nearest courier first, then the next one (never everyone at once)
            for o in db.q("select * from orders where status in ('accepted','ready') and courier_id is null and not exists (select 1 from order_offers f where f.order_id=orders.id and f.state='offered' and f.offered_at>?)", (now() - PRI_S,)):
                last = db.one("select max(round) as r, max(offered_at) as t from order_offers where order_id=?", (o["id"],))
                rnd = (last and last["r"]) or 1
                db.q("update order_offers set state='timeout' where order_id=? and state='offered' and offered_at<=?", (o["id"], t - PRI_S))
                nx = pick_next(o, rnd)
                if nx is None and rnd == 1 and last and last["t"] and t - last["t"] >= PRI_S + RETRY_S:
                    rnd = 2  # one single delayed second round for those who declined / timed out (withdrawn stay excluded)
                    nx = pick_next(o, rnd)
                    if nx is not None:
                        add_issue("second_round", o, 0, 0, {"rule": "مفيش طيار قبل الأوردر لمدة 10 دقايق، اتعرض تاني مرة واحدة على اللي رفضوا أو معدّوش المهلة"})
                if nx is None:
                    if last and last["t"]:
                        log_once("no_courier_available", o, "كل الطيارين المتاحين اتعرض عليهم الأوردر ورفضوا أو معدّوش المهلة. مش هيتعرض عليهم تاني، وهيتعرض على أي طيار جديد يظهر")
                    elif not db.one("select 1 as x from courier_loc where seen>=?", (t - FRESH_S,)):
                        log_once("no_courier_available", o, "مفيش أي طيار متصل وقت جاهزية الأوردر. السيستم هيعرضه أول ما يظهر طيار")
                    continue
                db.insert("insert into order_offers(order_id,courier_id,round,offered_at,state,dist) values(?,?,?,?,?,?)", (o["id"], nx[2], rnd, t, "offered", nx[3]))
                ev(o, "offer", SYSTEM, note=str(nx[2]))
                if not db.one("select 1 as x from restaurants where id=? and lat is not null", (o["rest_id"],)):
                    log_once("restaurant_no_location", o, "المطعم من غير موقع متسجل، الترتيب مش بالأقرب")
            for i in db.q("select i.id from courier_issues i join orders o on o.id=i.order_id where i.resolved_at=0 and i.kind='released_offline' and (o.status in ('delivered','failed','cancelled') or (o.courier_id is not null and o.courier_id<>i.courier_id))"):
                db.q("update courier_issues set resolved_at=?, resolution=? where id=?", (t, "الأوردر اتاخد من طيار تاني", i["id"]))
            for i in db.q("select i.id from courier_issues i join orders o on o.id=i.order_id where i.resolved_at=0 and i.kind in ('no_courier_available','restaurant_no_location') and (o.courier_id is not null or o.status not in ('accepted','ready'))"):
                db.q("update courier_issues set resolved_at=?, resolution=? where id=?", (t, "اتحلت", i["id"]))
            db.commit()
        except Exception:
            traceback.print_exc()
            db.rollback()
            db.reset()


def guard_loop():
    time.sleep(2)
    while True:
        try:
            guard_once()
        except Exception:
            traceback.print_exc()
        time.sleep(int(os.environ.get("T_TICK", 3)))


def route(m, p, d, qs, tok):
    # ---------- public
    if p == "/api/settings" and m == "GET":
        return {"banner": setting("banner"), "welcome": setting("welcome"), "contact_phone": setting("contact_phone"),
                "pay_on": setting("pay_on"), "pay_vf": setting("pay_vf"), "pay_ip": setting("pay_ip"), "pay_link": setting("pay_link"), "pay_name": setting("pay_name")}
    if p == "/api/guest" and m == "POST":
        nm = str(d.get("name", "")).strip()[:60]
        ph = re.sub(r"[^0-9+]", "", str(d.get("phone", "")))[:20]
        if not nm or len(ph) < 6:
            bad("برجاء كتابة الاسم ورقم الموبايل")
        uid = mk("customer", "g" + secrets.token_hex(6), nm, ph)
        t = db.one("select token from users where id=?", (uid,))["token"]
        return {"token": t, "name": nm, "role": "customer"}
    if p == "/api/login" and m == "POST":
        return login_ok(str(d.get("phone", "")).strip(), str(d.get("password", "")), d.get("role"))
    mm = re.match(r"^/api/backup/([0-9a-f]{32})$", p)
    if mm and m == "GET":
        exp = BACKUP_TOKENS.get(mm.group(1), 0)
        if exp < time.time():
            bad("انتهت صلاحية الرابط، برجاء طلبه مرة أخرى", 403)
        return ("BACKUP", None)

    u = db.one("select * from users where (' '||token||' ') like ? and active=1", ("% " + tok + " %",)) if tok_ok(tok) else None
    if not u:
        bad("برجاء تسجيل الدخول", 401)
    role = u["role"]

    # ---------- shared / customer reads
    if p == "/api/restaurants" and m == "GET":
        rows = db.q("select r.*, u.active as uactive from restaurants r join users u on u.id=r.owner_id where u.active=1")
        out = []
        pv = rest_pv()
        for r in rows:
            out.append({"id": r["id"], "name": r["name"], "fee": r["fee"], "open": open_now(r), "featured": r["featured"], "hours_from": r["hours_from"], "hours_to": r["hours_to"], "promo": r.get("promo") or "", "show_fee": 0 if r.get("show_fee") == 0 else 1, "cat": r.get("cat") or "rest", "has_photo": 1 if r["id"] in pv else 0, "pv": pv.get(r["id"], 0)})
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
        pv = rest_pv()
        for r in rows:
            nm = qq in (r["name"] or "").lower()
            if nm or r["id"] in by:
                out.append({"id": r["id"], "name": r["name"], "fee": r["fee"], "open": open_now(r), "featured": r["featured"], "matches": by.get(r["id"], [])[:3], "promo": r.get("promo") or "", "show_fee": 0 if r.get("show_fee") == 0 else 1, "cat": r.get("cat") or "rest", "has_photo": 1 if r["id"] in pv else 0, "pv": pv.get(r["id"], 0)})
        out.sort(key=lambda x: (-x["featured"], not x["open"], x["name"]))
        return out
    mm = re.match(r"^/api/menu/(\d+)$", p)
    if mm and m == "GET":
        r = rest_row(int(mm.group(1)))
        if not r or not r["uactive"]:
            bad("المطعم غير متاح حاليًا", 404)
        items = db.q("select id,name,price,category,pv,sold from items where rest_id=? and avail=1 order by category, id", (r["id"],))
        _rpv = rest_pv().get(r["id"])
        return {"restaurant": {"id": r["id"], "name": r["name"], "fee": r["fee"], "open": open_now(r), "hours_from": r["hours_from"], "hours_to": r["hours_to"], "show_fee": 0 if r.get("show_fee") == 0 else 1, "has_photo": 1 if _rpv is not None else 0, "pv": _rpv or 0}, "items": items}
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
            bad("المطعم غير متاح حاليًا")
        if not open_now(r):
            bad("المطعم مغلق حاليًا")
        addr = str(d.get("address", "")).strip()[:300]
        if len(addr) < 3:
            bad("برجاء كتابة العنوان")
        ph = re.sub(r"[^0-9+]", "", str(d.get("phone", "")))[:20] or u["contact"]
        if len(ph) < 6:
            bad("برجاء كتابة رقم موبايل صحيح")
        note = str(d.get("note", "")).strip()[:200]
        lat = lng = None
        if d.get("lat") not in (None, "") and d.get("lng") not in (None, ""):
            lat, lng = fnum(d["lat"], -90, 90, 6), fnum(d["lng"], -180, 180, 6)
            if lat is None or lng is None:
                lat = lng = None
        lnote = str(d.get("landmark", "")).strip()[:200]
        if len(lnote) < 3:
            bad("برجاء كتابة علامة مميزة قريبة من العنوان")
        lacc = None
        if lat is not None:
            lacc = fnum(d.get("acc"), 0, 100000) if d.get("acc") not in (None, "") else None
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
            bad("برجاء اختيار الأصناف")
        if db.one("select count(*) as n from orders where customer_id=? and status in ('pay','new','accepted','ready','picked')", (u["id"],))["n"] >= 3:
            bad("لديك 3 طلبات قيد التنفيذ، برجاء الانتظار حتى يكتمل أحدها")
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
        dup = db.one("select id, total from orders where customer_id=? and rest_id=? and address=? and total=? and status='new' and created>=? order by id desc limit 1", (u["id"], r["id"], addr, total, now() - 15))
        if dup:
            if code:
                db.q("update discounts set uses=case when uses>0 then uses-1 else 0 end where code=?", (code,))
            return {"id": dup["id"], "total": dup["total"]}
        pm = str(d.get("pay_method") or "cash")
        pref, pimg = "", ""
        if pm not in ("cash", "vodafone", "instapay") or (pm != "cash" and setting("pay_on") != "1"):
            pm = "cash"
        if pm != "cash":
            pref = re.sub(r"[^0-9]", "", str(d.get("pay_ref", "")))
            if len(pref) != 4:
                bad("برجاء كتابة آخر 4 أرقام من رقم عملية التحويل")
            pimg = str(d.get("pay_img") or "")
            if not pimg.startswith("data:image/") or len(pimg) > 300000:
                bad("برجاء رفع صورة إيصال التحويل (صورة واضحة وصغيرة الحجم)")
            if db.one("select 1 as x from orders where pay_method=? and pay_ref=? and total=? and status<>'cancelled' and created>=?", (pm, pref, total, now() - 172800)):
                db.q("update discounts set uses=case when uses>0 then uses-1 else 0 end where code=?", (code,)) if code else None
                bad("رقم العملية هذا مستخدم من قبل في طلب آخر، برجاء مراجعته")
        oid = db.insert("insert into orders(customer_id,rest_id,name,phone,address,lat,lng,loc_acc,loc_note,note,items,subtotal,fee,discount,discount_code,discount_by,total,status,created,pay_method,pay_ref,pay_img) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (u["id"], r["id"], u["name"], ph, addr, lat, lng, lacc, lnote, note, json.dumps(its, ensure_ascii=False), round(sub, 2), fee, disc, dcode, dby, total, "new" if pm == "cash" else "pay", now(), pm, pref, pimg))
        for it in its:
            db.q("update items set sold=sold+? where id=?", (it["qty"], it["id"]))
        ev(db.one("select * from orders where id=?", (oid,)), "placed" if pm == "cash" else "payreq", u)
        return {"id": oid, "total": total}

    if p == "/api/orders" and m == "GET":
        base = "select o.*, r.name as rest_name, (select x.name from users x where x.id=o.courier_id) as courier_name from orders o join restaurants r on r.id=o.rest_id "
        if role == "customer":
            rows = db.q(base + "where o.customer_id=? order by o.id desc limit 60", (u["id"],))
        elif role == "restaurant":
            rows = db.q(base + "where r.owner_id=? and o.status<>'pay' order by o.id desc limit 80", (u["id"],))
        elif role == "courier":
            rows = db.q(base + "where (o.status in ('accepted','ready') and o.courier_id is null and not exists(select 1 from order_events w where w.order_id=o.id and w.kind='released' and w.courier_id=?)) or (o.courier_id=? and o.status in ('picked','delivered','failed') and (o.status='picked' or o.picked_at>=?)) order by o.id desc limit 80", (u["id"], u["id"], day_start()))
        else:
            st = (qs.get("status") or [""])[0]
            day = (qs.get("day") or [""])[0]
            cond, par = [], []
            if (qs.get("view") or [""])[0] == "board":
                rows = db.q(base + "where o.status in ('pay','new','accepted','ready','picked') or o.created>=? order by o.id desc limit 300", (day_start(),))
                st = "__board__"
                day = ""
            if st in STATUS_GEN:
                cond.append("o.status=?")
                par.append(st)
            if day == "today":
                cond.append("o.created>=?")
                par.append(day_start())
            if st != "__board__":
                rows = db.q(base + ("where " + " and ".join(cond) + " " if cond else "") + "order by o.id desc limit 200", par)
        out = []
        _live = {}
        if role == "courier":
            _live = {x["order_id"]: x["courier_id"] for x in db.q("select order_id, courier_id from order_offers where state='offered' and offered_at>? order by id", (now() - PRI_S,))}
        for o in rows:
            o = order_out(o, role)
            if role == "restaurant":
                for k in ("phone", "address", "lat", "lng", "loc_acc", "loc_note"):
                    o.pop(k, None)
            if role == "courier" and o["status"] in ("accepted", "ready") and not o.get("courier_id") and _live.get(o["id"]) != u["id"]:
                continue
            if role == "courier" and (o["status"] in ("accepted", "ready") or (o["status"] == "picked" and not o.get("collected_at"))):
                for k in ("phone", "address", "lat", "lng", "name", "loc_acc", "loc_note"):
                    o.pop(k, None)
            if role == "customer":
                o.pop("courier_id", None)
            out.append(o)
        return order_extras(out, role)

    if p == "/api/order_action" and m == "POST":
        o = db.one("select o.*, r.owner_id from orders o join restaurants r on r.id=o.rest_id where o.id=?", (int(d.get("id", 0) or 0),))
        if not o:
            bad("الطلب غير موجود", 404)
        a, st = d.get("action"), o["status"]
        if role == "restaurant" and o["owner_id"] == u["id"]:
            if a == "accept" and st == "new":
                pm = int(d.get("prep_min", 0) or 0)
                if not 5 <= pm <= 180:
                    bad("اختار وقت التحضير")
                db.q("update orders set status='accepted', prep_min=?, accepted_at=? where id=? and status='new'", (pm, now(), o["id"]))
                if db.last_count != 1:
                    bad("إجراء غير مناسب")
                ev(o, "accepted", u, prep=pm)
            elif a == "reject" and st == "new":
                reason = str(d.get("reason", "")).strip()[:100]
                if not reason:
                    bad("اختار سبب الرفض")
                db.q("update orders set status='rejected', reject_reason=? where id=? and status='new'", (reason, o["id"]))
                if db.last_count != 1:
                    bad("إجراء غير مناسب")
                release_discount(o)
                release_items(o)
                ev(o, "rejected", u, note=reason)
            elif a == "ready" and st == "accepted":
                db.q("update orders set status='ready', ready_at=? where id=? and status='accepted'", (now(), o["id"]))
                if db.last_count != 1:
                    bad("إجراء غير مناسب")
                ev(o, "ready", u)
            elif a == "ready" and st == "picked" and not o.get("ready_at"):
                db.q("update orders set ready_at=? where id=? and status='picked' and (ready_at is null or ready_at=0)", (now(), o["id"]))
                if db.last_count != 1:
                    bad("إجراء غير مناسب")
                ev(o, "ready", u)
            elif a == "cancel" and st in ("accepted", "ready", "picked") and not o.get("collected_at"):
                reason = str(d.get("reason", "")).strip()[:100]
                if not reason:
                    bad("اختار سبب الإلغاء")
                db.q("update orders set status='cancelled', reject_reason=? where id=? and status in ('accepted','ready','picked') and (collected_at is null or collected_at=0)", (reason, o["id"]))
                if db.last_count != 1:
                    bad("إجراء غير مناسب")
                release_discount(o)
                release_items(o)
                ev(o, "cancelled", u, note=reason)
            else:
                bad("إجراء غير مناسب")
        elif role == "courier":
            if a == "decline" and st in ("accepted", "ready") and o["courier_id"] is None:
                c = cur_offer(o)
                if c and c["courier_id"] == u["id"]:
                    db.q("update order_offers set state='declined' where id=?", (c["id"],))
                return {"ok": True}
            if a == "take" and st in ("accepted", "ready") and o["courier_id"] is None:
                if was_withdrawn(o["id"], u["id"]):
                    sus(o, u, "take", "حاول ياخد أوردر اتسحب منه")
                    bad("تم سحب هذا الطلب منك ولا يمكن استلامه مرة أخرى", 403)
                if priority_block(o, u["id"]):
                    sus(o, u, "take", "حاول ياخد أوردر مش معروض عليه (3 مرات أو أكتر)", 3)
                    bad("الأوردر مش معروض عليك دلوقتي", 409)
                if active_count(u["id"]) >= MAXACT:
                    sus(o, u, "take", "تعدى الحد الأقصى للأوردرات الشغالة", 2)
                    bad("معاك %d أوردرات شغالة، خلّص واحد الأول" % MAXACT, 409)
                db.q("update orders set status='picked', courier_id=?, picked_at=? where id=? and status in ('accepted','ready') and courier_id is null", (u["id"], now(), o["id"]))
                if db.last_count != 1:
                    bad("الأوردر اتاخد")
                ev(o, "picked", u)
            elif a == "collect" and st == "picked" and o["courier_id"] == u["id"] and o.get("ready_at") and not o.get("collected_at"):
                db.q("update orders set collected_at=? where id=? and status='picked' and (collected_at is null or collected_at=0)", (now(), o["id"]))
                if db.last_count != 1:
                    bad("إجراء غير مناسب")
                ev(o, "collected", u)
            elif a == "deliver" and st == "picked" and o["courier_id"] == u["id"] and o.get("collected_at"):
                _at = now()
                try:
                    _a = int(d.get("at") or 0)
                    if o.get("collected_at") and o["collected_at"] <= _a <= _at:
                        _at = _a
                except Exception:
                    pass
                db.q("update orders set status='delivered', delivered_at=? where id=? and status='picked'", (_at, o["id"]))
                if db.last_count != 1:
                    bad("إجراء غير مناسب")
                ev(o, "delivered", u)
            elif a == "fail" and st == "picked" and o["courier_id"] == u["id"] and o.get("collected_at"):
                reason = str(d.get("reason", "")).strip()[:100]
                if not reason:
                    bad("اختار سبب تعذر التسليم")
                db.q("update orders set status='failed', fail_reason=? where id=? and status='picked'", (reason, o["id"]))
                if db.last_count != 1:
                    bad("إجراء غير مناسب")
                ev(o, "failed", u, note=reason)
            else:
                if a in ("collect", "deliver", "fail", "take"):
                    sus(o, u, a, "إجراء %s في حالة غلط أو على أوردر مش بتاعه (الحالة: %s)" % (a, st))
                bad("إجراء غير مناسب")
        elif role == "customer" and o["customer_id"] == u["id"] and a == "cancel":
            if st not in ("new", "pay"):
                bad("المطعم قبل الطلب، لا يمكن إلغاؤه الآن. برجاء التواصل معنا إذا كانت هناك مشكلة")
            db.q("update orders set status='cancelled' where id=? and status in ('new','pay')", (o["id"],))
            if db.last_count != 1:
                bad("إجراء غير مناسب")
            release_discount(o)
            release_items(o)
            ev(o, "cancelled", u, note="بطلب العميل قبل قبول المطعم")
        elif role == "admin" and a == "release" and st == "picked" and o["courier_id"] and not o.get("collected_at"):
            wreason = str(d.get("reason", "")).strip()[:100]
            if not wreason:
                bad("اختار سبب السحب")
            db.q("update orders set status=?, courier_id=null, picked_at=0 where id=? and status='picked' and (collected_at is null or collected_at=0)", ("ready" if o.get("ready_at") else "accepted", o["id"]))
            if db.last_count != 1:
                bad("إجراء غير مناسب")
            ev(o, "released", u, note=wreason)
        elif role == "admin" and a == "confirm_pay" and st == "pay":
            db.q("update orders set status='new' where id=? and status='pay'", (o["id"],))
            if db.last_count != 1:
                bad("إجراء غير مناسب")
            ev(o, "paid", u, note="")
        elif role == "admin" and a == "cancel" and st in OPEN_STATES:
            reason = str(d.get("reason", "")).strip()[:100]
            if not reason:
                bad("اختار سبب الإلغاء")
            db.q("update orders set status='cancelled', reject_reason=? where id=? and status in ('pay','new','accepted','ready','picked')", (reason, o["id"]))
            if db.last_count != 1:
                bad("إجراء غير مناسب")
            release_discount(o)
            release_items(o)
            ev(o, "cancelled", u, note=reason)
        else:
            bad("غير مسموح", 403)
        return {"ok": True}

    # ---------- courier
    if p == "/api/courier/ping" and role == "courier" and m == "POST":
        t = now()
        lat, lng = fnum(d.get("lat"), -90, 90, 6), fnum(d.get("lng"), -180, 180, 6)
        acc = fnum(d.get("acc"), 0, 100000, 1)
        if lat is not None and lng is not None and not (21 <= lat <= 32 and 24 <= lng <= 37):
            lat = lng = None
        if lat is not None and lng is not None:
            _pl = db.one("select lat,lng,ts from courier_loc where uid=?", (u["id"],))
            if _pl and _pl["lat"] is not None and t - _pl["ts"] < 600:
                _dt = max(t - _pl["ts"], 1)
                if hav(_pl["lat"], _pl["lng"], lat, lng) / _dt * 3600 > 250:  # more than 250 km/h: fake or glitch
                    lat = lng = None
        if lat is not None and lng is not None:
            db.q("update courier_loc set lat=?, lng=?, acc=?, ts=?, seen=? where uid=?", (lat, lng, acc, t, t, u["id"]))
            if db.last_count != 1:
                db.q("insert into courier_loc(uid,lat,lng,acc,ts,seen) values(?,?,?,?,?,?)", (u["id"], lat, lng, acc, t, t))
        else:
            db.q("update courier_loc set seen=? where uid=?", (t, u["id"]))
            if db.last_count != 1:
                db.q("insert into courier_loc(uid,seen) values(?,?)", (u["id"], t))
        notes = db.q("select id, order_id from courier_issues where courier_id=? and kind='released_offline' and notified=0", (u["id"],))
        for n in notes:
            db.q("update courier_issues set notified=1 where id=?", (n["id"],))
        return {"ok": True, "withdrawn": [n["order_id"] for n in notes]}
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
            return {"has_loc": r.get("lat") is not None and r.get("lng") is not None, "id": r["id"], "name": r["name"], "is_open": r["is_open"], "open_now": open_now(r), "fee": r["fee"], "hours_from": r["hours_from"], "hours_to": r["hours_to"], "promo": r.get("promo") or ""}
        if p == "/api/my/location" and m == "POST":
            lat, lng = fnum(d.get("lat"), -90, 90, 6), fnum(d.get("lng"), -180, 180, 6)
            if lat is None or lng is None:
                bad("الموقع غير صحيح")
            if not (21 <= lat <= 32 and 24 <= lng <= 37):
                bad("الموقع ده برة مصر، اتأكد من الموقع")
            db.q("update restaurants set lat=?, lng=? where id=?", (lat, lng, r["id"]))
            return {"ok": True}
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
        if p == "/api/my/promo" and m == "POST":
            db.q("update restaurants set promo=? where id=?", (clean_promo(d.get("text", "")), r["id"]))
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
            cat = d.get("cat") if d.get("cat") in CATS else "rest"
            db.q("insert into restaurants(owner_id,name,fee,cat) values(?,?,?,?)", (uid, nm, fee, cat))
            return {"code": code}
        if p == "/api/admin/rest_photo" and m == "POST":
            rid = int(d.get("id", 0) or 0)
            if not db.one("select 1 as x from restaurants where id=?", (rid,)):
                bad("المطعم غير موجود", 404)
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
            old = db.one("select pv from rest_photos where rest_id=?", (rid,))
            nv = (old["pv"] if old else 0) + 1
            db.q("delete from rest_photos where rest_id=?", (rid,))
            db.q("insert into rest_photos(rest_id,data,pv) values(?,?,?)", (rid, data[len(pre):], nv))
            return {"ok": True}
        if p == "/api/admin/rest_photo_delete" and m == "POST":
            db.q("delete from rest_photos where rest_id=?", (int(d.get("id", 0) or 0),))
            return {"ok": True}
        if p == "/api/admin/add_courier" and m == "POST":
            nm = str(d.get("name", "")).strip()[:60]
            if not nm:
                bad("اكتب الاسم")
            code = new_code()
            mk("courier", code, nm)
            return {"code": code}
        if p == "/api/admin/users" and m == "GET":
            return db.q("select u.id,u.phone as code,u.name,u.role,u.active,r.id as rid,r.fee,r.featured,r.promo,r.cat,r.lat,r.lng,r.show_fee,(select count(*) from rest_photos p where p.rest_id=r.id) as hasp,(select seen from courier_loc cl where cl.uid=u.id) as seen from users u left join restaurants r on r.owner_id=u.id where u.role in ('restaurant','courier') order by u.id desc")
        if p == "/api/admin/courier_issues" and m == "GET":
            out = []
            for i in db.q("select * from courier_issues order by id desc limit 100"):
                try:
                    dd = json.loads(i["data"] or "{}")
                except Exception:
                    dd = {}
                cur = db.one("select status, courier_id from orders where id=?", (i["order_id"],))
                lc = db.one("select lat,lng,ts,seen from courier_loc where uid=?", (i["courier_id"],))
                out.append({"id": i["id"], "kind": i["kind"], "order_id": i["order_id"], "created": i["created"], "offline_since": i["offline_since"], "resolved_at": i["resolved_at"], "resolution": i["resolution"],
                            "courier": dd.get("courier", {}), "order": dd.get("order", {}), "extra": dd.get("extra", {}), "order_status_now": cur["status"] if cur else "", "courier_seen_now": lc["seen"] if lc else 0})
            return out
        if p == "/api/admin/user_toggle" and m == "POST":
            db.q("update users set active=1-active, token=? where id=? and role in ('restaurant','courier')", (secrets.token_hex(16), int(d.get("id", 0) or 0)))
            return {"ok": True}
        if p == "/api/admin/restaurant_set" and m == "POST":
            fee = fnum(d.get("fee"), 0, 1000)
            if fee is None:
                bad("رسوم غير صحيحة")
            db.q("update restaurants set fee=?, featured=? where id=?", (fee, 1 if d.get("featured") else 0, int(d.get("id", 0) or 0)))
            if d.get("cat") in CATS:
                db.q("update restaurants set cat=? where id=?", (d["cat"], int(d.get("id", 0) or 0)))
            if "show_fee" in d:
                db.q("update restaurants set show_fee=? where id=?", (1 if d.get("show_fee") else 0, int(d.get("id", 0) or 0)))
            if "loc" in d:
                _l = str(d.get("loc") or "").strip()
                if _l == "":
                    db.q("update restaurants set lat=null, lng=null where id=?", (int(d.get("id", 0) or 0),))
                else:
                    _m = re.search(r"(-?\d{1,3}\.\d+)\s*[, ]\s*(-?\d{1,3}\.\d+)", _l)
                    _la, _ln = (fnum(_m.group(1), -90, 90, 6), fnum(_m.group(2), -180, 180, 6)) if _m else (None, None)
                    if _la is None or _ln is None or not (21 <= _la <= 32 and 24 <= _ln <= 37):
                        bad("اكتب الموقع كده: 30.123456, 31.123456 (خط العرض أولا، ولازم يكون جوه مصر)")
                    db.q("update restaurants set lat=?, lng=? where id=?", (_la, _ln, int(d.get("id", 0) or 0)))
            return {"ok": True}
        if p == "/api/admin/settings" and m == "POST":
            for k, mx in (("banner", 200), ("welcome", 300), ("contact_phone", 20), ("pay_on", 1), ("pay_vf", 20), ("pay_ip", 60), ("pay_link", 200), ("pay_name", 60)):
                if k in d:
                    db.q("update settings set v=? where k=?", (str(d[k]).strip()[:mx], k))
            return {"ok": True}
        if p == "/api/admin/pay_img" and m == "GET":
            r = db.one("select pay_img from orders where id=?", (int((qs.get("id") or ["0"])[0] or 0),))
            return {"img": (r["pay_img"] if r else "") or ""}
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
    for t in ("users", "restaurants", "items", "orders", "discounts", "settings", "photos", "rest_photos"):
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
        try:
            self.wfile.write(b)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def empty(self, code):
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def events(self, qs):
        usr = ev_user(self.headers.get("X-Token", ""))
        if not usr:
            return self.send_json(401, {"error": "سجّل دخول"})
        try:
            since = int((qs.get("since") or ["-1"])[0])
            wait = max(0, min(25, int((qs.get("wait") or ["0"])[0])))
        except Exception:
            return self.send_json(400, {"error": "طلب غير صحيح"})
        if not EVINIT[0]:
            with lock:
                try:
                    EVSEQ[0] = max(EVSEQ[0], db.one("select coalesce(max(id),0) as n from order_events")["n"])
                    EVINIT[0] = True
                except Exception:
                    db.rollback()
                    db.reset()
        if since < 0:
            return self.send_json(200, {"events": [], "last": EVSEQ[0]})
        end = time.time() + wait
        out = []
        while True:
            with EVC:
                new = [e for e in EVRING if e["id"] > since]
                if not new and wait > 0 and end - time.time() > 0:
                    EVC.wait(end - time.time())
                    new = [e for e in EVRING if e["id"] > since]
            if new:
                since = new[-1]["id"]
                for e in new:
                    r = ev_for(usr["role"], usr, e)
                    if r:
                        out.append(r)
            if out or time.time() >= end:
                break
        return self.send_json(200, {"events": out, "last": since})

    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        if p == "/api/ver":
            return self.send_json(200, {"v": VER[0]})
        if p == "/api/events":
            return self.events(parse_qs(u.query))
        if p.startswith("/api/"):
            return self.api("GET", p, parse_qs(u.query))
        mr = re.match(r"^/rpic/(\d+)$", p)
        if mr:
            r = None
            with lock:
                try:
                    r = db.one("select data from rest_photos where rest_id=?", (int(mr.group(1)),))
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
        if not f.startswith(HERE) or not f.endswith((".html", ".js", ".png", ".mp3")) or not os.path.isfile(f):
            return self.empty(404)
        b = open(f, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", (mimetypes.guess_type(f)[0] or "text/plain") + ("; charset=utf-8" if not f.endswith((".png", ".mp3")) else ""))
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
                        self.send_header("Content-Disposition", 'attachment; filename="3mak-backup-%s.json"' % cairo_now().strftime("%Y%m%d"))
                        self.send_header("Content-Length", str(len(b)))
                        self.end_headers()
                        self.wfile.write(b)
                        return
                    db.commit()
                    if m == "POST" and p not in ("/api/login", "/api/guest", "/api/discount_check", "/api/courier/ping"):
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
    threading.Thread(target=guard_loop, daemon=True).start()
    class _S(ThreadingHTTPServer):
        request_queue_size = 512  # default 5 drops bursts of connections (1s retry delay)
        daemon_threads = True
    _S(("0.0.0.0", port), H).serve_forever()
