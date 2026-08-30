"""HTTP endpoints: subscribe, confirm, unsubscribe, and subscriber export."""

from __future__ import annotations

import hmac
import hashlib
import ipaddress
import json
from datetime import date
from html import escape as html_escape

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from app import db
from app.availability import open_tables_exist
from app.config import Settings, load_settings
from app.emailer import confirm_email_html, send_email
from app.schemas import VENUES_PATH, SubscribeRequest

router = APIRouter()

RATE_LIMIT_MAX = 5
RATE_LIMIT_WINDOW_MIN = 60


def get_settings() -> Settings:
    return load_settings()


def client_ip(request: Request, settings: Settings) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    hops = max(0, settings.trusted_proxy_hops)
    if forwarded and hops:
        chain = [part.strip() for part in forwarded.split(",") if part.strip()]
        if len(chain) >= hops:
            candidate = chain[-hops]
            try:
                return str(ipaddress.ip_address(candidate))
            except ValueError:
                pass
    peer = request.client.host if request.client else "unknown"
    try:
        return str(ipaddress.ip_address(peer))
    except ValueError:
        return "unknown"


def abuse_key(kind: str, value: str, settings: Settings) -> str:
    secret = settings.abuse_hash_salt or settings.alert_export_token
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{kind}:{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{kind}:{digest}"


def _page(title: str, message: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title></head>
<body style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
             background:#070d16;color:#e8edf5;display:flex;min-height:100vh;
             align-items:center;justify-content:center;margin:0">
  <div style="max-width:420px;padding:32px;text-align:center">
    <h1 style="font-size:22px;margin:0 0 12px">{title}</h1>
    <p style="font-size:15px;line-height:1.5;color:#aab4c4;margin:0 0 20px">{message}</p>
    <a href="https://amex-explorer.kooexperience.com/#/table-for-two"
       style="color:#7aa2ff">Back to Table for Two</a>
  </div></body></html>"""


@router.post("/api/subscribe")
def subscribe(
    payload: SubscribeRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict:
    success = {"ok": True, "message": "Check your email to confirm your reminder."}
    if payload.website.strip():  # honeypot — pretend success, do nothing
        return success

    sub_input = payload.to_input()
    ip = client_ip(request, settings)
    conn = db.connect(settings.db_path)
    try:
        allowed = db.consume_rate_limits(
            conn,
            [
                (abuse_key("ip", ip, settings), "subscribe", settings.subscribe_ip_limit),
                (
                    abuse_key("email", sub_input.email, settings),
                    "subscribe",
                    settings.subscribe_email_limit,
                ),
                (abuse_key("global", "all", settings), "subscribe", settings.subscribe_global_limit),
            ],
            RATE_LIMIT_WINDOW_MIN,
        )
        if not allowed:
            raise HTTPException(
                status_code=429, detail="Too many attempts; please try again later."
            )
        confirm_token = db.upsert_pending(
            conn,
            sub_input,
            abuse_key("ip", ip, settings),
            settings.confirm_token_expiry_hours,
        )
        unsub_token = conn.execute(
            "SELECT unsubscribe_token, manage_token FROM subscribers WHERE email = ?",
            (sub_input.email,),
        ).fetchone()
    finally:
        conn.close()

    confirm_url = f"{settings.public_base_url}/api/confirm?token={confirm_token}"
    unsub_url = (
        f"{settings.public_base_url}/api/unsubscribe?token={unsub_token['unsubscribe_token']}"
    )
    manage_url = f"{settings.public_base_url}/api/manage?token={unsub_token['manage_token']}"
    matches_exist = open_tables_exist(
        sub_input.venues, sub_input.sessions, settings.table_data_url
    )
    send_email(
        sub_input.email,
        "Confirm your Table for Two reminders",
        confirm_email_html(
            sub_input.name, confirm_url, unsub_url, manage_url, matches_exist
        ),
        api_key=settings.resend_api_key,
        sender=settings.resend_from,
        list_unsubscribe_url=unsub_url,
    )
    return success


def _confirmation_form(title: str, message: str, action: str, label: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title></head>
<body style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
background:#070d16;color:#e8edf5;display:flex;min-height:100vh;align-items:center;
justify-content:center;margin:0"><main style="max-width:420px;padding:32px;text-align:center">
<h1 style="font-size:22px;margin:0 0 12px">{title}</h1>
<p style="font-size:15px;line-height:1.5;color:#aab4c4;margin:0 0 20px">{message}</p>
<form method="post" action="{html_escape(action, quote=True)}">
<button type="submit" style="padding:12px 20px;border:0;border-radius:8px;background:#4db8a6;
color:#07120f;font-weight:700;cursor:pointer">{label}</button></form>
</main></body></html>"""


@router.get("/api/confirm", response_class=HTMLResponse)
def confirm_page(token: str = "", settings: Settings = Depends(get_settings)) -> HTMLResponse:
    return HTMLResponse(
        _confirmation_form(
            "Confirm your reminders",
            "Confirm that you want to activate these Table for Two reminder settings.",
            f"{settings.public_base_url}/api/confirm?token={html_escape(token, quote=True)}",
            "Confirm reminders",
        )
    )


@router.post("/api/confirm", response_class=HTMLResponse)
def confirm(token: str = "", settings: Settings = Depends(get_settings)) -> HTMLResponse:
    conn = db.connect(settings.db_path)
    try:
        ok = db.confirm(conn, token)
    finally:
        conn.close()
    if ok:
        return HTMLResponse(
            _page(
                "You're subscribed",
                "We'll email you when a Table for Two slot matches your request.",
            )
        )
    return HTMLResponse(
        _page(
            "Link expired or invalid",
            "Please sign up again from the Table for Two page.",
        ),
        status_code=400,
    )


@router.get("/api/unsubscribe", response_class=HTMLResponse)
def unsubscribe_page(
    token: str = "", settings: Settings = Depends(get_settings)
) -> HTMLResponse:
    return HTMLResponse(
        _confirmation_form(
            "Unsubscribe from reminders",
            "Confirm that you want to stop all Table for Two reminder emails.",
            f"{settings.public_base_url}/api/unsubscribe?token={html_escape(token, quote=True)}",
            "Unsubscribe",
        )
    )


@router.post("/api/unsubscribe", response_class=HTMLResponse)
def unsubscribe(
    token: str = "", settings: Settings = Depends(get_settings)
) -> HTMLResponse:
    conn = db.connect(settings.db_path)
    try:
        ok = db.unsubscribe(conn, token)
    finally:
        conn.close()
    if ok:
        return HTMLResponse(
            _page("Unsubscribed", "You won't receive any more Table for Two reminders.")
        )
    return HTMLResponse(
        _page("Invalid link", "This unsubscribe link is not valid."), status_code=400
    )


def _venue_names() -> list[str]:
    try:
        return sorted(json.loads(VENUES_PATH.read_text()))
    except (OSError, ValueError):
        return []


_MANAGE_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Manage your Table for Two reminders</title>
<style>
 body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#070d16;
   color:#e8edf5;margin:0;padding:24px;display:flex;justify-content:center}
 .card{width:100%;max-width:420px}
 h1{font-size:20px;margin:0 0 4px}
 .sub{color:#8a94a6;font-size:13px;margin:0 0 18px}
 .note{background:rgba(77,184,166,.1);border:1px solid rgba(77,184,166,.35);border-radius:10px;
   padding:10px 12px;font-size:13px;margin:0 0 16px}
 form{display:flex;flex-direction:column;gap:12px}
 label{display:flex;flex-direction:column;gap:5px;font-size:12px;font-weight:600;color:#8a94a6}
 input,select{padding:9px 10px;font-size:14px;color:#e8edf5;background:#070d16;
   border:1px solid rgba(255,255,255,.12);border-radius:10px;font-family:inherit}
 fieldset{border:0;padding:0;margin:0;display:flex;flex-direction:column;gap:6px}
 legend{font-size:12px;font-weight:600;color:#8a94a6;padding:0}
 .checks{display:flex;gap:18px}
 .checks label{flex-direction:row;align-items:center;font-size:14px;color:#e8edf5;font-weight:500}
 .checks input{accent-color:#4db8a6}
 button{padding:11px 14px;font-size:14px;font-weight:700;color:#4db8a6;background:rgba(77,184,166,.1);
   border:1px solid rgba(77,184,166,.35);border-radius:10px;cursor:pointer;font-family:inherit}
 .status{font-size:13px;color:#4db8a6;margin:0}
 .status.err{color:#ff8585}
 .unsub{display:inline-block;margin-top:18px;color:#8a94a6;font-size:13px}
 .vany{flex-direction:row;align-items:center;gap:6px;font-size:14px;color:#e8edf5;font-weight:500}
 .vany input{width:auto;accent-color:#4db8a6}
 .venuelist{display:grid;gap:6px;max-height:140px;overflow-y:auto;padding:8px 10px;margin-top:6px;
   border:1px solid rgba(255,255,255,.12);border-radius:10px;background:#070d16}
 .venuelist label{flex-direction:row;align-items:center;gap:8px;font-size:13px;color:#e8edf5;font-weight:500}
 .venuelist input{width:auto;accent-color:#4db8a6}
 .dateadder{display:flex;gap:8px}
 .dateadder input{flex:1;min-width:0}
 .dateadder button{flex:none;padding:0 14px;font-size:13px}
 .datechips{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
 .datechips:empty{display:none}
 .datechip{display:inline-flex;align-items:center;gap:4px;padding:4px 4px 4px 9px;font-size:12px;
   color:#e8edf5;background:rgba(15,27,43,.7);border:1px solid rgba(255,255,255,.12);border-radius:999px}
 .datechip button{border:none;background:none;color:#8a94a6;font-size:15px;line-height:1;cursor:pointer;padding:0 4px}
 .hint{margin:6px 0 0;font-size:11px;color:#8a94a6}
</style></head><body><div class="card">
<h1>Your Table for Two reminders</h1>
<p class="sub">__EMAIL__</p>
__STATUS_NOTE__
<form id="mform">
 <label>Name<input id="m_name" type="text" value="__NAME__" placeholder="Your name"></label>
 <label>Party size<input id="m_party" type="number" min="1" max="20" value="__PARTY__"></label>
 <fieldset><legend>Venues</legend>
   <label class="vany"><input type="checkbox" id="m_any" __ANY_CHECKED__> Any venue</label>
   <div class="venuelist" id="m_venue_list">__VENUE_CHECKBOXES__</div>
 </fieldset>
 <fieldset><legend>Session</legend><div class="checks">
   <label><input type="checkbox" name="session" value="Lunch" __LUNCH__> Lunch</label>
   <label><input type="checkbox" name="session" value="Dinner" __DINNER__> Dinner</label>
 </div></fieldset>
 <label>From<input id="m_start" type="date" value="__START__" min="__TODAY__"></label>
 <label>To<input id="m_end" type="date" value="__END__" min="__TODAY__"></label>
 <fieldset><legend>Specific dates (optional)</legend>
   <div class="dateadder"><input type="date" id="m_date_pick"><button type="button" id="m_date_add">Add</button></div>
   <div class="datechips" id="m_date_chips">__DATE_CHIPS__</div>
   <p class="hint">Leave empty for any date in the range above.</p>
 </fieldset>
 <button type="submit">Save changes</button>
 <p id="status" class="status"></p>
</form>
<a class="unsub" href="__BASE__/api/unsubscribe?token=__TOKEN__">Unsubscribe from all reminders</a>
<script>
var mList=document.getElementById('m_venue_list'), mAny=document.getElementById('m_any');
if(mList){mList.addEventListener('change',function(){if(mAny)mAny.checked=mList.querySelectorAll('.m_venue_cb:checked').length===0;});}
if(mAny){mAny.addEventListener('change',function(){if(mAny.checked){Array.prototype.slice.call(mList.querySelectorAll('.m_venue_cb:checked')).forEach(function(c){c.checked=false;});}});}
var dPick=document.getElementById('m_date_pick'), dAdd=document.getElementById('m_date_add'), dChips=document.getElementById('m_date_chips');
if(dAdd){dAdd.addEventListener('click',function(){
 var v=dPick.value; if(!v) return;
 var have=Array.prototype.slice.call(dChips.querySelectorAll('.datechip')).map(function(c){return c.dataset.value;});
 if(have.indexOf(v)>=0) return;
 var c=document.createElement('span'); c.className='datechip'; c.dataset.value=v; c.textContent=v+' ';
 var b=document.createElement('button'); b.type='button'; b.textContent='×'; b.addEventListener('click',function(){c.remove();});
 c.appendChild(b); dChips.appendChild(c); dPick.value='';
});}
document.getElementById('mform').addEventListener('submit', async function(e){
 e.preventDefault();
 var sessions = Array.prototype.slice.call(document.querySelectorAll('input[name=session]:checked')).map(function(x){return x.value;});
 var venues = Array.prototype.slice.call(document.querySelectorAll('.m_venue_cb:checked')).map(function(x){return x.value;});
 var dates = Array.prototype.slice.call(document.querySelectorAll('.datechip')).map(function(c){return c.dataset.value;});
 var body = {name:(document.getElementById('m_name').value||'').trim()||null,
   party_size:Number(document.getElementById('m_party').value||2),sessions:sessions,
   venues:venues.length?venues:['any'],dates:dates,
   date_start:document.getElementById('m_start').value,date_end:document.getElementById('m_end').value};
 var s=document.getElementById('status'); s.textContent='Saving…'; s.className='status';
 try{
  var r=await fetch(window.location.pathname+window.location.search,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  var d=await r.json().catch(function(){return {};});
  if(r.ok){s.textContent=d.message||'Saved.';}else{s.textContent=d.detail||'Could not save.';s.className='status err';}
 }catch(err){s.textContent='Network error — try again.';s.className='status err';}
});
</script>
</div></body></html>"""


def _manage_page(record: dict, token: str, base: str, venue_names: list[str]) -> str:
    selected = set(record["venues"])
    any_selected = "any" in selected or not selected
    checkboxes = []
    for name in venue_names:
        checked = " checked" if name in selected else ""
        checkboxes.append(
            f'<label><input type="checkbox" class="m_venue_cb" '
            f'value="{html_escape(name)}"{checked}> {html_escape(name)}</label>'
        )
    date_chips = "".join(
        f'<span class="datechip" data-value="{html_escape(value)}">{html_escape(value)} '
        f'<button type="button" onclick="this.parentNode.remove()">×</button></span>'
        for value in record.get("dates", [])
    )
    note = ""
    if record["status"] == "pending":
        note = (
            '<p class="note">Your email isn\'t confirmed yet — check your inbox for the '
            "confirmation link. You can still update your preferences here.</p>"
        )
    replacements = {
        "__EMAIL__": html_escape(record["email"]),
        "__NAME__": html_escape(record["name"] or ""),
        "__PARTY__": str(record["party_size"]),
        "__VENUE_CHECKBOXES__": "".join(checkboxes),
        "__ANY_CHECKED__": "checked" if any_selected else "",
        "__DATE_CHIPS__": date_chips,
        "__LUNCH__": "checked" if "Lunch" in record["sessions"] else "",
        "__DINNER__": "checked" if "Dinner" in record["sessions"] else "",
        "__START__": html_escape(record["date_start"]),
        "__END__": html_escape(record["date_end"]),
        "__TODAY__": date.today().isoformat(),
        "__STATUS_NOTE__": note,
        "__BASE__": base,
        "__TOKEN__": html_escape(token),
    }
    page = _MANAGE_TEMPLATE
    for key, value in replacements.items():
        page = page.replace(key, value)
    return page


@router.get("/api/manage", response_class=HTMLResponse)
def manage(token: str = "", settings: Settings = Depends(get_settings)) -> HTMLResponse:
    conn = db.connect(settings.db_path)
    try:
        record = db.get_by_manage_token(conn, token)
    finally:
        conn.close()
    if not record:
        return HTMLResponse(
            _page("Invalid link", "This management link is not valid."), status_code=400
        )
    if record["status"] == "unsubscribed":
        return HTMLResponse(
            _page(
                "Unsubscribed",
                "You've unsubscribed. Sign up again from the Table for Two page to restart.",
            )
        )
    return HTMLResponse(
        _manage_page(record, token, settings.public_base_url, _venue_names())
    )


@router.post("/api/manage")
async def manage_update(
    request: Request, token: str = "", settings: Settings = Depends(get_settings)
) -> dict:
    conn = db.connect(settings.db_path)
    try:
        record = db.get_by_manage_token(conn, token)
        if not record or record["status"] == "unsubscribed":
            raise HTTPException(status_code=400, detail="This link is no longer valid.")
        body = await request.json()
        body["email"] = record["email"]
        body["website"] = ""
        try:
            validated = SubscribeRequest(**body)
        except ValidationError as exc:
            message = exc.errors()[0].get("msg", "Invalid input")
            raise HTTPException(status_code=422, detail=message) from exc
        db.update_preferences(conn, token, validated.to_input())
    finally:
        conn.close()
    return {"ok": True, "message": "Your reminder preferences are updated."}


@router.get("/api/subscribers")
def subscribers(
    authorization: str = Header(default=""),
    settings: Settings = Depends(get_settings),
) -> dict:
    provided = authorization.removeprefix("Bearer ").strip()
    if not settings.alert_export_token or not hmac.compare_digest(
        provided, settings.alert_export_token
    ):
        raise HTTPException(status_code=401, detail="unauthorized")
    conn = db.connect(settings.db_path)
    try:
        rows = db.active_subscribers(conn)
    finally:
        conn.close()
    subscriptions = []
    for row in rows:
        token = row.pop("unsubscribe_token")
        row["unsubscribe_url"] = (
            f"{settings.public_base_url}/api/unsubscribe?token={token}"
        )
        subscriptions.append(row)
    return {"subscriptions": subscriptions}
