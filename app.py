# app.py (Streamlit Cloud) — SIN Telegram / SIN FastAPI
import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import date, datetime, timedelta
import calendar
from dateutil.relativedelta import relativedelta
import plotly.express as px
import time
import re
import math

# =========================================================
# 1) CONFIG UI
# =========================================================
st.set_page_config(
    page_title="Finanzas Pro",
    page_icon="💸",
    layout="wide",
    initial_sidebar_state="expanded"
)

# =========================================================
# 2) CSS (Fintech style)
# =========================================================
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

div[data-testid="stMetric"] {
  background-color: var(--secondary-background-color);
  border: 1px solid rgba(128, 128, 128, 0.2);
  padding: 15px;
  border-radius: 10px;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.08);
}
div[data-testid="stMetricLabel"] p { font-weight: 600 !important; opacity: 0.85; }

.day-card {
  background-color: var(--secondary-background-color);
  border: 1px solid rgba(128, 128, 128, 0.2);
  border-radius: 8px;
  height: 110px;
  padding: 8px;
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  font-size: 0.85rem;
  margin-bottom: 8px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}
.day-header {
  font-weight: 700;
  color: var(--text-color);
  opacity: 0.85;
  margin-bottom: 4px;
  border-bottom: 1px solid rgba(128, 128, 128, 0.2);
}
.tag-ing {
  color: #4ade80;
  background: rgba(74, 222, 128, 0.1);
  padding: 2px 6px; border-radius: 4px; font-weight: 600; font-size: 0.75rem; margin-top: 2px;
}
.tag-gas {
  color: #f87171;
  background: rgba(248, 113, 113, 0.1);
  padding: 2px 6px; border-radius: 4px; font-weight: 600; font-size: 0.75rem; margin-top: 2px;
}
.sidebar-brand {
  font-size: 1.5rem;
  font-weight: 800;
  color: var(--text-color);
  margin-bottom: 1rem;
  padding: 10px;
  background: var(--secondary-background-color);
  border-radius: 8px;
  text-align: center;
  border: 1px solid rgba(128, 128, 128, 0.2);
}
.small-muted { opacity: 0.75; font-size: 0.88rem; }
.badge {
  display:inline-block; padding: 4px 8px; border-radius: 999px;
  border: 1px solid rgba(128,128,128,0.25);
  background: rgba(128,128,128,0.08);
  font-size: 0.78rem; margin-right: 6px;
}
</style>
""",
    unsafe_allow_html=True
)

# =========================================================
# 3) SUPABASE
# =========================================================
@st.cache_resource
def init_connection():
    url = st.secrets.get("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY")
    if not url or not key:
        st.error("Faltan SUPABASE_URL / SUPABASE_KEY en st.secrets (Streamlit Cloud → Settings → Secrets).")
        st.stop()
    return create_client(url, key)

supabase = init_connection()

def invalidate_caches():
    try:
        st.cache_data.clear()
    except Exception:
        pass

# =========================================================
# 4) LOGIN (bcrypt hash en st.secrets)
#   - Secrets recomendados:
#     APP_PASSWORD_HASH = "$2b$12$...."
# =========================================================
def _verify_password(plain: str) -> bool:
    pw_hash = st.secrets.get("APP_PASSWORD_HASH")
    pw_plain = st.secrets.get("APP_PASSWORD")  # fallback opcional (no recomendado)
    if pw_hash:
        try:
            import bcrypt
            return bcrypt.checkpw(plain.encode("utf-8"), pw_hash.encode("utf-8"))
        except Exception:
            st.error("No se pudo validar bcrypt. Asegurate de tener 'bcrypt' en requirements.txt.")
            return False
    if pw_plain:
        return plain == pw_plain
    # Si no hay secrets, cortamos
    st.error("Falta APP_PASSWORD_HASH (o APP_PASSWORD) en Secrets.")
    return False

def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False
    if st.session_state.password_correct:
        return True

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<br><h3 style='text-align:center'>🔐 Finanzas Pro</h3>", unsafe_allow_html=True)
        pwd = st.text_input("Contraseña", type="password")
        if st.button("Entrar", use_container_width=True):
            if _verify_password(pwd):
                st.session_state.password_correct = True
                st.rerun()
            else:
                st.error("Incorrecto")
    return False

if not check_password():
    st.stop()

# =========================================================
# 5) HELPERS
# =========================================================
def fmt_ars(valor):
    if valor is None or (isinstance(valor, float) and (math.isnan(valor) or math.isinf(valor))):
        valor = 0
    try:
        s = f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"$ {s[:-3]}" if s.endswith(",00") else f"$ {s}"
    except Exception:
        return "$ 0"

def safe_date(y: int, m: int, d: int) -> date:
    # Si d no existe en ese mes, usa último día
    last = calendar.monthrange(y, m)[1]
    d2 = max(1, min(int(d), last))
    return date(y, m, d2)

def month_name_es(m: int) -> str:
    names = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"]
    return names[m-1]

def parse_amount(s: str) -> float:
    s = str(s).replace("$", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    return abs(float(s))

def categorize_desc(desc: str, df_cat: pd.DataFrame) -> str:
    # reglas simples por merchant / texto
    d = (desc or "").upper()

    rules = [
        (r"(PEDIDOSYA|RAPPI|DELIVERY|HAMBURG|PIZZA|KFC|MCDONALD|BURGER)", "Comida"),
        (r"(UBER|DIDI|CABIFY|TAXI|SUBE)", "Transporte"),
        (r"(NETFLIX|SPOTIFY|DISNEY|HBO|PRIME VIDEO|YOUTUBE)", "Suscripciones"),
        (r"(FARMAC|FARMACITY|PERFUMER|DROGUER)", "Salud"),
        (r"(SUPERMERC|COTO|DIA|JUMBO|CARREFOUR|CHANGO|VEA)", "Supermercado"),
        (r"(MERCADOPAGO|MP\*|MERCADO LIBRE|ML\*)", "MercadoPago"),
        (r"(LUZ|EDENOR|EDESUR|AYSA|GAS|METROGAS|NATURGY|INTERNET|FIBERTEL|TELECENTRO|MOVISTAR|CLARO|PERSONAL)", "Servicios"),
    ]

    # si existe categoría exacta, usala
    existing = set((df_cat["nombre"].astype(str)).str.lower().tolist()) if not df_cat.empty else set()

    for pat, cat in rules:
        if re.search(pat, d):
            if cat.lower() in existing:
                return cat
            # fallback a "General" si no existe
            break

    if "general" in existing:
        return "General"
    # si no existe General, devolvemos primera
    return df_cat.iloc[0]["nombre"] if not df_cat.empty else "General"

# =========================================================
# 6) DATA ACCESS (cacheado)
# =========================================================
@st.cache_data(ttl=60)
def get_maestros():
    cta = pd.DataFrame(supabase.table("cuentas").select("*").execute().data or [])
    cat = pd.DataFrame(supabase.table("categorias").select("*").execute().data or [])
    try:
        su = float(
            (supabase.table("configuracion")
             .select("valor")
             .eq("clave", "sueldo_mensual")
             .execute().data or [{"valor": "0"}])[0]["valor"]
        )
    except Exception:
        su = 0.0
    return cta, cat, su

@st.cache_data(ttl=45)
def get_movimientos(desde: date, hasta: date, back_months: int = 0) -> pd.DataFrame:
    desde_ext = desde - relativedelta(months=back_months) if back_months else desde
    resp = (
        supabase.table("movimientos")
        .select("*, categorias(nombre, icono), cuentas:cuentas!cuenta_id(nombre, tipo, dia_cierre, dia_vencimiento)")
        .gte("fecha", str(desde_ext))
        .lte("fecha", str(hasta))
        .order("fecha")
        .execute()
    )
    if not resp.data:
        return pd.DataFrame()

    data = []
    for d in resp.data:
        r = d.copy()
        r["categoria"] = f"{(d.get('categorias') or {}).get('icono','')} {(d.get('categorias') or {}).get('nombre','General')}".strip()
        r["cuenta"] = (d.get("cuentas") or {}).get("nombre", "Efectivo")
        r["tipo_cta"] = (d.get("cuentas") or {}).get("tipo", "DEBITO")
        r["cierre"] = (d.get("cuentas") or {}).get("dia_cierre", 25)
        r["vto"] = (d.get("cuentas") or {}).get("dia_vencimiento", 5)
        r.pop("categorias", None)
        r.pop("cuentas", None)
        data.append(r)

    df = pd.DataFrame(data)
    if not df.empty:
        df["fecha"] = pd.to_datetime(df["fecha"]).dt.date
        df["monto"] = pd.to_numeric(df["monto"], errors="coerce").fillna(0.0)
    return df

@st.cache_data(ttl=45)
def get_suscripciones():
    return pd.DataFrame(supabase.table("suscripciones").select("*").execute().data or [])

@st.cache_data(ttl=45)
def get_metas():
    return pd.DataFrame(supabase.table("metas").select("*").execute().data or [])

@st.cache_data(ttl=45)
def get_compras_tarjeta(desde: date, hasta: date) -> pd.DataFrame:
    # compras (entidad)
    resp = (
        supabase.table("compras_tarjeta")
        .select("*")
        .gte("fecha_compra", str(desde))
        .lte("fecha_compra", str(hasta))
        .order("fecha_compra")
        .execute()
    )
    df = pd.DataFrame(resp.data or [])
    if not df.empty:
        df["fecha_compra"] = pd.to_datetime(df["fecha_compra"]).dt.date
        df["monto_total"] = pd.to_numeric(df["monto_total"], errors="coerce").fillna(0.0)
    return df

@st.cache_data(ttl=45)
def get_cuotas_tarjeta(desde: date, hasta: date) -> pd.DataFrame:
    # cuotas (para presupuesto mensual / proyecciones)
    resp = (
        supabase.table("cuotas_tarjeta")
        .select("*")
        .gte("fecha_cuota", str(desde))
        .lte("fecha_cuota", str(hasta))
        .order("fecha_cuota")
        .execute()
    )
    df = pd.DataFrame(resp.data or [])
    if not df.empty:
        df["fecha_cuota"] = pd.to_datetime(df["fecha_cuota"]).dt.date
        df["monto_cuota"] = pd.to_numeric(df["monto_cuota"], errors="coerce").fillna(0.0)
    return df

# =========================================================
# 7) DB WRITES
# =========================================================
def db_save_mov(fecha, monto, desc, cta_id, cat_id, tipo, dest_id=None, source="manual", raw_reference=None, merchant=None):
    payload = {
        "fecha": str(fecha),
        "monto": float(monto),
        "descripcion": desc,
        "cuenta_id": cta_id,
        "categoria_id": cat_id,
        "tipo": tipo,
        "source": source,
        "raw_reference": raw_reference,
        "merchant": merchant or desc,
    }
    if dest_id:
        payload["cuenta_destino_id"] = dest_id
    supabase.table("movimientos").insert(payload).execute()
    invalidate_caches()

def db_delete_mov(id_mov):
    supabase.table("movimientos").delete().eq("id", id_mov).execute()
    invalidate_caches()

def save_suscripcion(desc, monto, cta_id, cat_id, tipo):
    supabase.table("suscripciones").insert({
        "descripcion": desc, "monto": float(monto), "cuenta_id": cta_id, "categoria_id": cat_id, "tipo": tipo
    }).execute()
    invalidate_caches()

def delete_suscripcion(sid):
    supabase.table("suscripciones").delete().eq("id", sid).execute()
    invalidate_caches()

def save_meta(n, o, f):
    supabase.table("metas").insert({"nombre": n, "objetivo": float(o), "fecha_limite": str(f)}).execute()
    invalidate_caches()

def update_meta_ahorro(mid, v):
    supabase.table("metas").update({"ahorrado": float(v)}).eq("id", mid).execute()
    invalidate_caches()

def delete_meta(mid):
    supabase.table("metas").delete().eq("id", mid).execute()
    invalidate_caches()

def db_save_compra_tarjeta(fecha_compra, monto_total, cuotas_total, cuenta_id, categoria_id, descripcion,
                          source="manual", raw_reference=None, merchant=None):
    # inserta compra
    compra = supabase.table("compras_tarjeta").insert({
        "fecha_compra": str(fecha_compra),
        "monto_total": float(monto_total),
        "cuotas_total": int(cuotas_total),
        "cuenta_id": cuenta_id,
        "categoria_id": categoria_id,
        "descripcion": descripcion,
        "source": source,
        "raw_reference": raw_reference,
        "merchant": merchant or descripcion
    }).execute().data[0]

    # genera cuotas (virtuales / contables)
    cuotas = []
    monto_cuota = float(monto_total) / int(cuotas_total)
    for i in range(int(cuotas_total)):
        f_cuota = fecha_compra + relativedelta(months=i)
        cuotas.append({
            "compra_id": compra["id"],
            "nro_cuota": i + 1,
            "fecha_cuota": str(f_cuota),
            "monto_cuota": float(monto_cuota),
            "estado": "pendiente"
        })
    supabase.table("cuotas_tarjeta").insert(cuotas).execute()
    invalidate_caches()

def db_delete_compra_tarjeta(compra_id):
    # cascada borra cuotas por FK on delete cascade (si lo creaste así)
    supabase.table("compras_tarjeta").delete().eq("id", compra_id).execute()
    invalidate_caches()

def log_import_error(source: str, message: str, raw_payload: dict | None):
    try:
        supabase.table("import_errors").insert({
            "source": source,
            "message": message,
            "raw_payload": raw_payload
        }).execute()
    except Exception:
        pass

# =========================================================
# 8) CICLOS TARJETA
# =========================================================
def last_cierre_date(today: date, dia_cierre: int) -> date:
    cierre_this = safe_date(today.year, today.month, dia_cierre)
    if today > cierre_this:
        return cierre_this
    prev = today - relativedelta(months=1)
    return safe_date(prev.year, prev.month, dia_cierre)

def prev_cierre_date(cierre: date, dia_cierre: int) -> date:
    prev = cierre - relativedelta(months=1)
    return safe_date(prev.year, prev.month, dia_cierre)

def next_cierre_date(today: date, dia_cierre: int) -> date:
    cierre_this = safe_date(today.year, today.month, dia_cierre)
    if today <= cierre_this:
        return cierre_this
    nxt = today + relativedelta(months=1)
    return safe_date(nxt.year, nxt.month, dia_cierre)

def due_date_from_cierre(cierre: date, dia_vto: int) -> date:
    nxt = cierre + relativedelta(months=1)
    return safe_date(nxt.year, nxt.month, dia_vto)

def resumen_key_from_cierre(card_name: str, cierre: date) -> str:
    return f"{card_name} {cierre.year}-{cierre.month:02d}"

def get_tarjeta_installments(df_cta, df_cat, desde: date, hasta: date) -> pd.DataFrame:
    """
    Unifica consumos tarjeta:
      - cuotas_tarjeta (nuevo modelo)
      - movimientos tipo COMPRA_TARJETA (viejo/imports viejos)
    Devuelve columnas: fecha, monto, cuenta_id, cuenta, categoria, source, raw_reference
    """
    # cuotas nuevas
    df_q = get_cuotas_tarjeta(desde, hasta)
    df_out = []

    if not df_q.empty:
        compra_ids = df_q["compra_id"].unique().tolist()
        # traemos compras asociadas (en batches por si son muchas)
        df_p_all = []
        chunk = 150
        for i in range(0, len(compra_ids), chunk):
            ids = compra_ids[i:i+chunk]
            resp = supabase.table("compras_tarjeta").select("*").in_("id", ids).execute()
            df_p_all.append(pd.DataFrame(resp.data or []))
        df_p = pd.concat(df_p_all, ignore_index=True) if df_p_all else pd.DataFrame()

        if not df_p.empty:
            df_p["id"] = df_p["id"].astype(str)
            df_q["compra_id"] = df_q["compra_id"].astype(str)
            m = df_q.merge(df_p, left_on="compra_id", right_on="id", how="left", suffixes=("_cuota", "_compra"))
            # map nombres
            cta_map = dict(zip(df_cta["id"].astype(str), df_cta["nombre"].astype(str))) if not df_cta.empty else {}
            cat_map = dict(zip(df_cat["id"].astype(str), (df_cat["icono"].fillna("") + " " + df_cat["nombre"]).str.strip())) if not df_cat.empty else {}

            m["fecha"] = m["fecha_cuota"]
            m["monto"] = m["monto_cuota"]
            m["cuenta_id"] = m["cuenta_id"].astype(str)
            m["cuenta"] = m["cuenta_id"].map(cta_map).fillna("Tarjeta")
            m["categoria_id"] = m["categoria_id"].astype(str)
            m["categoria"] = m["categoria_id"].map(cat_map).fillna("General")
            m["source"] = m.get("source", "manual")
            m["raw_reference"] = m.get("raw_reference", None)
            m["descripcion"] = m.get("descripcion", "")

            df_out.append(m[["fecha", "monto", "cuenta_id", "cuenta", "categoria", "source", "raw_reference", "descripcion"]])

    # consumos viejos en movimientos
    df_m = get_movimientos(desde, hasta, back_months=0)
    if not df_m.empty:
        df_old = df_m[df_m["tipo"] == "COMPRA_TARJETA"].copy()
        if not df_old.empty:
            df_old["cuenta_id"] = df_old["cuenta_id"].astype(str)
            df_old["fecha"] = df_old["fecha"]
            df_old["monto"] = df_old["monto"]
            df_old["source"] = df_old.get("source", "manual")
            df_old["raw_reference"] = df_old.get("raw_reference", None)
            df_old["descripcion"] = df_old.get("descripcion", "")
            df_out.append(df_old[["fecha", "monto", "cuenta_id", "cuenta", "categoria", "source", "raw_reference", "descripcion"]])

    if not df_out:
        return pd.DataFrame(columns=["fecha","monto","cuenta_id","cuenta","categoria","source","raw_reference","descripcion"])

    out = pd.concat(df_out, ignore_index=True)
    out["fecha"] = pd.to_datetime(out["fecha"]).dt.date
    out["monto"] = pd.to_numeric(out["monto"], errors="coerce").fillna(0.0)
    return out

# =========================================================
# 9) CARGA MAESTROS
# =========================================================
df_cta, df_cat, sueldo_base = get_maestros()

# =========================================================
# 10) SIDEBAR
# =========================================================
with st.sidebar:
    st.markdown('<div class="sidebar-brand">🦅 Finanzas Pro</div>', unsafe_allow_html=True)
    menu = st.radio(
        "Navegación",
        ["📊 Dashboard", "📅 Calendario", "➕ Nueva Operación", "🎯 Metas", "📝 Historial", "💳 Tarjetas", "⚙️ Ajustes"],
        label_visibility="collapsed"
    )
    st.markdown("---")
    c_mes, c_anio = st.columns(2)
    mes_sel = c_mes.selectbox("Mes", range(1, 13), index=date.today().month - 1)
    anio_sel = c_anio.number_input("Año", value=date.today().year, step=1)
    f_ini = date(int(anio_sel), int(mes_sel), 1)
    f_fin = f_ini + relativedelta(months=1) - timedelta(days=1)

# =========================================================
# 11) DASHBOARD
# =========================================================
if menu == "📊 Dashboard":
    st.markdown(f"## 📈 Balance: {month_name_es(f_ini.month).title()} {f_ini.year}")

    # movimientos cash / ingresos / pagos
    df_raw = get_movimientos(f_ini, f_fin, back_months=0)

    # consumos tarjeta (cuotas + viejos)
    df_tj_mes = get_tarjeta_installments(df_cta, df_cat, f_ini, f_fin)

    if (df_raw.empty) and (df_tj_mes.empty):
        st.warning("No hay datos en este mes.")
    else:
        df_mes = df_raw.copy() if not df_raw.empty else pd.DataFrame()
        if not df_mes.empty:
            df_mes = df_mes[(df_mes["fecha"] >= f_ini) & (df_mes["fecha"] <= f_fin)]

        # ingresos
        ing_reg = 0.0
        if not df_mes.empty:
            ing_reg = df_mes[df_mes["tipo"] == "INGRESO"]["monto"].sum()
        total_ingresos = ing_reg if ing_reg > 0 else float(sueldo_base or 0)

        # gastos cash (incluye GASTO, TRANSFERENCIA saliente; excluye PAGO_TARJETA)
        gastos_cash = 0.0
        if not df_mes.empty:
            gastos_cash = df_mes[df_mes["tipo"] == "GASTO"]["monto"].sum()

        gastos_tj = float(df_tj_mes["monto"].sum()) if not df_tj_mes.empty else 0.0

        total_consumo = gastos_cash + gastos_tj
        saldo_mes = total_ingresos - total_consumo

        # "Pagar resumen" (estimación): sumatoria de saldos pendientes por tarjeta con vto en este mes
        hoy = date.today()
        pagar_resumen_mes = 0.0
        if not df_cta.empty:
            df_cards = df_cta[df_cta["tipo"] == "CREDITO"].copy()
            if not df_cards.empty:
                # consumos necesarios para calcular statement (traemos 2 meses)
                from_x = f_ini - relativedelta(months=2)
                to_x = f_fin
                df_tj_ext = get_tarjeta_installments(df_cta, df_cat, from_x, to_x)
                df_mov_ext = get_movimientos(from_x, to_x, back_months=0)

                for _, card in df_cards.iterrows():
                    dia_cierre = int(card.get("dia_cierre") or 25)
                    dia_vto = int(card.get("dia_vencimiento") or 5)

                    # statements cuyo vto cae entre f_ini..f_fin:
                    # aproximación: tomamos el último cierre previo al fin de mes y vemos su vto
                    cierre = last_cierre_date(f_fin, dia_cierre)
                    vto = due_date_from_cierre(cierre, dia_vto)
                    # si vto cae en este mes, calculamos saldo pendiente de ese cierre
                    if f_ini <= vto <= f_fin:
                        prev = prev_cierre_date(cierre, dia_cierre)
                        stmt_start = prev + timedelta(days=1)
                        stmt_end = cierre
                        card_id = str(card["id"])

                        stmt_total = df_tj_ext[(df_tj_ext["cuenta_id"] == card_id) &
                                              (df_tj_ext["fecha"] >= stmt_start) &
                                              (df_tj_ext["fecha"] <= stmt_end)]["monto"].sum()

                        pagos = 0.0
                        if not df_mov_ext.empty:
                            pagos = df_mov_ext[(df_mov_ext["tipo"] == "PAGO_TARJETA") &
                                               (df_mov_ext["cuenta_destino_id"].astype(str) == card_id) &
                                               (df_mov_ext["fecha"] >= cierre) &
                                               (df_mov_ext["fecha"] <= vto)]["monto"].sum()
                        pagar_resumen_mes += max(stmt_total - pagos, 0.0)

        caja_real = total_ingresos - gastos_cash - pagar_resumen_mes

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("💰 Resultado Neto", fmt_ars(saldo_mes), delta="Ingreso - Consumo Total")
        c2.metric("🏦 Caja Disponible", fmt_ars(caja_real), help="Dinero real tras pagar resumen (estimado) y cash")
        c3.metric("🛒 Consumo Total", fmt_ars(total_consumo), delta="Cash + Tarjeta", delta_color="inverse")
        c4.metric("💳 Pagar Resumen", fmt_ars(pagar_resumen_mes), delta="Vencimientos del mes", delta_color="inverse")

        st.divider()
        g1, g2 = st.columns([2, 1])

        # dataset para chart: gastos cash + gastos tarjeta (cuotas)
        df_chart = pd.DataFrame()
        if not df_mes.empty:
            df_chart = df_mes[df_mes["tipo"] != "INGRESO"][["fecha", "monto", "categoria"]].copy()
        if not df_tj_mes.empty:
            df_tj_chart = df_tj_mes[["fecha", "monto", "categoria"]].copy()
            df_chart = pd.concat([df_chart, df_tj_chart], ignore_index=True)

        with g1:
            st.markdown("##### 📈 Evolución")
            if not df_chart.empty:
                fig = px.bar(df_chart, x="fecha", y="monto", color="categoria")
                fig.update_layout(xaxis_title=None, yaxis_title=None, height=320, margin=dict(l=0, r=0, t=0, b=0))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Sin gastos.")

        with g2:
            st.markdown("##### 🍰 Rubros")
            if not df_chart.empty:
                fig_p = px.pie(df_chart, values="monto", names="categoria", hole=0.6)
                fig_p.update_layout(showlegend=False, height=320, margin=dict(l=0, r=0, t=0, b=0))
                st.plotly_chart(fig_p, use_container_width=True)
            else:
                st.info("Sin rubros.")

# =========================================================
# 12) CALENDARIO
# =========================================================
elif menu == "📅 Calendario":
    st.markdown(f"### 📅 Agenda: {month_name_es(f_ini.month).title()} {f_ini.year}")

    df_cal_mov = get_movimientos(f_ini, f_fin, back_months=0)
    df_cal_tj = get_tarjeta_installments(df_cta, df_cat, f_ini, f_fin)

    # armamos eventos: ingresos desde movimientos; gastos = gastos cash + cuotas tarjeta
    df_events = []
    if not df_cal_mov.empty:
        df_events.append(df_cal_mov[["fecha", "tipo", "monto", "descripcion"]].copy())
    if not df_cal_tj.empty:
        t = df_cal_tj.copy()
        t["tipo"] = "COMPRA_TARJETA"
        t["descripcion"] = t["descripcion"].fillna("Tarjeta")
        df_events.append(t[["fecha", "tipo", "monto", "descripcion"]])

    df_cal = pd.concat(df_events, ignore_index=True) if df_events else pd.DataFrame(columns=["fecha","tipo","monto","descripcion"])
    if not df_cal.empty:
        df_cal["fecha"] = pd.to_datetime(df_cal["fecha"]).dt.date
        df_cal["monto"] = pd.to_numeric(df_cal["monto"], errors="coerce").fillna(0.0)

    cal = calendar.Calendar()
    semanas = cal.monthdayscalendar(int(anio_sel), int(mes_sel))
    dias = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]

    cols = st.columns(7)
    for i, d in enumerate(dias):
        cols[i].markdown(f"<div style='text-align:center; font-weight:600; opacity:0.7;'>{d}</div>", unsafe_allow_html=True)

    for semana in semanas:
        cols = st.columns(7)
        for i, dia in enumerate(semana):
            with cols[i]:
                if dia != 0:
                    fecha_dia = date(int(anio_sel), int(mes_sel), int(dia))
                    content_html = f"<div class='day-header'>{dia}</div>"
                    evs = df_cal[df_cal["fecha"] == fecha_dia] if not df_cal.empty else pd.DataFrame()

                    ing = evs[evs["tipo"] == "INGRESO"]["monto"].sum() if not evs.empty else 0
                    gas = evs[evs["tipo"] != "INGRESO"]["monto"].sum() if not evs.empty else 0

                    if ing > 0:
                        content_html += f"<div class='tag-ing'>+{fmt_ars(ing)}</div>"
                    if gas > 0:
                        content_html += f"<div class='tag-gas'>-{fmt_ars(gas)}</div>"

                    st.markdown(f"<div class='day-card'>{content_html}</div>", unsafe_allow_html=True)

                    if not evs.empty:
                        with st.popover("Ver", use_container_width=True):
                            st.caption(f"{dia}/{mes_sel}/{anio_sel}")
                            st.dataframe(evs[["descripcion", "tipo", "monto"]], hide_index=True, use_container_width=True)
                else:
                    st.write("")

# =========================================================
# 13) NUEVA OPERACIÓN
# =========================================================
elif menu == "➕ Nueva Operación":
    st.markdown("### Registrar Movimiento")
    t1, t2, t3 = st.tabs(["Manual / Cuotas", "🔄 Fijos", "📥 Importar Excel"])

    # -------------------------
    # Manual / cuotas
    # -------------------------
    with t1:
        with st.container(border=True):
            tipo_op = st.radio("Tipo", ["Gasto", "Ingreso", "Pagar Tarjeta"], horizontal=True)
            st.divider()
            c1, c2 = st.columns(2)
            f = c1.date_input("Fecha", date.today())
            m = c2.number_input("Monto", min_value=0.0, step=100.0)
            d = st.text_input("Descripción")

            c3, c4 = st.columns(2)

            if tipo_op == "Pagar Tarjeta":
                cta_n = c3.selectbox("Desde", df_cta[df_cta["tipo"] != "CREDITO"]["nombre"].tolist() if not df_cta.empty else [])
                cta_dest = c4.selectbox("Tarjeta", df_cta[df_cta["tipo"] == "CREDITO"]["nombre"].tolist() if not df_cta.empty else [])
                cat_n = "General" if (not df_cat.empty and "General" in df_cat["nombre"].tolist()) else (df_cat.iloc[0]["nombre"] if not df_cat.empty else "General")
            else:
                cta_n = c3.selectbox("Cuenta", df_cta["nombre"].tolist() if not df_cta.empty else [])
                cat_n = c4.selectbox("Categoría", df_cat["nombre"].tolist() if not df_cat.empty else ["General"])

            cuotas = 1
            if tipo_op == "Gasto":
                # cuotas solo si la cuenta es crédito
                es_credito = False
                if not df_cta.empty and cta_n:
                    es_credito = (df_cta[df_cta["nombre"] == cta_n]["tipo"].values[0] == "CREDITO")
                if es_credito:
                    cuotas = st.slider("Cuotas (tarjeta)", 1, 24, 1)
                else:
                    cuotas = 1

            if st.button("Guardar", type="primary", use_container_width=True):
                if df_cta.empty or df_cat.empty:
                    st.error("Faltan cuentas o categorías cargadas.")
                else:
                    id_c = df_cta[df_cta["nombre"] == cta_n]["id"].values[0]
                    id_cat = df_cat[df_cat["nombre"] == cat_n]["id"].values[0]

                    if tipo_op == "Pagar Tarjeta":
                        id_d = df_cta[df_cta["nombre"] == cta_dest]["id"].values[0]
                        db_save_mov(f, m, d or f"Pago tarjeta {cta_dest}", id_c, id_cat, "PAGO_TARJETA", dest_id=id_d, source="manual")
                    elif tipo_op == "Ingreso":
                        db_save_mov(f, m, d, id_c, id_cat, "INGRESO", source="manual")
                    else:
                        # Gasto
                        es_cred = df_cta[df_cta["nombre"] == cta_n]["tipo"].values[0] == "CREDITO"
                        if es_cred:
                            # Nuevo modelo: compra_tarjeta + cuotas
                            db_save_compra_tarjeta(
                                fecha_compra=f,
                                monto_total=m,
                                cuotas_total=cuotas,
                                cuenta_id=id_c,
                                categoria_id=id_cat,
                                descripcion=d,
                                source="manual",
                                raw_reference=None,
                                merchant=d
                            )
                        else:
                            # Gasto cash
                            db_save_mov(f, m, d, id_c, id_cat, "GASTO", source="manual")

                    st.toast("✅ Guardado")
                    time.sleep(0.6)
                    st.rerun()

    # -------------------------
    # Fijos
    # -------------------------
    with t2:
        df_sus = get_suscripciones()
        if not df_sus.empty:
            c_date, c_info = st.columns([1, 2])
            fecha_imp = c_date.date_input("Fecha Impacto", date.today().replace(day=5))
            c_info.info(f"Se crearán en **{month_name_es(fecha_imp.month).title()}**.")

            ed_sus = st.data_editor(
                df_sus[["descripcion", "monto"]],
                use_container_width=True,
                num_rows="fixed",
                column_config={"monto": st.column_config.NumberColumn("Monto", format="$ %.2f")}
            )

            if st.button("🚀 Procesar", type="primary"):
                c = 0
                for i, row in ed_sus.iterrows():
                    if i in df_sus.index:
                        orig = df_sus.loc[i]
                        # si la suscripción es tarjeta, lo dejamos como compra de 1 cuota
                        cuenta_id = orig["cuenta_id"]
                        tipo = str(orig.get("tipo") or "GASTO")
                        if tipo == "COMPRA_TARJETA":
                            db_save_compra_tarjeta(
                                fecha_compra=fecha_imp,
                                monto_total=row["monto"],
                                cuotas_total=1,
                                cuenta_id=cuenta_id,
                                categoria_id=orig["categoria_id"],
                                descripcion=row["descripcion"],
                                source="fijo",
                                raw_reference=None,
                                merchant=row["descripcion"]
                            )
                        else:
                            db_save_mov(
                                fecha_imp, row["monto"], row["descripcion"],
                                cuenta_id, orig["categoria_id"], tipo,
                                source="fijo"
                            )
                        c += 1
                st.toast(f"✅ {c} movimientos procesados")
                time.sleep(0.6)
                st.rerun()
        else:
            st.warning("No hay fijos configurados.")

    # -------------------------
    # Importar Excel
    # -------------------------
    with t3:
        up = st.file_uploader("Excel/CSV Santander/Galicia (o similar)", type=["xlsx", "csv"])
        if up:
            try:
                if up.name.endswith(".csv"):
                    df_u = pd.read_csv(up)
                else:
                    raw = pd.read_excel(up)
                    head = 0
                    for i in range(len(raw)):
                        rowvals = [str(x).upper() for x in raw.iloc[i].values]
                        if any("FECHA" in v for v in rowvals):
                            head = i + 1
                            break
                    df_u = pd.read_excel(up, skiprows=head)

                df_u = df_u.dropna(how="all").reset_index(drop=True)
                st.dataframe(df_u.head(5), use_container_width=True)

                with st.form("imp"):
                    tarjetas = df_cta[df_cta["tipo"] == "CREDITO"]["nombre"].tolist() if not df_cta.empty else []
                    sel = st.selectbox("Tarjeta Destino", tarjetas)

                    c1, c2, c3 = st.columns(3)
                    fc = c1.selectbox("Col. Fecha", df_u.columns)
                    dc = c2.selectbox("Col. Detalle", df_u.columns)
                    mc = c3.selectbox("Col. Pesos", df_u.columns)

                    if st.form_submit_button("Importar"):
                        if not sel:
                            st.error("No hay tarjetas cargadas.")
                        else:
                            tid = df_cta[df_cta["nombre"] == sel]["id"].values[0]

                            # map de categorías por nombre
                            cat_by_name = {str(r["nombre"]): str(r["id"]) for _, r in df_cat.iterrows()} if not df_cat.empty else {}
                            cat_default_name = "General" if "General" in cat_by_name else (df_cat.iloc[0]["nombre"] if not df_cat.empty else "General")
                            cat_default_id = cat_by_name.get(cat_default_name)

                            inserted = 0
                            skipped = 0
                            errors = 0

                            for idx, r in df_u.iterrows():
                                try:
                                    desc = str(r[dc]).strip()
                                    if not desc or desc.lower() == "nan":
                                        continue

                                    ms = str(r[mc]).replace("$", "").replace(" ", "")
                                    val = parse_amount(ms)
                                    fval = pd.to_datetime(r[fc], dayfirst=True, errors="coerce")
                                    if pd.isna(fval):
                                        continue
                                    fval = fval.date()

                                    # categoriza
                                    cat_name = categorize_desc(desc, df_cat)
                                    cat_id = cat_by_name.get(cat_name, cat_default_id)

                                    # dedupe básico en compras_tarjeta
                                    exists = (
                                        supabase.table("compras_tarjeta")
                                        .select("id")
                                        .eq("fecha_compra", str(fval))
                                        .eq("monto_total", float(val))
                                        .eq("cuenta_id", str(tid))
                                        .eq("descripcion", desc)
                                        .limit(1)
                                        .execute()
                                    )
                                    if exists.data:
                                        skipped += 1
                                        continue

                                    # inserta como compra de 1 cuota
                                    db_save_compra_tarjeta(
                                        fecha_compra=fval,
                                        monto_total=val,
                                        cuotas_total=1,
                                        cuenta_id=tid,
                                        categoria_id=cat_id,
                                        descripcion=desc,
                                        source="excel",
                                        raw_reference=f"{up.name}:row{idx}",
                                        merchant=desc
                                    )
                                    inserted += 1

                                except Exception as e:
                                    errors += 1
                                    log_import_error("excel", f"Row {idx}: {e}", {"row": int(idx), "detalle": str(r.to_dict())})

                            st.success(f"Importado: {inserted} | Duplicados: {skipped} | Errores: {errors}")
                            time.sleep(0.6)
                            st.rerun()

            except Exception as e:
                st.error(f"Error importando: {e}")

# =========================================================
# 14) METAS
# =========================================================
elif "Metas" in menu:
    st.markdown("### 🎯 Objetivos")
    df_m = get_metas()
    c1, c2 = st.columns([1, 2])
    with c1:
        with st.container(border=True):
            st.markdown("#### Nueva Meta")
            n = st.text_input("Nombre")
            o = st.number_input("Objetivo ($)", min_value=1.0)
            l = st.date_input("Límite")
            if st.button("Crear", type="primary", use_container_width=True):
                save_meta(n, o, l)
                st.rerun()

    with c2:
        if not df_m.empty:
            for _, m in df_m.iterrows():
                with st.container(border=True):
                    ca, cb = st.columns([3, 1])
                    objetivo = float(m.get("objetivo") or 0)
                    ah = float(m.get("ahorrado") or 0)
                    pct = ah / objetivo if objetivo > 0 else 0
                    ca.markdown(f"**{m.get('nombre','Meta')}**")
                    ca.progress(min(pct, 1.0))
                    ca.caption(f"{fmt_ars(ah)} / {fmt_ars(objetivo)}")
                    nv = cb.number_input("Monto", value=float(ah), key=f"v{m['id']}", label_visibility="collapsed")
                    if cb.button("💾", key=f"s{m['id']}"):
                        update_meta_ahorro(m["id"], nv)
                        st.rerun()
                    if cb.button("🗑️", key=f"d{m['id']}"):
                        delete_meta(m["id"])
                        st.rerun()
        else:
            st.info("Sin metas.")

# =========================================================
# 15) HISTORIAL
# =========================================================
elif "Historial" in menu:
    st.markdown("### 📝 Historial")

    tab_mov, tab_comp = st.tabs(["Movimientos (cash/pagos)", "Compras Tarjeta (entidad)"])

    # -------- Movimientos
    with tab_mov:
        check_col, _ = st.columns([1, 3])
        ver_todo = check_col.checkbox("Ver todo histórico (movimientos)")
        df_h = get_movimientos(date(2024, 1, 1), date(2027, 1, 1), back_months=0) if ver_todo else get_movimientos(f_ini, f_fin, back_months=0)
        if not ver_todo and not df_h.empty:
            df_h = df_h[(df_h["fecha"] >= f_ini) & (df_h["fecha"] <= f_fin)]

        if not df_h.empty:
            st.data_editor(
                df_h[["id", "fecha", "descripcion", "monto", "cuenta", "tipo"]],
                column_config={"monto": st.column_config.NumberColumn("Monto", format="$ %.2f")},
                use_container_width=True, hide_index=True
            )
            with st.expander("🗑️ Borrado (movimientos)"):
                ops = {f"{r['fecha']} | {r.get('descripcion','')} | {fmt_ars(r['monto'])}": r["id"] for _, r in df_h.iterrows()}
                s = st.selectbox("Elegir:", ["..."] + list(ops.keys()))
                if st.button("Eliminar Item") and s != "...":
                    db_delete_mov(ops[s])
                    st.toast("Eliminado")
                    time.sleep(0.5)
                    st.rerun()
        else:
            st.info("Sin datos en movimientos.")

    # -------- Compras tarjeta
    with tab_comp:
        check_col2, _ = st.columns([1, 3])
        ver_todo_c = check_col2.checkbox("Ver todo histórico (compras tarjeta)")
        df_c = get_compras_tarjeta(date(2024, 1, 1), date(2027, 1, 1)) if ver_todo_c else get_compras_tarjeta(f_ini, f_fin)

        if not df_c.empty:
            # map nombres
            cta_map = dict(zip(df_cta["id"].astype(str), df_cta["nombre"].astype(str))) if not df_cta.empty else {}
            cat_map = dict(zip(df_cat["id"].astype(str), (df_cat["icono"].fillna("") + " " + df_cat["nombre"]).str.strip())) if not df_cat.empty else {}
            df_c["cuenta"] = df_c["cuenta_id"].astype(str).map(cta_map).fillna("Tarjeta")
            df_c["categoria"] = df_c["categoria_id"].astype(str).map(cat_map).fillna("General")

            st.dataframe(
                df_c[["fecha_compra","descripcion","cuenta","categoria","monto_total","cuotas_total","source"]],
                use_container_width=True,
                hide_index=True
            )

            with st.expander("🗑️ Borrado (compras tarjeta)"):
                ops = {f"{r['fecha_compra']} | {r['descripcion']} | {r['cuenta']} | {fmt_ars(r['monto_total'])}": r["id"] for _, r in df_c.iterrows()}
                s = st.selectbox("Elegir compra:", ["..."] + list(ops.keys()), key="delcomp")
                if st.button("Eliminar Compra (borra cuotas)") and s != "...":
                    db_delete_compra_tarjeta(ops[s])
                    st.toast("Compra eliminada")
                    time.sleep(0.5)
                    st.rerun()
        else:
            st.info("Sin compras tarjeta en el rango.")

# =========================================================
# 16) TARJETAS (mejorado)
# =========================================================
elif "Tarjetas" in menu:
    st.markdown("### 💳 Tarjetas")

    if df_cta.empty:
        st.warning("No hay cuentas cargadas.")
    else:
        df_cards = df_cta[df_cta["tipo"] == "CREDITO"].copy()
        if df_cards.empty:
            st.info("No hay tarjetas (cuentas tipo CREDITO).")
        else:
            # Traemos consumos extendidos para armar estados y comparativas
            hoy = date.today()
            desde_ext = hoy - relativedelta(months=6)
            hasta_ext = hoy + relativedelta(months=1)
            df_tj_ext = get_tarjeta_installments(df_cta, df_cat, desde_ext, hasta_ext)
            df_mov_ext = get_movimientos(desde_ext, hasta_ext, back_months=0)

            tab_estado, tab_config = st.tabs(["Estado", "Config"])

            # ----------------- ESTADO
            with tab_estado:
                for _, card in df_cards.iterrows():
                    card_id = str(card["id"])
                    card_name = str(card["nombre"])
                    dia_cierre = int(card.get("dia_cierre") or 25)
                    dia_vto = int(card.get("dia_vencimiento") or 5)
                    limite_total = card.get("limite_total", None)
                    pago_min_pct = float(card.get("pago_minimo_pct") or 0.10)
                    pago_min_fijo = card.get("pago_minimo_fijo", None)

                    cierre = last_cierre_date(hoy, dia_cierre)
                    prev = prev_cierre_date(cierre, dia_cierre)
                    vto = due_date_from_cierre(cierre, dia_vto)
                    next_cierre = next_cierre_date(hoy, dia_cierre)

                    stmt_start = prev + timedelta(days=1)
                    stmt_end = cierre
                    open_start = cierre + timedelta(days=1)
                    open_end = hoy

                    stmt_total = df_tj_ext[(df_tj_ext["cuenta_id"] == card_id) &
                                           (df_tj_ext["fecha"] >= stmt_start) &
                                           (df_tj_ext["fecha"] <= stmt_end)]["monto"].sum()

                    open_total = df_tj_ext[(df_tj_ext["cuenta_id"] == card_id) &
                                           (df_tj_ext["fecha"] >= open_start) &
                                           (df_tj_ext["fecha"] <= open_end)]["monto"].sum()

                    pagos = 0.0
                    if not df_mov_ext.empty:
                        pagos = df_mov_ext[(df_mov_ext["tipo"] == "PAGO_TARJETA") &
                                           (df_mov_ext["cuenta_destino_id"].astype(str) == card_id) &
                                           (df_mov_ext["fecha"] >= cierre) &
                                           (df_mov_ext["fecha"] <= vto)]["monto"].sum()

                    saldo_pend = max(stmt_total - pagos, 0.0)

                    # mínimo simulado
                    if pago_min_fijo is not None and str(pago_min_fijo) != "nan":
                        min_pay = float(pago_min_fijo)
                    else:
                        min_pay = float(stmt_total) * pago_min_pct

                    # uso límite
                    uso_pct = None
                    if limite_total not in (None, "", "nan"):
                        try:
                            lim = float(limite_total)
                            if lim > 0:
                                uso_pct = (stmt_total + open_total) / lim
                        except Exception:
                            uso_pct = None

                    with st.container(border=True):
                        top = st.columns([2.2, 1, 1, 1])
                        top[0].markdown(f"#### **{card_name}**")
                        top[0].markdown(
                            f"<span class='badge'>Cierre: {cierre.strftime('%d/%m/%Y')}</span>"
                            f"<span class='badge'>Vto: {vto.strftime('%d/%m/%Y')}</span>"
                            f"<span class='badge'>Próximo cierre: {next_cierre.strftime('%d/%m/%Y')}</span>",
                            unsafe_allow_html=True
                        )

                        m1, m2, m3 = st.columns(3)
                        m1.metric(f"💳 A pagar (vto {vto.strftime('%d/%m')})", fmt_ars(saldo_pend))
                        m2.metric(f"🧾 Compras en curso (cierre {next_cierre.strftime('%d/%m')})", fmt_ars(open_total))
                        m3.metric("📈 Uso de límite", f"{(uso_pct*100):.0f}%" if uso_pct is not None else "—")

                        # Alertas
                        alerts = []
                        days_to_cierre = (next_cierre - hoy).days
                        days_to_vto = (vto - hoy).days
                        if days_to_cierre >= 0 and days_to_cierre <= 7:
                            alerts.append(f"⏳ Faltan **{days_to_cierre}** días para el **cierre**.")
                        if days_to_vto >= 0 and days_to_vto <= 7:
                            alerts.append(f"⚠️ Faltan **{days_to_vto}** días para el **vencimiento**.")
                        if uso_pct is not None and uso_pct > 0.30:
                            alerts.append("📉 Te pasaste del **30%** recomendado de utilización.")
                        if saldo_pend > 0 and min_pay > 0:
                            alerts.append(f"💡 Pago mínimo estimado: **{fmt_ars(min_pay)}**")

                        if alerts:
                            st.info("\n\n".join(alerts))

                        # Gráfico por categoría (del resumen a pagar)
                        df_stmt = df_tj_ext[(df_tj_ext["cuenta_id"] == card_id) &
                                            (df_tj_ext["fecha"] >= stmt_start) &
                                            (df_tj_ext["fecha"] <= stmt_end)].copy()

                        if not df_stmt.empty:
                            agg = df_stmt.groupby("categoria", as_index=False)["monto"].sum().sort_values("monto", ascending=False)
                            fig = px.bar(agg, x="categoria", y="monto")
                            fig.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0), xaxis_title=None, yaxis_title=None)
                            st.plotly_chart(fig, use_container_width=True)
                        else:
                            st.caption("Sin consumos en el último resumen (para pagar).")

                        # Detalles
                        with st.expander("Ver detalle"):
                            cA, cB, cC = st.columns(3)
                            cA.write("**Resumen (a pagar)**")
                            cA.caption(f"Periodo: {stmt_start.strftime('%d/%m')} → {stmt_end.strftime('%d/%m')}")
                            cA.metric("Total", fmt_ars(stmt_total))
                            cA.metric("Pagado", fmt_ars(pagos))
                            cA.metric("Pendiente", fmt_ars(saldo_pend))

                            cB.write("**En curso**")
                            cB.caption(f"Periodo: {open_start.strftime('%d/%m')} → {open_end.strftime('%d/%m')}")
                            cB.metric("Acumulado", fmt_ars(open_total))

                            cC.write("**Límites / mínimo**")
                            if uso_pct is not None:
                                cC.metric("Límite total", fmt_ars(limite_total))
                                cC.metric("Disponible (est.)", fmt_ars(max(float(limite_total) - (stmt_total + open_total), 0.0)))
                            cC.metric("Pago mínimo (est.)", fmt_ars(min_pay))

                            st.divider()
                            st.write("**Movimientos del resumen**")
                            if not df_stmt.empty:
                                st.dataframe(df_stmt[["fecha","descripcion","monto","categoria"]].sort_values("fecha"),
                                             use_container_width=True, hide_index=True)
                            else:
                                st.caption("Nada para mostrar.")

                            st.write("**Pagos aplicados (cierre → vto)**")
                            df_p = pd.DataFrame()
                            if not df_mov_ext.empty:
                                df_p = df_mov_ext[(df_mov_ext["tipo"] == "PAGO_TARJETA") &
                                                  (df_mov_ext["cuenta_destino_id"].astype(str) == card_id) &
                                                  (df_mov_ext["fecha"] >= cierre) &
                                                  (df_mov_ext["fecha"] <= vto)][["fecha","descripcion","monto","cuenta"]].copy()
                            if not df_p.empty:
                                st.dataframe(df_p.sort_values("fecha"), use_container_width=True, hide_index=True)
                            else:
                                st.caption("Sin pagos en el rango.")

            # ----------------- CONFIG
            with tab_config:
                st.caption("Configura cierre/vto + límites. (Guarda directo en tabla cuentas)")
                for _, r in df_cards.iterrows():
                    with st.container(border=True):
                        c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 1, 1])
                        c1.write(f"**{r['nombre']}**")

                        ci = c2.number_input("Cierre", 1, 31, int(r.get("dia_cierre") or 25), key=f"c{r['id']}")
                        vt = c3.number_input("Vto", 1, 31, int(r.get("dia_vencimiento") or 5), key=f"v{r['id']}")

                        lim = c4.number_input("Límite", min_value=0.0, value=float(r.get("limite_total") or 0.0), step=10000.0, key=f"l{r['id']}")
                        minpct = c5.number_input("Min %", min_value=0.0, max_value=1.0, value=float(r.get("pago_minimo_pct") or 0.10), step=0.01, key=f"mp{r['id']}")

                        c6, c7 = st.columns([1, 1])
                        minfix = c6.number_input("Pago mínimo fijo (opcional)", min_value=0.0, value=float(r.get("pago_minimo_fijo") or 0.0), step=1000.0, key=f"mf{r['id']}")
                        if c7.button("💾 Guardar", key=f"save{r['id']}"):
                            payload = {
                                "dia_cierre": int(ci),
                                "dia_vencimiento": int(vt),
                                "limite_total": float(lim) if lim > 0 else None,
                                "pago_minimo_pct": float(minpct),
                                "pago_minimo_fijo": float(minfix) if minfix > 0 else None,
                            }
                            supabase.table("cuentas").update(payload).eq("id", r["id"]).execute()
                            invalidate_caches()
                            st.toast("Actualizado")
                            time.sleep(0.3)
                            st.rerun()

# =========================================================
# 17) AJUSTES
# =========================================================
elif "Ajustes" in menu:
    st.markdown("### ⚙️ Ajustes")

    # sueldo base
    with st.container(border=True):
        st.write("Sueldo Base")
        ns = st.number_input("Neto", value=int(sueldo_base or 0), label_visibility="collapsed")
        if st.button("Actualizar"):
            supabase.table("configuracion").upsert({"clave": "sueldo_mensual", "valor": str(int(ns))}).execute()
            invalidate_caches()
            st.toast("Ok")
            time.sleep(0.3)
            st.rerun()

    # fijos
    st.markdown("#### Fijos")
    with st.form("add_sus"):
        c1, c2, c3 = st.columns([2, 1, 1])
        sd = c1.text_input("Desc")
        sm = c2.number_input("Monto", min_value=0.0)
        sc = c3.selectbox("Pago", df_cta["nombre"].tolist() if not df_cta.empty else [])
        if st.form_submit_button("Agregar"):
            sidc = df_cta[df_cta["nombre"] == sc]["id"].values[0]
            # por ahora asignamos categoría default
            sca = df_cat[df_cat["nombre"].eq("General")]["id"].values[0] if (not df_cat.empty and "General" in df_cat["nombre"].tolist()) else (df_cat.iloc[0]["id"] if not df_cat.empty else None)
            stipo = "COMPRA_TARJETA" if df_cta[df_cta["nombre"] == sc]["tipo"].values[0] == "CREDITO" else "GASTO"
            save_suscripcion(sd, sm, sidc, sca, stipo)
            st.rerun()

    df_s = get_suscripciones()
    if not df_s.empty:
        st.dataframe(df_s[["descripcion", "monto", "tipo"]], use_container_width=True, hide_index=True)
        ds = st.selectbox("Borrar:", ["..."] + df_s["descripcion"].astype(str).tolist())
        if st.button("Eliminar Fijo") and ds != "...":
            did = df_s[df_s["descripcion"] == ds]["id"].values[0]
            delete_suscripcion(did)
            st.rerun()
    else:
        st.caption("No hay fijos.")

