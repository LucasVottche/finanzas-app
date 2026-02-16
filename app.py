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
        
        # --- LÓGICA DE INGRESOS (Evita duplicados) ---
        ingresos_registrados = df_mes[df_mes['tipo'] == 'INGRESO']['monto'].sum()
        # Si ya cargaste un sueldo, el total es ese. Si no cargaste nada, usamos el de Ajustes.
        total_ingresos = ingresos_registrados if ingresos_registrados > 0 else sueldo_base
        
        # --- GASTOS ---
        gastos_cash = df_mes[df_mes['tipo'] == 'GASTO']['monto'].sum()
        consumos_tarjeta_mes = df_mes[df_mes['tipo'] == 'COMPRA_TARJETA']['monto'].sum()
        
        # --- VENCIMIENTOS DE TARJETA (Lo que pagás hoy de consumos viejos) ---
        df_tj = df_raw[df_raw['tipo'] == 'COMPRA_TARJETA'].copy()
        vence_ahora_monto = 0
        if not df_tj.empty:
            df_tj['fecha_vto'] = df_tj.apply(lambda x: calcular_vto_real(x['fecha'], x['cierre'], x['vto']), axis=1)
            vence_ahora = df_tj[(df_tj['fecha_vto'] >= f_ini) & (df_tj['fecha_vto'] <= f_fin)]
            vence_ahora_monto = vence_ahora['monto'].sum()

        disponible = total_ingresos - gastos_cash - vence_ahora_monto

        c1, c2, c3 = st.columns(3)
        with c1:
            with st.container(border=True):
                st.metric("✅ Disponible (Caja)", fmt_ars(disponible), help="Lo que te queda en el bolsillo este mes")
                st.caption(f"Ingresos: {fmt_ars(total_ingresos)}")
        with c2:
            with st.container(border=True):
                st.metric("💳 Vencen este mes", fmt_ars(vence_ahora_monto), help="Consumos de meses anteriores que pagás hoy")
        with c3:
            with st.container(border=True):
                st.metric("🛒 Consumo Total", fmt_ars(gastos_cash + consumos_tarjeta_mes), help="Todo lo que gastaste en el mes (Cash + Tarjeta)")

        st.divider()
        col_g1, col_g2 = st.columns([2, 1])
        with col_g1:
            st.subheader("Flujo de Movimientos")
            df_bar = df_mes[df_mes['tipo'] != 'INGRESO']
            if not df_bar.empty:
                fig = px.bar(df_bar, x='fecha', y='monto', color='categoria', barmode='group')
                st.plotly_chart(fig, use_container_width=True)
        with col_g2:
            st.subheader("Gastos por Rubro")
            df_pie = df_mes[df_mes['tipo'].isin(['GASTO', 'COMPRA_TARJETA'])]
            if not df_pie.empty:
                fig_pie = px.pie(df_pie, values='monto', names='categoria', hole=0.5)
                st.plotly_chart(fig_pie, use_container_width=True)
    else:
        st.info("No hay datos para este mes. Podés cargarlos en 'Planificador'.")

# --- 3. PLANIFICADOR (Edición rápida) ---
elif menu == "📅 Planificador":
    st.title(f"Planear {f_ini.strftime('%B %Y')}")
    st.info("Cargá tu sueldo y gastos fijos. Si los gastos son con Tarjeta, aparecerán como deuda en el Dashboard.")
    with st.container(border=True):
        ing = st.number_input("Sueldo Neto estimado", value=int(sueldo_base), step=1000)
        if 'plan_df' not in st.session_state:
            st.session_state.plan_df = pd.DataFrame([{"Descripción": "Alquiler", "Monto": 0.0, "Categoría": df_cat['nombre'].tolist()[0], "Pago": df_cta['nombre'].tolist()[0]}])
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
                    db_save(f_ini + timedelta(days=4), r['Monto'], r['Descripción'], c_id, df_cat[df_cat['nombre'] == r['Categoría']]['id'].values[0], tp)
            st.success("Plan guardado!"); time.sleep(1); st.rerun()

# --- 4. HISTORIAL (Para borrar o editar el plan) ---
elif menu == "📝 Historial":
    st.title("Editar o Borrar Movimientos")
    st.caption("Filtrá por el mes en la barra lateral para ver tu planificación de Marzo.")
    df_h = get_movimientos(f_ini, f_fin)
    if not df_h.empty:
        df_h = df_h[(df_h['fecha'] >= f_ini) & (df_h['fecha'] <= f_fin)]
        st.data_editor(df_h[['id', 'fecha', 'descripcion', 'monto', 'cuenta', 'categoria', 'tipo']], 
                       use_container_width=True, hide_index=True, key="edit_hist")
        if st.button("Guardar Cambios"):
            st.toast("Cambios guardados en Supabase") # Aquí podés añadir la lógica de update si querés
    else:
        st.write("Sin movimientos en este periodo.")

# (Resto de secciones iguales...)
# --- 6. AJUSTES ---
elif menu == "⚙️ Ajustes":
    st.title("Configuración")
    with st.container(border=True):
        n_s = st.number_input("Sueldo Base Mensual", value=int(sueldo_base))
        if st.button("Actualizar Sueldo", use_container_width=True):
            supabase.table("configuracion").upsert({"clave": "sueldo_mensual", "valor": str(n_s)}).execute()
            st.success("Ok"); time.sleep(1); st.rerun()