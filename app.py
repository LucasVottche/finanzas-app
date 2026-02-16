import os
import re
from datetime import date, datetime
from fastapi import FastAPI, Request, HTTPException
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
TELEGRAM_SECRET = os.environ["TELEGRAM_SECRET"]
ALLOWED_CHAT_ID = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID")  # opcional

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
app = FastAPI()

def find_id(table: str, field: str, value: str):
    r = supabase.table(table).select("id").eq(field, value).limit(1).execute()
    if not r.data:
        raise ValueError(f"No existe {table}.{field}={value}")
    return r.data[0]["id"]

def parse_amount(s: str) -> float:
    s = s.replace("$","").replace(" ","")
    if "," in s and "." in s:
        s = s.replace(".","").replace(",",".")
    elif "," in s:
        s = s.replace(",",".")
    return abs(float(s))

@app.post("/telegram")
async def telegram_webhook(req: Request):
    # Anti-spam: secret en querystring
    secret = req.query_params.get("secret")
    if secret != TELEGRAM_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

    body = await req.json()
    msg = body.get("message") or body.get("edited_message") or {}
    text = msg.get("text")
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id", ""))

    if ALLOWED_CHAT_ID and chat_id != str(ALLOWED_CHAT_ID):
        raise HTTPException(status_code=403, detail="Chat not allowed")

    if not text:
        return {"ok": True}

    # Formatos:
    # g 12500 supermercado visa
    # i 250000 sueldo galicia
    # t 18990 uber santander_visa [YYYY-MM-DD]
    # p 120000 galicia santander_visa [YYYY-MM-DD]
    # Nota: para cuenta/tarjeta usás el nombre EXACTO como en cuentas.nombre
    try:
        parts = text.strip().split()
        if len(parts) < 4:
            return {"ok": True, "error": "Formato corto"}

        kind = parts[0].lower()
        amount = parse_amount(parts[1])

        f = date.today()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", parts[-1]):
            f = datetime.strptime(parts[-1], "%Y-%m-%d").date()
            parts = parts[:-1]

        rest = parts[2:]

        # categoría default = primera
        cat_id = supabase.table("categorias").select("id").limit(1).execute().data[0]["id"]

        if kind in ("g","i"):
            cuenta = rest[-1]
            desc = " ".join(rest[:-1])
            cta_id = find_id("cuentas", "nombre", cuenta)
            tipo = "GASTO" if kind == "g" else "INGRESO"

            supabase.table("movimientos").insert({
                "fecha": str(f),
                "monto": amount,
                "descripcion": desc,
                "cuenta_id": cta_id,
                "categoria_id": cat_id,
                "tipo": tipo,
                "source": "telegram",
                "raw_reference": f"tg:{chat_id}:{msg.get('message_id')}",
                "merchant": desc
            }).execute()

        elif kind == "t":
            tarjeta = rest[-1]
            desc = " ".join(rest[:-1])
            tid = find_id("cuentas", "nombre", tarjeta)

            # inserta como compra_tarjeta + 1 cuota (consistente con tu app)
            compra = supabase.table("compras_tarjeta").insert({
                "fecha_compra": str(f),
                "monto_total": amount,
                "cuotas_total": 1,
                "cuenta_id": tid,
                "categoria_id": cat_id,
                "descripcion": desc,
                "source": "telegram",
                "raw_reference": f"tg:{chat_id}:{msg.get('message_id')}",
                "merchant": desc
            }).execute().data[0]
            supabase.table("cuotas_tarjeta").insert([{
                "compra_id": compra["id"],
                "nro_cuota": 1,
                "fecha_cuota": str(f),
                "monto_cuota": amount,
                "estado": "pendiente"
            }]).execute()

        elif kind == "p":
            if len(rest) < 2:
                return {"ok": True, "error": "p requiere origen y tarjeta"}
            origen = rest[0]
            tarjeta = rest[1]

            id_origen = find_id("cuentas", "nombre", origen)
            id_tarjeta = find_id("cuentas", "nombre", tarjeta)

            supabase.table("movimientos").insert({
                "fecha": str(f),
                "monto": amount,
                "descripcion": f"Pago tarjeta {tarjeta}",
                "cuenta_id": id_origen,
                "cuenta_destino_id": id_tarjeta,
                "categoria_id": cat_id,
                "tipo": "PAGO_TARJETA",
                "source": "telegram",
                "raw_reference": f"tg:{chat_id}:{msg.get('message_id')}",
            }).execute()

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
