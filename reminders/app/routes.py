"""HTTP endpoints: subscribe, confirm, unsubscribe, and subscriber export."""

from __future__ import annotations

import hmac
import hashlib
import ipaddress
import json
import logging
from datetime import date
from html import escape as html_escape

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from app import db, tft_guide
from app.availability import open_tables_exist
from app.config import Settings, load_settings
from app.emailer import EmailDeliveryError, confirm_email_html, send_email
from app.observability import log_event
from app.schemas import SubscribeRequest
from app.tft_live_refresh import MEALS

router = APIRouter()
logger = logging.getLogger("amex_reminders.lifecycle")

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


SITE_URL = "https://amex-explorer.kooexperience.com/#/table-for-two"
# Same faces as the explorer site, self-hosted so no visitor IP reaches Google.
FONT_LINKS = (
    "<style>@font-face{font-family:'Cormorant Garamond';font-style:normal;font-weight:300 700;"
    "font-display:swap;src:url(/fonts/cormorant-garamond-latin-normal.woff2) format('woff2')}"
    "@font-face{font-family:'Figtree';font-style:normal;font-weight:300 900;"
    "font-display:swap;src:url(/fonts/figtree-latin-normal.woff2) format('woff2')}</style>"
)
PAGE_CSS = """
:root{--surface:rgba(11,22,36,.92);--field:rgba(5,10,17,.62);--border:rgba(183,155,105,.18);
 --border-strong:rgba(201,165,90,.42);--gold:#c9a55a;--teal:#4db8a6;--text:#f0ebe2;--muted:#8a9aaa;
 --danger:#ff8a80;--serif:"Cormorant Garamond",Georgia,serif;--sans:"Figtree",system-ui,sans-serif;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;padding:1.5rem;
 font:400 1rem/1.55 var(--sans);color:var(--text);-webkit-font-smoothing:antialiased;
 background:radial-gradient(70rem 36rem at 12% -12%,rgba(201,165,90,.12),transparent 60%),
  radial-gradient(56rem 30rem at 108% 112%,rgba(77,184,166,.09),transparent 60%),
  linear-gradient(180deg,#0a1520,#070c14 55%,#050a11)}
.card{width:100%;max-width:27rem;padding:2.25rem 1.75rem 1.75rem;background:var(--surface);
 border:1px solid var(--border);border-radius:20px;box-shadow:0 1.5rem 4rem rgba(0,0,0,.45);
 animation:rise .45s cubic-bezier(.2,.8,.2,1) both}
.eyebrow{margin:0 0 .9rem;font:600 .7rem/1 var(--sans);letter-spacing:.18em;text-transform:uppercase;color:var(--gold)}
h1{margin:0 0 .6rem;font:600 2.1rem/1.05 var(--serif);letter-spacing:-.015em}
.lead{margin:0 0 1.6rem;color:var(--muted)}
.mark{display:grid;place-items:center;width:2.75rem;height:2.75rem;margin:0 0 1.1rem;border-radius:50%;
 border:1px solid var(--border-strong);color:var(--gold);font:600 1.1rem/1 var(--sans)}
.mark.warn{border-color:rgba(255,138,128,.45);color:var(--danger)}
.btn{display:flex;justify-content:center;width:100%;padding:.9rem 1.2rem;border:0;border-radius:12px;
 background:var(--gold);color:#17110a;font:600 1rem/1 var(--sans);cursor:pointer;
 transition:transform .1s ease-out,filter .15s ease}
.btn:hover{filter:brightness(1.07)}
.btn:active{transform:scale(.97)}
.back{display:inline-block;margin-top:1.4rem;color:var(--muted);font-size:.9rem;text-decoration:none;
 border-bottom:1px solid var(--border);padding-bottom:1px}
.back:hover{color:var(--text);border-color:var(--border-strong)}
:focus-visible{outline:2px solid var(--teal);outline-offset:3px;border-radius:6px}
@keyframes rise{from{opacity:0;transform:translateY(8px)}}
@media (prefers-reduced-motion:reduce){.card{animation:none}.btn{transition:none}.btn:active{transform:none}}
@media (prefers-contrast:more){.card{background:#0b1624;border-color:var(--gold)}.lead{color:var(--text)}}
"""


def _document(title: str, inner: str, extra_css: str = "") -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html_escape(title)} · Table for Two</title>{FONT_LINKS}"
        f"<style>{PAGE_CSS}{extra_css}</style></head><body>{inner}</body></html>"
    )


def _page(title: str, message: str, mark: str = "✓", tone: str = "") -> str:
    return _document(
        title,
        f'<main class="card"><div class="mark {tone}" aria-hidden="true">{mark}</div>'
        '<p class="eyebrow">Table for Two reminders</p>'
        f'<h1>{html_escape(title)}</h1><p class="lead">{html_escape(message)}</p>'
        f'<a class="back" href="{SITE_URL}">Back to Table for Two</a></main>',
    )


@router.post("/api/subscribe")
def subscribe(
    payload: SubscribeRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict:
    success = {"ok": True, "message": "Check your email to confirm your reminder."}
    if payload.website.strip():  # honeypot — pretend success, do nothing
        log_event(logger, "subscribe_honeypot")
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
            log_event(logger, "subscribe_rate_limited")
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
    recipient_id = abuse_key("email", sub_input.email, settings).split(":", 1)[1][:12]
    try:
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
    except Exception as exc:
        error_code = (
            exc.code if isinstance(exc, EmailDeliveryError) else "unexpected_failure"
        )
        logger.error(
            json.dumps(
                {
                    "event": "confirmation_email_failed",
                    "recipient_id": recipient_id,
                    "error_code": error_code,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        raise HTTPException(
            status_code=502,
            detail="Confirmation email could not be sent. Please try again later.",
        ) from None
    log_event(logger, "subscription_pending", recipient_id=recipient_id)
    return success


def _confirmation_form(title: str, message: str, action: str, label: str) -> str:
    return _document(
        title,
        '<main class="card"><p class="eyebrow">Table for Two reminders</p>'
        f'<h1>{html_escape(title)}</h1><p class="lead">{html_escape(message)}</p>'
        f'<form method="post" action="{html_escape(action, quote=True)}">'
        f'<button class="btn" type="submit">{html_escape(label)}</button></form>'
        f'<a class="back" href="{SITE_URL}">Back to Table for Two</a></main>',
    )


@router.get("/api/confirm", response_class=HTMLResponse)
def confirm_page(token: str = "", settings: Settings = Depends(get_settings)) -> HTMLResponse:
    return HTMLResponse(
        _confirmation_form(
            "One last step",
            "Confirm your email and we'll start watching for tables that match your request.",
            f"{settings.public_base_url}/api/confirm?token={html_escape(token, quote=True)}",
            "Start my reminders",
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
        log_event(logger, "subscription_confirmed")
        return HTMLResponse(
            _page(
                "You're all set",
                "We'll email you as soon as a matching table opens up. Book it in the Amex Experiences App.",
            )
        )
    return HTMLResponse(
        _page(
            "This link has expired",
            "Confirmation links last a few days. Sign up again from the Table for Two page.",
            "!",
            "warn",
        ),
        status_code=400,
    )


@router.get("/api/unsubscribe", response_class=HTMLResponse)
def unsubscribe_page(
    token: str = "", settings: Settings = Depends(get_settings)
) -> HTMLResponse:
    return HTMLResponse(
        _confirmation_form(
            "Stop all reminders?",
            "You'll stop getting Table for Two emails. You can sign up again any time.",
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
        log_event(logger, "subscription_unsubscribed")
        return HTMLResponse(
            _page("You're unsubscribed", "You won't get any more Table for Two reminders.", "–")
        )
    return HTMLResponse(
        _page("Invalid link", "This unsubscribe link is not valid.", "!", "warn"), status_code=400
    )


def _venue_names() -> list[str]:
    return tft_guide.venue_names()


MANAGE_CSS = """
body{align-items:start}
.card{max-width:30rem;margin-block:1rem}
.sub{margin:-.2rem 0 1.4rem;color:var(--muted);font-size:.9rem;word-break:break-all}
.note{background:rgba(77,184,166,.1);border:1px solid rgba(77,184,166,.35);border-radius:12px;
 padding:.7rem .85rem;font-size:.9rem;margin:0 0 1.2rem}
form{display:flex;flex-direction:column;gap:1.05rem}
label{display:flex;flex-direction:column;gap:.4rem;font-size:.8rem;font-weight:600;color:var(--muted);letter-spacing:.01em}
input,select{padding:.7rem .8rem;font:400 1rem/1.2 var(--sans);color:var(--text);background:var(--field);
 border:1px solid var(--border);border-radius:12px;transition:border-color .15s ease}
input:hover{border-color:var(--border-strong)}
input:focus-visible{outline:none;border-color:var(--teal);box-shadow:0 0 0 3px rgba(77,184,166,.25)}
fieldset{border:0;padding:0;margin:0;display:flex;flex-direction:column;gap:.5rem}
legend{font-size:.8rem;font-weight:600;color:var(--muted);padding:0;margin-bottom:.4rem}
.checks{display:flex;flex-wrap:wrap;gap:.5rem}
.checks label,.vany,.venuelist label{flex-direction:row;align-items:center;gap:.55rem;font-size:.95rem;color:var(--text);font-weight:500}
.checks label{padding:.5rem .8rem;border:1px solid var(--border);border-radius:999px;background:var(--field);cursor:pointer}
.checks label:has(input:checked){border-color:var(--border-strong);background:rgba(201,165,90,.1)}
input[type=checkbox]{width:1.05rem;height:1.05rem;padding:0;accent-color:var(--gold);flex:none}
.venuelist{display:grid;gap:.45rem;max-height:11rem;overflow-y:auto;padding:.7rem .8rem;
 border:1px solid var(--border);border-radius:12px;background:var(--field)}
.dateadder{display:flex;gap:.5rem}
.dateadder input{flex:1;min-width:0}
.dateadder button{flex:none;padding:0 1rem;font:600 .9rem/1 var(--sans);color:var(--gold);background:transparent;
 border:1px solid var(--border-strong);border-radius:12px;cursor:pointer}
.dateadder button:active{transform:scale(.97)}
.datechips{display:flex;flex-wrap:wrap;gap:.4rem;margin-top:.2rem}
.datechips:empty{display:none}
.datechip{display:inline-flex;align-items:center;gap:.2rem;padding:.25rem .25rem .25rem .65rem;font-size:.82rem;
 color:var(--text);background:var(--field);border:1px solid var(--border);border-radius:999px}
.datechip button{border:none;background:none;color:var(--muted);font-size:1rem;line-height:1;cursor:pointer;padding:.1rem .35rem}
.hint{margin:.1rem 0 0;font-size:.78rem;color:var(--muted)}
form > button[type=submit]{display:flex;justify-content:center;padding:.9rem 1.2rem;border:0;border-radius:12px;
 background:var(--gold);color:#17110a;font:600 1rem/1 var(--sans);cursor:pointer;transition:transform .1s ease-out}
form > button[type=submit]:active{transform:scale(.97)}
.status{font-size:.9rem;color:var(--teal);margin:0;min-height:1.4em}
.status.err{color:var(--danger)}
.unsub{display:inline-block;margin-top:1.4rem;color:var(--muted);font-size:.85rem}
@media (prefers-reduced-motion:reduce){form > button[type=submit]:active,.dateadder button:active{transform:none}}
"""

_MANAGE_TEMPLATE = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    "<title>Manage your reminders · Table for Two</title>" + FONT_LINKS
    + "<style>" + PAGE_CSS + MANAGE_CSS + "</style></head><body>"
    + """<main class="card"><p class="eyebrow">Table for Two reminders</p>
<h1>Your reminders</h1>
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
   __SESSION_CHECKBOXES__
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
 var c=document.createElement('span'); c.className='datechip'; c.dataset.value=v; var d=new Date(v+'T00:00'); c.textContent=d.toLocaleDateString('en-SG',d.getFullYear()===new Date().getFullYear()?{weekday:'short',day:'numeric',month:'short'}:{weekday:'short',day:'numeric',month:'short',year:'numeric'})+' ';
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
</main></body></html>"""
)


def _chip_label(value: str) -> str:
    day = date.fromisoformat(value)
    year = "" if day.year == date.today().year else f" {day.year}"
    return f"{day:%a}, {day.day} {day:%b}{year}"


def _manage_page(record: dict, token: str, base: str, venue_names: list[str]) -> str:
    selected = set(record["venues"])
    any_selected = "any" in selected or not selected
    checkboxes = []
    # Chosen venues first, so the current choice is visible without scrolling.
    for name in sorted(venue_names, key=lambda venue: venue not in selected):
        checked = " checked" if name in selected else ""
        checkboxes.append(
            f'<label><input type="checkbox" class="m_venue_cb" '
            f'value="{html_escape(name)}"{checked}> {html_escape(name)}</label>'
        )
    date_chips = "".join(
        f'<span class="datechip" data-value="{html_escape(value)}">{_chip_label(value)} '
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
        "__SESSION_CHECKBOXES__": "".join(
            f'<label><input type="checkbox" name="session" value="{meal}"'
            f'{" checked" if meal in record["sessions"] else ""}> {meal}</label>'
            for meal in MEALS
        ),
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
            _page("Invalid link", "This management link is not valid.", "!", "warn"), status_code=400
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
    log_event(logger, "subscription_preferences_updated")
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
