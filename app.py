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
    
    # Cierre del mes de la compra
    f_cierre = date(fecha_compra.year, fecha_compra.month, int(dia_cierre))
    
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
    # Traemos un margen más amplio para calcular vencimientos de tarjeta
    desde_ext = desde - relativedelta(months=3)
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
    st.title("Lucas Finanzas")
    menu = st.radio("Sección", ["📊 Dashboard", "💳 Tarjetas", "📅 Planificador", "➕ Cargar Manual", "📝 Historial", "⚙️ Ajustes"])
    st.divider()
    mes_sel = st.selectbox("Mes Visualizado", range(1, 13), index=date.today().month - 1)
    anio_sel = st.number_input("Año", value=date.today().year, step=1)
    f_ini = date(anio_sel, mes_sel, 1)
    f_fin = f_ini + relativedelta(months=1) - timedelta(days=1)

# --- 1. DASHBOARD ---
if menu == "📊 Dashboard":
    st.title(f"Balance de {f_ini.strftime('%B %Y')}")
    df_raw = get_movimientos(f_fin)
    
    if not df_raw.empty:
        # Gastos y Sueldos DENTRO del mes (No tarjetas)
        df_mes = df_raw[(df_raw['fecha'] >= f_ini) & (df_raw['fecha'] <= f_fin)]
        ingresos = df_mes[df_mes['tipo'] == 'INGRESO']['monto'].sum()
        gastos_cash = df_mes[df_mes['tipo'] == 'GASTO']['monto'].sum()
        pagos_tj = df_mes[df_mes['tipo'] == 'PAGO_TARJETA']['monto'].sum()

        # Vencimientos de Tarjeta que caen en este mes
        df_tj = df_raw[df_raw['tipo'] == 'COMPRA_TARJETA'].copy()
        vence_mes = 0
        lista_tj = []
        if not df_tj.empty:
            df_tj['fecha_vto'] = df_tj.apply(lambda x: calcular_vto_real(x['fecha'], x['cierre'], x['vto']), axis=1)
            vence_ahora = df_tj[(df_tj['fecha_vto'] >= f_ini) & (df_tj['fecha_vto'] <= f_fin)]
            vence_mes = vence_ahora['monto'].sum()
            if not vence_ahora.empty:
                for c, m in vence_ahora.groupby('cuenta')['monto'].sum().items():
                    lista_tj.append(f"{c}: {fmt_ars(m)}")

        disponible = (sueldo_base + ingresos) - gastos_cash - vence_mes

        c1, c2, c3 = st.columns(3)
        c1.metric("💰 Disponible Real", fmt_ars(disponible), help="Neto - Gastos Cash - Tarjetas que vencen")
        c2.metric("💳 Vencen este mes", fmt_ars(vence_mes))
        for t in lista_tj: c2.caption(t)
        c3.metric("💸 Gastos Cash", fmt_ars(gastos_cash))

        st.divider()
        if not df_mes.empty:
            st.subheader("Distribución de Gastos")
            df_pie = df_mes[df_mes['tipo'].isin(['GASTO', 'COMPRA_TARJETA'])]
            if not df_pie.empty:
                fig = px.pie(df_pie, values='monto', names='categoria', hole=0.4)
                st.plotly_chart(fig, width='stretch')
    else:
        st.info("No hay datos para este mes.")

# --- 2. TARJETAS ---
elif menu == "💳 Tarjetas":
    st.title("Gestión de Resúmenes")
    tab1, tab2 = st.tabs(["⚙️ Configurar Fechas", "📥 Importar Excel"])
    
    with tab1:
        df_crd = df_cta[df_cta['tipo'] == 'CREDITO']
        for _, r in df_crd.iterrows():
            with st.container(border=True):
                col_a, col_b, col_c, col_d = st.columns([2,1,1,1])
                col_a.write(f"**{r['nombre']}**")
                cierre = col_b.number_input(f"Cierre", 1, 31, int(r.get('dia_cierre') or 23), key=f"ci_{r['id']}")
                vto = col_c.number_input(f"Vto", 1, 31, int(r.get('dia_vencimiento') or 5), key=f"vt_{r['id']}")
                if col_d.button("Guardar", key=f"btn_{r['id']}"):
                    supabase.table("cuentas").update({"dia_cierre": cierre, "dia_vencimiento": vto}).eq("id", r['id']).execute()
                    st.success("Guardado"); time.sleep(1); st.rerun()

    with tab2:
        up = st.file_uploader("Subí el Excel/CSV del banco", type=['csv', 'xlsx'])
        if up:
            df_up = pd.read_csv(up) if up.name.endswith('.csv') else pd.read_excel(up)
            st.dataframe(df_up.head(5), width='stretch')
            with st.form("f_import"):
                sel_tj = st.selectbox("Asignar a:", df_cta[df_cta['tipo'] == 'CREDITO']['nombre'].tolist())
                c1, c2, c3 = st.columns(3)
                f_col = c1.selectbox("Col. Fecha", df_up.columns)
                d_col = c2.selectbox("Col. Desc", df_up.columns)
                m_col = c3.selectbox("Col. Monto", df_up.columns)
                if st.form_submit_button("Importar Gastos"):
                    id_tj = df_cta[df_cta['nombre'] == sel_tj]['id'].values[0]
                    cat_id = df_cat.iloc[0]['id']
                    count = 0
                    for _, row in df_up.iterrows():
                        try:
                            f = pd.to_datetime(row[f_col], dayfirst=True).date()
                            m = abs(float(str(row[m_col]).replace('$','').replace('.','').replace(',','.')))
                            db_save(f, m, str(row[d_col]), id_tj, cat_id, "COMPRA_TARJETA")
                            count += 1
                        except: pass
                    st.success(f"Importados {count} gastos."); time.sleep(2); st.rerun()

# --- 3. PLANIFICADOR ---
elif menu == "📅 Planificador":
    st.title(f"Planear {f_ini.strftime('%B %Y')}")
    ing = st.number_input("Sueldo Neto estimado", value=int(sueldo_base), step=1000)
    
    if 'plan_df' not in st.session_state:
        st.session_state.plan_df = pd.DataFrame([{"Descripción": "Gasto fijo", "Monto": 0.0, "Categoría": df_cat['nombre'].tolist()[0], "Pago": df_cta['nombre'].tolist()[0]}])
    
    ed = st.data_editor(st.session_state.plan_df, num_rows="dynamic", width='stretch',
        column_config={
            "Categoría": st.column_config.SelectboxColumn(options=df_cat['nombre'].tolist()),
            "Pago": st.column_config.SelectboxColumn(options=df_cta['nombre'].tolist())
        })
    
    if st.button("Guardar Planificación en Base de Datos", type="primary"):
        # Ingreso
        id_mp = df_cta[df_cta['nombre'] == "Mercado Pago"]['id'].values[0] # Default
        db_save(f_ini, ing, "Sueldo Planificado", id_mp, df_cat.iloc[0]['id'], "INGRESO")
        # Gastos
        for _, r in ed.iterrows():
            if r['Monto'] > 0:
                c_id = df_cta[df_cta['nombre'] == r['Pago']]['id'].values[0]
                ct_id = df_cat[df_cat['nombre'] == r['Categoría']]['id'].values[0]
                t = "COMPRA_TARJETA" if df_cta[df_cta['nombre'] == r['Pago']]['tipo'].values[0] == 'CREDITO' else "GASTO"
                db_save(f_ini + timedelta(days=5), r['Monto'], r['Descripción'], c_id, ct_id, t)
        st.success("Plan guardado!"); time.sleep(2); st.rerun()

# --- 4. CARGAR MANUAL ---
elif menu == "➕ Cargar Manual":
    st.title("Nueva Operación")
    tipo = st.radio("Tipo", ["Gasto", "Ingreso", "Pagar Tarjeta"], horizontal=True)
    with st.form("f_manual"):
        f = st.date_input("Fecha", date.today())
        m = st.number_input("Monto", min_value=0.0)
        d = st.text_input("Descripción")
        cta = st.selectbox("Cuenta", df_cta['nombre'].tolist())
        cat = st.selectbox("Categoría", df_cat['nombre'].tolist())
        if st.form_submit_button("Guardar"):
            id_c = df_cta[df_cta['nombre'] == cta]['id'].values[0]
            id_cat = df_cat[df_cat['nombre'] == cat]['id'].values[0]
            tp = "GASTO"
            if tipo == "Ingreso": tp = "INGRESO"
            elif df_cta[df_cta['nombre'] == cta]['tipo'].values[0] == 'CREDITO': tp = "COMPRA_TARJETA"
            
            db_save(f, m, d, id_c, id_cat, tp)
            st.success("Guardado"); time.sleep(1); st.rerun()

# --- 5. HISTORIAL ---
elif menu == "📝 Historial":
    st.title("Movimientos")
    df = get_movimientos(f_fin)
    if not df.empty:
        df_hist = df[(df['fecha'] >= f_ini) & (df['fecha'] <= f_fin)][['id', 'fecha', 'descripcion', 'monto', 'cuenta', 'categoria', 'tipo']]
        st.data_editor(df_hist, width='stretch', hide_index=True, disabled=['id'])

# --- 6. AJUSTES ---
elif menu == "⚙️ Ajustes":
    st.title("Configuración")
    n_s = st.number_input("Sueldo Base Mensual", value=int(sueldo_base))
    if st.button("Actualizar Sueldo"):
        supabase.table("configuracion").upsert({"clave": "sueldo_mensual", "valor": str(n_s)}).execute()
        st.success("Actualizado"); time.sleep(1); st.rerun()