import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
import plotly.express as px
import time

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Finanzas Pro", page_icon="💰", layout="wide")

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
    return f"$ {s[:-3]}" if s.endswith(",00") else f"$ {s}"

def calcular_vto_real(fecha_compra, dia_cierre, dia_vto):
    if isinstance(fecha_compra, str):
        try: fecha_compra = datetime.strptime(fecha_compra, "%Y-%m-%d").date()
        except: return date.today()
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
    desde_ext = desde - relativedelta(months=5)
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
    st.header(f"Balance Mensual: {f_ini.strftime('%B %Y')}")
    df_raw = get_movimientos(f_ini, f_fin)
    
    if not df_raw.empty:
        df_mes = df_raw[(df_raw['fecha'] >= f_ini) & (df_raw['fecha'] <= f_fin)]
        
        # INGRESOS: Sueldo Base + lo que cargues como INGRESO manual
        ing_adicionales = df_mes[df_mes['tipo'] == 'INGRESO']['monto'].sum()
        total_ingresos = sueldo_base + ing_adicionales
        
        # CONSUMO REAL (Gasto Cash + Compras Tarjeta del mes)
        gastos_cash = df_mes[df_mes['tipo'] == 'GASTO']['monto'].sum()
        gastos_tarjeta = df_mes[df_mes['tipo'] == 'COMPRA_TARJETA']['monto'].sum()
        total_consumo = gastos_cash + gastos_tarjeta
        
        resultado_neto = total_ingresos - total_consumo

        # VENCIMIENTOS TARJETA (Consumos anteriores que se pagan hoy)
        df_tj = df_raw[df_raw['tipo'] == 'COMPRA_TARJETA'].copy()
        vence_ahora = 0
        if not df_tj.empty:
            df_tj['fecha_vto'] = df_tj.apply(lambda x: calcular_vto_real(x['fecha'], x['cierre'], x['vto']), axis=1)
            vence_ahora = df_tj[(df_tj['fecha_vto'] >= f_ini) & (df_tj['fecha_vto'] <= f_fin)]['monto'].sum()

        c1, c2, c3 = st.columns(3)
        with c1:
            with st.container(border=True):
                st.metric("💰 Resultado Neto", fmt_ars(resultado_neto), help="Sueldo Base - Todo lo gastado este mes")
                st.caption(f"Ingresos Totales: {fmt_ars(total_ingresos)}")
        with c2:
            with st.container(border=True):
                st.metric("📉 Consumo Total", fmt_ars(total_consumo))
                st.caption(f"Tarjeta: {fmt_ars(gastos_tarjeta)} | Cash: {fmt_ars(gastos_cash)}")
        with c3:
            with st.container(border=True):
                st.metric("💳 Vence este mes", fmt_ars(vence_ahora), help="Monto del resumen a pagar")

        st.divider()
        col_g1, col_g2 = st.columns([2, 1])
        with col_g1:
            fig = px.bar(df_mes[df_mes['tipo'] != 'INGRESO'], x='fecha', y='monto', color='categoria', title="Flujo de Gastos")
            st.plotly_chart(fig, use_container_width=True)
        with col_g2:
            fig_p = px.pie(df_mes[df_mes['tipo'].isin(['GASTO', 'COMPRA_TARJETA'])], values='monto', names='categoria', hole=0.5, title="Rubros")
            st.plotly_chart(fig_p, use_container_width=True)
    else:
        st.info("Sin datos para este mes. El sueldo base configurado es: " + fmt_ars(sueldo_base))

# --- 2. PLANIFICADOR (SIN SUELDO DUPLICADO) ---
elif menu == "📅 Planificador":
    st.title(f"Proyectar Gastos: {f_ini.strftime('%B %Y')}")
    st.info(f"💡 El sueldo base de **{fmt_ars(sueldo_base)}** ya está contemplado. Cargá aquí tus gastos fijos.")
    
    with st.container(border=True):
        if 'plan_df' not in st.session_state:
            st.session_state.plan_df = pd.DataFrame([{"Descripción": "Alquiler", "Monto": 0.0, "Categoría": df_cat['nombre'].tolist()[0], "Pago": df_cta['nombre'].tolist()[0]}])
        
        ed = st.data_editor(st.session_state.plan_df, num_rows="dynamic", use_container_width=True,
            column_config={
                "Categoría": st.column_config.SelectboxColumn(options=df_cat['nombre'].tolist()),
                "Pago": st.column_config.SelectboxColumn(options=df_cta['nombre'].tolist())
            })
        
        total_plan = ed['Monto'].sum()
        st.write(f"**Total gastos planificados:** {fmt_ars(total_plan)}")
        st.write(f"**Saldo remanente estimado:** {fmt_ars(sueldo_base - total_plan)}")
        
        if st.button("Guardar Gastos Planificados", type="primary", use_container_width=True):
            count = 0
            for _, r in ed.iterrows():
                if r['Monto'] > 0:
                    c_id = df_cta[df_cta['nombre'] == r['Pago']]['id'].values[0]
                    tp = "COMPRA_TARJETA" if df_cta[df_cta['nombre'] == r['Pago']]['tipo'].values[0] == 'CREDITO' else "GASTO"
                    db_save(f_ini + timedelta(days=4), r['Monto'], r['Descripción'], c_id, df_cat[df_cat['nombre'] == r['Categoría']]['id'].values[0], tp)
                    count += 1
            st.success(f"¡{count} gastos guardados correctamente!"); time.sleep(1); st.rerun()

# --- 3. CARGAR ---
elif menu == "➕ Cargar":
    st.title("Nueva Operación")
    tipo_op = st.radio("Tipo", ["Gasto", "Ingreso", "Pagar Tarjeta"], horizontal=True)
    with st.container(border=True):
        with st.form("f_manual"):
            col1, col2 = st.columns(2)
            f = col1.date_input("Fecha", date.today())
            m = col2.number_input("Monto", min_value=0.0, step=100.0)
            d = st.text_input("Descripción")
            c3, c4 = st.columns(2)
            if tipo_op != "Pagar Tarjeta":
                cta_n = c3.selectbox("Cuenta/Tarjeta", df_cta['nombre'].tolist())
                cat_n = c4.selectbox("Categoría", df_cat['nombre'].tolist())
            else:
                cta_n = c3.selectbox("Desde (Banco)", df_cta[df_cta['tipo'] != 'CREDITO']['nombre'].tolist())
                cta_dest = c4.selectbox("Tarjeta Pagada", df_cta[df_cta['tipo'] == 'CREDITO']['nombre'].tolist())
                cat_n = df_cat.iloc[0]['nombre']

            if st.form_submit_button("Guardar"):
                id_c = df_cta[df_cta['nombre'] == cta_n]['id'].values[0]
                id_ct = df_cat[df_cat['nombre'] == cat_n]['id'].values[0]
                if tipo_op == "Ingreso": tp = "INGRESO"
                elif tipo_op == "Pagar Tarjeta":
                    tp = "PAGO_TAR_JETA"
                    id_dest = df_cta[df_cta['nombre'] == cta_dest]['id'].values[0]
                    db_save(f, m, d, id_c, id_ct, "PAGO_TARJETA", id_dest)
                else:
                    tp = "COMPRA_TARJETA" if df_cta[df_cta['nombre'] == cta_n]['tipo'].values[0] == 'CREDITO' else "GASTO"
                    db_save(f, m, d, id_c, id_ct, tp)
                st.success("¡Guardado!"); time.sleep(1); st.rerun()

# --- 4. HISTORIAL ---
elif menu == "📝 Historial":
    st.title("Gestión de Movimientos")
    ver_todo = st.checkbox("🔍 Ver TODO el historial")
    if ver_todo: df_h = get_movimientos(date(2024,1,1), date(2027,1,1))
    else:
        df_h = get_movimientos(f_ini, f_fin)
        if not df_h.empty: df_h = df_h[(df_h['fecha'] >= f_ini) & (df_h['fecha'] <= f_fin)]

    if not df_h.empty:
        st.data_editor(df_h[['id', 'fecha', 'descripcion', 'monto', 'cuenta', 'tipo']], width="stretch", hide_index=True)
        st.divider()
        opciones = {f"{r['fecha']} | {r['descripcion']} | {fmt_ars(r['monto'])}": r['id'] for _, r in df_h.iterrows()}
        a_borrar = st.selectbox("Seleccioná para borrar:", ["Seleccionar..."] + list(opciones.keys()))
        if st.button("Borrar Seleccionado", type="primary") and a_borrar != "Seleccionar...":
            db_delete(opciones[a_borrar]); st.success("Eliminado"); time.sleep(1); st.rerun()
    else: st.info("No hay datos.")

# --- 5. TARJETAS ---
elif menu == "💳 Tarjetas":
    st.title("Tarjetas")
    tab1, tab2 = st.tabs(["⚙️ Fechas", "📥 Importar"])
    with tab1:
        df_crd = df_cta[df_cta['tipo'] == 'CREDITO']
        for _, r in df_crd.iterrows():
            with st.container(border=True):
                ca, cb, cc, cd = st.columns([2,1,1,1])
                ca.write(f"### {r['nombre']}")
                ci = cb.number_input("Cierre", 1, 31, int(r.get('dia_cierre') or 23), key=f"ci_{r['id']}")
                vt = cc.number_input("Vto", 1, 31, int(r.get('dia_vencimiento') or 5), key=f"vt_{r['id']}")
                if cd.button("Guardar", key=f"btn_{r['id']}"):
                    supabase.table("cuentas").update({"dia_cierre": ci, "dia_vencimiento": vt}).eq("id", r['id']).execute()
                    st.success("Ok"); st.rerun()
    with tab2:
        up = st.file_uploader("Subí Excel/CSV", type=['xlsx', 'csv'])
        if up:
            try:
                if up.name.endswith('.csv'): df_up = pd.read_csv(up)
                else:
                    df_raw = pd.read_excel(up)
                    header = 0
                    for i in range(len(df_raw)):
                        if 'Fecha' in df_raw.iloc[i].values or 'FECHA' in df_raw.iloc[i].values: header = i + 1; break
                    df_up = pd.read_excel(up, skiprows=header)
                df_up = df_up.dropna(how='all').reset_index(drop=True)
                st.dataframe(df_up.head(5), width="stretch")
                with st.form("imp"):
                    sel = st.selectbox("Asignar a:", df_cta[df_cta['tipo'] == 'CREDITO']['nombre'].tolist())
                    c1, c2, c3 = st.columns(3)
                    f_c = c1.selectbox("Fecha", df_up.columns); d_c = c2.selectbox("Desc", df_up.columns); m_c = c3.selectbox("Monto", df_up.columns)
                    if st.form_submit_button("Importar"):
                        id_tj = df_cta[df_cta['nombre'] == sel]['id'].values[0]
                        for _, row in df_up.iterrows():
                            try:
                                m_s = str(row[m_c]).replace('$','').replace(' ','')
                                if ',' in m_s and '.' in m_s: m_s = m_s.replace('.','').replace(',','.')
                                elif ',' in m_s: m_s = m_s.replace(',','.')
                                db_save(pd.to_datetime(row[f_c], dayfirst=True).date(), abs(float(m_s)), str(row[d_c]), id_tj, df_cat.iloc[0]['id'], "COMPRA_TARJETA")
                            except: continue
                        st.success("Ok!"); time.sleep(1); st.rerun()
            except Exception as e: st.error(f"Error: {e}")

# --- 6. AJUSTES ---
elif menu == "⚙️ Ajustes":
    st.header("Sueldo Base")
    n_s = st.number_input("Ingreso Neto Mensual", value=int(sueldo_base), step=1000)
    if st.button("Guardar Sueldo"):
        supabase.table("configuracion").upsert({"clave": "sueldo_mensual", "valor": str(n_s)}).execute()
        st.success("Guardado!"); time.sleep(1); st.rerun()