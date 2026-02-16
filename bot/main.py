import os
import re
from datetime import date, datetime
from fastapi import FastAPI, Request, HTTPException
from supabase import create_client

# ======================
# ENV VARS (Render)
# ======================
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

TELEGRAM_SECRET = os.environ["TELEGRAM_SECRET"]  # mismo valor que setWebhook secret_token
ALLOWED_CHAT_ID = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID")  # opcional

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
app = FastAPI()

@app.get("/")
def health():
    return {"ok": True, "service": "telegram-bot"}


# ======================
# Helpers
# ======================
def norm(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def parse_amount(s: str) -> float:
    s = s.replace("$", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    return abs(float(s))


def find_id_by_name(table: str, value: str) -> str:
    """
    Busca por match exacto en 'nombre'. Si no encuentra, hace match por normalización
    (ej: 'Santander Visa' == 'santander_visa').
    """
    # 1) exacto
    r = supabase.table(table).select("id,nombre").eq("nombre", value).limit(1).execute()
    if r.data:
        return r.data[0]["id"]

    # 2) normalizado (trae lista y matchea)
    all_rows = supabase.table(table).select("id,nombre").execute().data or []
    target = norm(value)
    for row in all_rows:
        if norm(row["nombre"]) == target:
            return row["id"]

    raise ValueError(f"No existe {table}.nombre='{value}' (ni por alias normalizado)")


def get_default_categoria_id() -> str:
    r = supabase.table("categorias").select("id").order("nombre").limit(1).execute()
    if not r.data:
        raise ValueError("No hay categorías cargadas")
    return r.data[0]["id"]


def categorize(merchant: str, default_cat_id: str) -> str:
    """
    Regla simple por texto. Si querés, después lo hacemos configurable en Supabase.
    """
    m = merchant.upper()

    rules = [
        (r"(PEDIDOSYA|RAPPI|MCDONALD|BURGER|MOSTAZA)", "Comida"),
        (r"(UBER|DIDI|CABIFY|TAXI)", "Transporte"),
        (r"(NETFLIX|SPOTIFY|DISNEY|HBO|PRIME)", "Suscripciones"),
        (r"(SUPERMERC|COTO|CARREFOUR|DIA|JUMBO|VEA)", "Supermercado"),
    ]

    # trae categorías una vez por request (simple)
    cats = supabase.table("categorias").select("id,nombre").execute().data or []
    cat_map = {norm(c["nombre"]): c["id"] for c in cats}

    for pattern, cat_name in rules:
        if re.search(pattern, m):
            cid = cat_map.get(norm(cat_name))
            if cid:
                return cid

    return default_cat_id


# ======================
# Webhook
# ======================
@app.post("/telegram")
async def telegram_webhook(req: Request):
    # Seguridad: Telegram puede mandar este header si seteás secret_token en setWebhook
    secret_hdr = req.headers.get("x-telegram-bot-api-secret-token")
    if secret_hdr != TELEGRAM_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

    body = await req.json()

    msg = body.get("message") or body.get("edited_message") or {}
    text = msg.get("text")
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id", ""))
    message_id = msg.get("message_id")

    if ALLOWED_CHAT_ID and chat_id != str(ALLOWED_CHAT_ID):
        raise HTTPException(status_code=403, detail="Chat not allowed")

    if not text:
        return {"ok": True}

    # Formatos:
    # g 12500 supermercado galicia
    # i 250000 sueldo galicia
    # t 18990 uber santander_visa
    # p 120000 galicia santander_visa
    # opcional fecha al final: YYYY-MM-DD
    try:
        parts = text.strip().split()
        if len(parts) < 3:
            return {"ok": True, "error": "Formato corto"}

        kind = parts[0].lower()
        amount = parse_amount(parts[1])

        f = date.today()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", parts[-1]):
            f = datetime.strptime(parts[-1], "%Y-%m-%d").date()
            parts = parts[:-1]

        rest = parts[2:]

        default_cat_id = get_default_categoria_id()

        # dedupe reference
        raw_ref = f"tg:{chat_id}:{message_id}"

        if kind in ("g", "i"):
            # ultimo token = cuenta
            cuenta = rest[-1]
            desc = " ".join(rest[:-1]) if len(rest) > 1 else "Sin desc"

            cta_id = find_id_by_name("cuentas", cuenta)
            cat_id = categorize(desc, default_cat_id)

            tipo = "GASTO" if kind == "g" else "INGRESO"

            payload = {
                "fecha": str(f),
                "monto": amount,
                "descripcion": desc,
                "cuenta_id": cta_id,
                "categoria_id": cat_id,
                "tipo": tipo,
                "source": "telegram",
                "raw_reference": raw_ref,
                "merchant": desc,
            }

            # upsert por raw_reference para no duplicar
            supabase.table("movimientos").upsert(payload, on_conflict="raw_reference").execute()

        elif kind == "t":
            # compra tarjeta
            tarjeta = rest[-1]
            desc = " ".join(rest[:-1]) if len(rest) > 1 else "Consumo tarjeta"

            tid = find_id_by_name("cuentas", tarjeta)
            cat_id = categorize(desc, default_cat_id)

            payload = {
                "fecha": str(f),
                "monto": amount,
                "descripcion": desc,
                "cuenta_id": tid,
                "categoria_id": cat_id,
                "tipo": "COMPRA_TARJETA",
                "source": "telegram",
                "raw_reference": raw_ref,
                "merchant": desc,
            }

            supabase.table("movimientos").upsert(payload, on_conflict="raw_reference").execute()

        elif kind == "p":
            # pago tarjeta (transferencia)
            if len(rest) < 2:
                return {"ok": True, "error": "p requiere origen y tarjeta"}

            origen = rest[0]
            tarjeta = rest[1]

            id_origen = find_id_by_name("cuentas", origen)
            id_tarjeta = find_id_by_name("cuentas", tarjeta)

            payload = {
                "fecha": str(f),
                "monto": amount,
                "descripcion": f"Pago tarjeta {tarjeta}",
                "cuenta_id": id_origen,
                "cuenta_destino_id": id_tarjeta,
                "categoria_id": default_cat_id,
                "tipo": "PAGO_TARJETA",
                "source": "telegram",
                "raw_reference": raw_ref,
            }

            supabase.table("movimientos").upsert(payload, on_conflict="raw_reference").execute()

        else:
            return {"ok": True, "error": "Tipo inválido (g/i/t/p)"}

    except Exception as e:
        try:
            supabase.table("bot_errors").insert({
                "source": "telegram",
                "message": str(e),
                "raw_payload": body
            }).execute()
        except Exception:
            pass
        return {"ok": True, "error": str(e)}

    return {"ok": True}
