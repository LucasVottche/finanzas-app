import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
import plotly.express as px
import time

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Finanzas Pro", page_icon="💳", layout="wide")

# --- CONEXIÓN ---
@st.cache_resource
def init_connection():
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except: st.stop()

supabase = init_connection()

# --- FORMATOS ---
def fmt_ars(valor):
    if valor is None: valor = 0
    s = f"{valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    return f"${s[:-3]}" if s.endswith(",00") else f"${s}"

def calcular_vto_real(fecha_compra, dia_cierre, dia_vto):
    if isinstance(fecha_compra, str):
        fecha_compra = datetime.strptime(fecha_compra, "%Y-%m-%d").date()
    try: f_cierre = date(fecha_compra.year, fecha_compra.month, int(dia_cierre))
    except: f_cierre = date(fecha_compra.year, fecha_compra.month, 28)
    
    if fecha_compra <= f_cierre: resumen = fecha_compra + relativedelta(months=1)
    else: resumen = fecha_compra + relativedelta(months=2)
    
    try: return date(resumen.year, resumen.month, int(dia_vto))
    except: return date(resumen.year, resumen.month, 28)

# --- BASE DE DATOS ---
def get_maestros():
    cta = pd.DataFrame(supabase.table("cuentas").select("*").execute().data)
    cat = pd.DataFrame(supabase.table("categorias").select("*").execute().data)
    try: su = float(supabase.table("configuracion").select("valor").eq("clave", "sueldo_mensual").execute().data[0]['valor'])
    except: su = 0.0
    return cta, cat, su

def get_movimientos(desde, hasta):
    desde_ext = desde - relativedelta(months=4)
    resp = supabase.table("movimientos").select(
        "*, categorias(nombre, icono), cuentas:cuentas!cuenta_id(nombre, tipo, dia_cierre, dia_vencimiento)"
    ).gte("fecha", str(desde_ext)).lte("fecha", str(hasta)).order("fecha").execute()
    
    if not resp.data: return pd.DataFrame()
    data = []
    for d in resp.data:
        r = d.copy()
        r['categoria'] = f"{d['categorias']['icono']} {d['categorias']['nombre']}" if d.get('categorias') else "Sin Cat"
        r['cuenta'] = d['cuentas']['nombre'] if d.get('cuentas') else "Sin Cuenta"
        r['tipo_cta'] = d['cuentas']['tipo'] if d.get('cuentas') else "DEBITO"
        r['cierre'] = d['cuentas'].get('dia_cierre', 23) if d.get('cuentas') else 23
        r['vto'] = d['cuentas'].get('dia_vencimiento', 5) if d.get('cuentas') else 5
        del r['categorias'], r['cuentas']
        data.append(r)
    df = pd.DataFrame(data)
    df['fecha'] = pd.to_datetime(df['fecha']).dt.date
    return df

def db_save(fecha, monto, desc, cta_id, cat_id, tipo, dest_id=None):
    payload = {"fecha": str(fecha), "monto": monto, "descripcion": desc, "cuenta_id": cta_id, "categoria_id": cat_id, "tipo": tipo}
    if dest_id: payload["cuenta_destino_id"] = dest_id
    supabase.table("movimientos").insert(payload).execute()

def db_delete(id_mov):
    supabase.table("movimientos").delete().eq("id", id_mov).execute()

# --- CARGA ---
df_cta, df_cat, sueldo_base = get_maestros()

# --- SIDEBAR ---
with st.sidebar:
    st.title("Lucas Finanzas")
    menu = st.radio("Sección", ["📊 Dashboard", "📅 Planificador", "➕ Cargar", "📝 Historial", "💳 Tarjetas", "⚙️ Ajustes"])
    st.divider()
    mes_sel = st.selectbox("Mes", range(1, 13), index=date.today().month - 1)
    anio_sel = st.number_input("Año", value=date.today().year, step=1)
    f_ini = date(anio_sel, mes_sel, 1)
    f_fin = f_ini + relativedelta(months=1) - timedelta(days=1)

# --- 1. DASHBOARD ---
if menu == "📊 Dashboard":
    st.header(f"Resumen de {f_ini.strftime('%B %Y')}")
    df_raw = get_movimientos(f_ini, f_fin)
    
    if not df_raw.empty:
        df_mes = df_raw[(df_raw['fecha'] >= f_ini) & (df_raw['fecha'] <= f_fin)]
        
        # --- LÓGICA DE INGRESOS ---
        ingresos_registrados = df_mes[df_mes['tipo'] == 'INGRESO']['monto'].sum()
        total_ingresos = ingresos_registrados if ingresos_registrados > 0 else sueldo_base
        
        # --- GASTOS ---
        gastos_cash = df_mes[df_mes['tipo'] == 'GASTO']['monto'].sum()
        consumos_tj_mes = df_mes[df_mes['tipo'] == 'COMPRA_TARJETA']['monto'].sum()
        
        # --- VENCIMIENTOS TARJETA ---
        df_tj = df_raw[df_raw['tipo'] == 'COMPRA_TARJETA'].copy()
        vence_ahora = 0
        if not df_tj.empty:
            df_tj['fecha_vto'] = df_tj.apply(lambda x: calcular_vto_real(x['fecha'], x['cierre'], x['vto']), axis=1)
            vence_ahora_df = df_tj[(df_tj['fecha_vto'] >= f_ini) & (df_tj['fecha_vto'] <= f_fin)]
            vence_ahora = vence_ahora_df['monto'].sum()

        disponible = total_ingresos - gastos_cash - vence_ahora

        c1, c2, c3 = st.columns(3)
        with c1:
            with st.container(border=True):
                st.metric("✅ Disponible (Caja)", fmt_ars(disponible))
                st.caption(f"Ingresos: {fmt_ars(total_ingresos)}")
        with c2:
            with st.container(border=True):
                st.metric("💳 Vencen este mes", fmt_ars(vence_ahora))
        with c3:
            with st.container(border=True):
                st.metric("🛒 Consumo Total", fmt_ars(gastos_cash + consumos_tj_mes))

        st.divider()
        col_g1, col_g2 = st.columns([2, 1])
        with col_g1:
            st.subheader("Flujo")
            if not df_mes.empty:
                fig = px.bar(df_mes[df_mes['tipo'] != 'INGRESO'], x='fecha', y='monto', color='categoria')
                st.plotly_chart(fig, use_container_width=True)
        with col_g2:
            st.subheader("Rubros")
            if not df_mes.empty:
                fig_p = px.pie(df_mes[df_mes['tipo'].isin(['GASTO', 'COMPRA_TARJETA'])], values='monto', names='categoria', hole=0.5)
                st.plotly_chart(fig_p, use_container_width=True)
    else:
        st.info("No hay datos.")

# --- 2. PLANIFICADOR ---
elif menu == "📅 Planificador":
    st.title(f"Planear {f_ini.strftime('%B %Y')}")
    with st.container(border=True):
        ing = st.number_input("Sueldo Neto estimado", value=int(sueldo_base), step=1000)
        if 'plan_df' not in st.session_state:
            st.session_state.plan_df = pd.DataFrame([{"Descripción": "Gasto fijo", "Monto": 0.0, "Categoría": df_cat['nombre'].tolist()[0], "Pago": df_cta['nombre'].tolist()[0]}])
        
        ed = st.data_editor(st.session_state.plan_df, num_rows="dynamic", use_container_width=True,
            column_config={
                "Categoría": st.column_config.SelectboxColumn(options=df_cat['nombre'].tolist()),
                "Pago": st.column_config.SelectboxColumn(options=df_cta['nombre'].tolist())
            })
        
        if st.button("Guardar Planificación", type="primary", use_container_width=True):
            id_mp = df_cta[df_cta['nombre'] == "Mercado Pago"]['id'].values[0]
            db_save(f_ini, ing, "Sueldo Planificado", id_mp, df_cat.iloc[0]['id'], "INGRESO")
            for _, r in ed.iterrows():
                if r['Monto'] > 0:
                    c_id = df_cta[df_cta['nombre'] == r['Pago']]['id'].values[0]
                    tp = "COMPRA_TARJETA" if df_cta[df_cta['nombre'] == r['Pago']]['tipo'].values[0] == 'CREDITO' else "GASTO"
                    db_save(f_ini + timedelta(days=4), r['Monto'], r['Descripción'], c_id, df_cat[df_cat['nombre'] == r['Categoría']]['id'].values[0], tp)
            st.success("Plan guardado!"); time.sleep(1); st.rerun()

# --- 3. CARGAR (MANUAL) ---
elif menu == "➕ Cargar":
    st.title("Nueva Operación Manual")
    tipo_op = st.radio("Tipo", ["Gasto", "Ingreso", "Pagar Tarjeta"], horizontal=True)
    
    with st.container(border=True):
        with st.form("f_manual"):
            col1, col2 = st.columns(2)
            f = col1.date_input("Fecha", date.today())
            m = col2.number_input("Monto", min_value=0.0, step=100.0)
            d = st.text_input("Descripción")
            
            c3, c4 = st.columns(2)
            cta_n = c3.selectbox("Cuenta", df_cta['nombre'].tolist())
            cat_n = c4.selectbox("Categoría", df_cat['nombre'].tolist())
            
            if st.form_submit_button("Guardar Movimiento", use_container_width=True):
                id_c = df_cta[df_cta['nombre'] == cta_n]['id'].values[0]
                id_ct = df_cat[df_cat['nombre'] == cat_n]['id'].values[0]
                tp = "INGRESO" if tipo_op == "Ingreso" else ("COMPRA_TARJETA" if df_cta[df_cta['nombre'] == cta_n]['tipo'].values[0] == 'CREDITO' else "GASTO")
                db_save(f, m, d, id_c, id_ct, tp)
                st.success("¡Guardado!"); time.sleep(1); st.rerun()

# --- 4. TARJETAS (NUEVO / REPARADO) ---
elif menu == "💳 Tarjetas":
    st.title("Gestión de Crédito")
    tab1, tab2 = st.tabs(["⚙️ Configurar Fechas", "📥 Importar Resumen"])
    
    with tab1:
        df_crd = df_cta[df_cta['tipo'] == 'CREDITO']
        if df_crd.empty: st.info("No hay tarjetas de crédito.")
        for _, r in df_crd.iterrows():
            with st.container(border=True):
                ca, cb, cc, cd = st.columns([2,1,1,1])
                ca.write(f"### {r['nombre']}")
                ci = cb.number_input("Cierre", 1, 31, int(r.get('dia_cierre') or 23), key=f"ci_{r['id']}")
                vt = cc.number_input("Vto", 1, 31, int(r.get('dia_vencimiento') or 5), key=f"vt_{r['id']}")
                if cd.button("Guardar", key=f"btn_{r['id']}", use_container_width=True):
                    supabase.table("cuentas").update({"dia_cierre": ci, "dia_vencimiento": vt}).eq("id", r['id']).execute()
                    st.success("Actualizado"); time.sleep(1); st.rerun()
    
    with tab2:
        st.caption("Subí el resumen del banco para cargar consumos automáticamente.")
        up = st.file_uploader("Archivo CSV o Excel", type=['csv', 'xlsx'])
        if up:
            df_up = pd.read_csv(up) if up.name.endswith('.csv') else pd.read_excel(up)
            st.dataframe(df_up.head(3), use_container_width=True)
            with st.form("f_import"):
                sel = st.selectbox("Asignar a:", df_cta[df_cta['tipo'] == 'CREDITO']['nombre'].tolist())
                c1, c2, c3 = st.columns(3)
                f_c = c1.selectbox("Col. Fecha", df_up.columns)
                d_c = c2.selectbox("Col. Desc", df_up.columns)
                m_c = c3.selectbox("Col. Monto", df_up.columns)
                if st.form_submit_button("Importar Todo", use_container_width=True):
                    id_tj = df_cta[df_cta['nombre'] == sel]['id'].values[0]
                    for _, row in df_up.iterrows():
                        try:
                            fecha_p = pd.to_datetime(row[f_c], dayfirst=True).date()
                            monto_p = abs(float(str(row[m_c]).replace('$','').replace('.','').replace(',','.')))
                            db_save(fecha_p, monto_p, str(row[d_c]), id_tj, df_cat.iloc[0]['id'], "COMPRA_TARJETA")
                        except: pass
                    st.success("¡Importación Exitosa!"); time.sleep(1); st.rerun()

# --- 5. HISTORIAL ---
elif menu == "📝 Historial":
    st.title("Historial y Edición")
    df_h = get_movimientos(f_ini, f_fin)
    if not df_h.empty:
        df_h = df_h[(df_h['fecha'] >= f_ini) & (df_h['fecha'] <= f_fin)]
        # Agregamos opción de borrar
        sel_del = st.selectbox("Borrar un movimiento (Selecciona descripción)", ["Seleccionar..."] + df_h['descripcion'].tolist())
        if sel_del != "Seleccionar...":
            id_del = df_h[df_h['descripcion'] == sel_del]['id'].values[0]
            if st.button("Eliminar Permanentemente", type="primary"):
                db_delete(id_del)
                st.success("Borrado."); time.sleep(1); st.rerun()
        
        st.data_editor(df_h[['id', 'fecha', 'descripcion', 'monto', 'cuenta', 'categoria', 'tipo']], use_container_width=True, hide_index=True)
    else:
        st.info("Sin datos.")

# --- 6. AJUSTES ---
elif menu == "⚙️ Ajustes":
    st.header("Configuración")
    n_s = st.number_input("Sueldo Base (Ajustes)", value=int(sueldo_base))
    if st.button("Actualizar Sueldo"):
        supabase.table("configuracion").upsert({"clave": "sueldo_mensual", "valor": str(n_s)}).execute()
        st.success("Ok!"); time.sleep(1); st.rerun()