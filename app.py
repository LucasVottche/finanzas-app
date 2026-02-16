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
    except Exception as e:
        st.error(f"Error de conexión: {e}")
        st.stop()

supabase = init_connection()

# --- FORMATOS 🇦🇷 ---
def fmt_ars(valor):
    if valor is None: valor = 0
    s = f"{valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    return f"${s[:-3]}" if s.endswith(",00") else f"${s}"

# --- LÓGICA DE VENCIMIENTOS ---
def calcular_vto_real(fecha_compra, dia_cierre, dia_vto):
    if isinstance(fecha_compra, str):
        fecha_compra = datetime.strptime(fecha_compra, "%Y-%m-%d").date()
    try:
        f_cierre = date(fecha_compra.year, fecha_compra.month, int(dia_cierre))
    except:
        f_cierre = date(fecha_compra.year, fecha_compra.month, 28)
    
    if fecha_compra <= f_cierre:
        resumen = fecha_compra + relativedelta(months=1)
    else:
        resumen = fecha_compra + relativedelta(months=2)
    
    try:
        return date(resumen.year, resumen.month, int(dia_vto))
    except:
        return date(resumen.year, resumen.month, 28)

# --- BASE DE DATOS ---
def get_maestros():
    cta = pd.DataFrame(supabase.table("cuentas").select("*").execute().data)
    cat = pd.DataFrame(supabase.table("categorias").select("*").execute().data)
    try:
        su = float(supabase.table("configuracion").select("valor").eq("clave", "sueldo_mensual").execute().data[0]['valor'])
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

# --- CARGA ---
df_cta, df_cat, sueldo_base = get_maestros()

# --- SIDEBAR ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2382/2382461.png", width=50)
    st.title("Lucas Finanzas")
    menu = st.radio("Sección", ["📊 Dashboard", "💳 Tarjetas", "📅 Planificador", "➕ Cargar Manual", "📝 Historial", "⚙️ Ajustes"])
    st.divider()
    mes_sel = st.selectbox("Mes Visualizado", range(1, 13), index=date.today().month - 1)
    anio_sel = st.number_input("Año", value=date.today().year, step=1)
    f_ini = date(anio_sel, mes_sel, 1)
    f_fin = f_ini + relativedelta(months=1) - timedelta(days=1)

# --- 1. DASHBOARD ---
if menu == "📊 Dashboard":
    st.header(f"Resumen de {f_ini.strftime('%B %Y')}")
    df_raw = get_movimientos(f_ini, f_fin)
    
    # Cálculos comparativos (vs mes anterior)
    f_prev_ini = f_ini - relativedelta(months=1)
    f_prev_fin = f_ini - timedelta(days=1)
    
    if not df_raw.empty:
        df_mes = df_raw[(df_raw['fecha'] >= f_ini) & (df_raw['fecha'] <= f_fin)]
        df_prev = df_raw[(df_raw['fecha'] >= f_prev_ini) & (df_raw['fecha'] <= f_prev_fin)]
        
        ingresos = df_mes[df_mes['tipo'] == 'INGRESO']['monto'].sum()
        gastos_cash = df_mes[df_mes['tipo'] == 'GASTO']['monto'].sum()
        gastos_prev = df_prev[df_prev['tipo'] == 'GASTO']['monto'].sum() if not df_prev.empty else 0
        
        # Tarjetas
        df_tj = df_raw[df_raw['tipo'] == 'COMPRA_TARJETA'].copy()
        vence_mes = 0
        lista_tj = []
        if not df_tj.empty:
            df_tj['fecha_vto'] = df_tj.apply(lambda x: calcular_vto_real(x['fecha'], x['cierre'], x['vto']), axis=1)
            vence_ahora = df_tj[(df_tj['fecha_vto'] >= f_ini) & (df_tj['fecha_vto'] <= f_fin)]
            vence_mes = vence_ahora['monto'].sum()
            for c, m in vence_ahora.groupby('cuenta')['monto'].sum().items():
                lista_tj.append(f"{c}: {fmt_ars(m)}")

        disponible = (sueldo_base + ingresos) - gastos_cash - vence_mes
        delta_gastos = ((gastos_cash - gastos_prev) / gastos_prev * 100) if gastos_prev > 0 else 0

        # --- UX: METRICAS EN TARJETAS ---
        c1, c2, c3 = st.columns(3)
        with c1:
            with st.container(border=True):
                st.metric("✅ Disponible Real", fmt_ars(disponible), help="Lo que queda tras gastos y tarjetas")
                st.caption(f"Ingresos: {fmt_ars(sueldo_base + ingresos)}")
        with c2:
            with st.container(border=True):
                st.metric("💳 Vencen este mes", fmt_ars(vence_mes))
                for t in lista_tj: st.caption(f"• {t}")
        with c3:
            with st.container(border=True):
                st.metric("💸 Gastos Cash", fmt_ars(gastos_cash), 
                          delta=f"{delta_gastos:.1f}% vs anterior" if gastos_prev > 0 else None, 
                          delta_color="inverse")

        st.divider()
        
        # --- UX: GRÁFICOS ---
        col_g1, col_g2 = st.columns([2, 1])
        with col_g1:
            st.subheader("Flujo Diario")
            df_bar = df_mes[df_mes['tipo'].isin(['GASTO', 'PAGO_TARJETA'])]
            if not df_bar.empty:
                fig_bar = px.bar(df_bar.groupby('fecha')['monto'].sum().reset_index(), 
                                 x='fecha', y='monto', color_discrete_sequence=['#FF4B4B'])
                fig_bar.update_layout(xaxis_title=None, yaxis_title=None, height=300, margin=dict(l=0,r=0,b=0,t=0))
                st.plotly_chart(fig_bar, use_container_width=True)
        
        with col_g2:
            st.subheader("Categorías")
            df_pie = df_mes[df_mes['tipo'].isin(['GASTO', 'COMPRA_TARJETA'])]
            if not df_pie.empty:
                fig_pie = px.pie(df_pie, values='monto', names='categoria', hole=0.5)
                fig_pie.update_layout(showlegend=False, height=300, margin=dict(l=0,r=0,b=0,t=0))
                st.plotly_chart(fig_pie, use_container_width=True)
    else:
        st.info("No hay datos cargados para este mes. Podés usar el 'Planificador' para proyectar.")

# --- 2. TARJETAS (UX RECORRIDA) ---
elif menu == "💳 Tarjetas":
    st.title("Gestión de Resúmenes")
    t1, t2 = st.tabs(["⚙️ Configurar Fechas", "📥 Importar Excel"])
    with t1:
        df_crd = df_cta[df_cta['tipo'] == 'CREDITO']
        for _, r in df_crd.iterrows():
            with st.container(border=True):
                ca, cb, cc, cd = st.columns([2,1,1,1])
                ca.write(f"### {r['nombre']}")
                ci = cb.number_input("Cierre", 1, 31, int(r.get('dia_cierre') or 23), key=f"ci_{r['id']}")
                vt = cc.number_input("Vto", 1, 31, int(r.get('dia_vencimiento') or 5), key=f"vt_{r['id']}")
                if cd.button("Guardar", key=f"btn_{r['id']}", use_container_width=True):
                    supabase.table("cuentas").update({"dia_cierre": ci, "dia_vencimiento": vt}).eq("id", r['id']).execute()
                    st.success("Ok"); time.sleep(1); st.rerun()
    with t2:
        up = st.file_uploader("Subí el resumen del banco", type=['csv', 'xlsx'])
        if up:
            df_up = pd.read_csv(up) if up.name.endswith('.csv') else pd.read_excel(up)
            st.dataframe(df_up.head(3), use_container_width=True)
            with st.form("import"):
                sel = st.selectbox("Asignar a:", df_cta[df_cta['tipo'] == 'CREDITO']['nombre'].tolist())
                c1, c2, c3 = st.columns(3)
                f_c = c1.selectbox("Col. Fecha", df_up.columns); d_c = c2.selectbox("Col. Desc", df_up.columns); m_c = c3.selectbox("Col. Monto", df_up.columns)
                if st.form_submit_button("Importar", use_container_width=True):
                    id_tj = df_cta[df_cta['nombre'] == sel]['id'].values[0]
                    for _, row in df_up.iterrows():
                        try:
                            f = pd.to_datetime(row[f_c], dayfirst=True).date()
                            m = abs(float(str(row[m_c]).replace('$','').replace('.','').replace(',','.')))
                            db_save(f, m, str(row[d_c]), id_tj, df_cat.iloc[0]['id'], "COMPRA_TARJETA")
                        except: pass
                    st.success("Importado"); time.sleep(1); st.rerun()

# --- 3. PLANIFICADOR (UX RECORRIDA) ---
elif menu == "📅 Planificador":
    st.title(f"Planear {f_ini.strftime('%B %Y')}")
    with st.container(border=True):
        ing = st.number_input("Sueldo Neto estimado", value=int(sueldo_base), step=1000)
        if 'plan_df' not in st.session_state:
            st.session_state.plan_df = pd.DataFrame([{"Descripción": "Gasto fijo", "Monto": 0.0, "Categoría": df_cat['nombre'].tolist()[0], "Pago": df_cta['nombre'].tolist()[0]}])
        ed = st.data_editor(st.session_state.plan_df, num_rows="dynamic", use_container_width=True,
            column_config={"Categoría": st.column_config.SelectboxColumn(options=df_cat['nombre'].tolist()),
                           "Pago": st.column_config.SelectboxColumn(options=df_cta['nombre'].tolist())})
        if st.button("Guardar Planificación", type="primary", use_container_width=True):
            id_mp = df_cta[df_cta['nombre'] == "Mercado Pago"]['id'].values[0]
            db_save(f_ini, ing, "Sueldo Planificado", id_mp, df_cat.iloc[0]['id'], "INGRESO")
            for _, r in ed.iterrows():
                if r['Monto'] > 0:
                    c_id = df_cta[df_cta['nombre'] == r['Pago']]['id'].values[0]
                    tp = "COMPRA_TARJETA" if df_cta[df_cta['nombre'] == r['Pago']]['tipo'].values[0] == 'CREDITO' else "GASTO"
                    db_save(f_ini + timedelta(days=5), r['Monto'], r['Descripción'], c_id, df_cat[df_cat['nombre'] == r['Categoría']]['id'].values[0], tp)
            st.success("Plan guardado!"); time.sleep(1); st.rerun()

# --- 4. CARGAR MANUAL (UX RECORRIDA) ---
elif menu == "➕ Cargar Manual":
    st.title("Nueva Operación")
    tipo = st.radio("Tipo", ["Gasto", "Ingreso", "Pagar Tarjeta"], horizontal=True)
    with st.container(border=True):
        with st.form("f_man"):
            f = st.date_input("Fecha", date.today())
            m = st.number_input("Monto", min_value=0.0); d = st.text_input("Descripción")
            cta = st.selectbox("Cuenta", df_cta['nombre'].tolist()); cat = st.selectbox("Categoría", df_cat['nombre'].tolist())
            if st.form_submit_button("Guardar", use_container_width=True):
                id_c = df_cta[df_cta['nombre'] == cta]['id'].values[0]
                tp = "GASTO"
                if tipo == "Ingreso": tp = "INGRESO"
                elif df_cta[df_cta['nombre'] == cta]['tipo'].values[0] == 'CREDITO': tp = "COMPRA_TARJETA"
                db_save(f, m, d, id_c, df_cat[df_cat['nombre'] == cat]['id'].values[0], tp)
                st.success("Guardado"); time.sleep(1); st.rerun()

# --- 5. HISTORIAL ---
elif menu == "📝 Historial":
    st.title("Movimientos")
    df = get_movimientos(f_ini, f_fin)
    if not df.empty:
        df_h = df[(df['fecha'] >= f_ini) & (df['fecha'] <= f_fin)][['id', 'fecha', 'descripcion', 'monto', 'cuenta', 'categoria', 'tipo']]
        st.data_editor(df_h, use_container_width=True, hide_index=True, disabled=['id'])

# --- 6. AJUSTES ---
elif menu == "⚙️ Ajustes":
    st.title("Configuración")
    with st.container(border=True):
        n_s = st.number_input("Sueldo Base Mensual", value=int(sueldo_base))
        if st.button("Actualizar Sueldo", use_container_width=True):
            supabase.table("configuracion").upsert({"clave": "sueldo_mensual", "valor": str(n_s)}).execute()
            st.success("Ok"); time.sleep(1); st.rerun()