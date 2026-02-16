import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
import plotly.express as px
import time

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Finanzas Lucas", 
    page_icon="💸", 
    layout="wide"
)

# --- CONEXIÓN SUPABASE ---
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

# --- FUNCIONES DE FORMATO ARGENTINO 🇦🇷 ---
def fmt_ars(valor):
    """Convierte 1500.50 en $1.500,50"""
    if valor is None: valor = 0
    # Formato estándar primero (1,500.50)
    s = f"{valor:,.2f}"
    # Invertimos caracteres: , -> X, . -> ,, X -> .
    s = s.replace(',', 'X').replace('.', ',').replace('X', '.')
    # Si termina en ,00 lo sacamos para limpiar
    if s.endswith(",00"):
        s = s[:-3]
    return f"${s}"

# --- FUNCIONES DE BASE DE DATOS ---
def get_data_maestros():
    cuentas = pd.DataFrame(supabase.table("cuentas").select("*").execute().data)
    categorias = pd.DataFrame(supabase.table("categorias").select("*").execute().data)
    try:
        resp = supabase.table("configuracion").select("valor").eq("clave", "sueldo_mensual").execute()
        sueldo = float(resp.data[0]['valor']) if resp.data else 0.0
    except:
        sueldo = 0.0
    return cuentas, categorias, sueldo

def get_movimientos_periodo(desde, hasta):
    try:
        resp = supabase.table("movimientos").select(
            "*, categorias(nombre, icono), cuentas:cuentas!cuenta_id(nombre, tipo)"
        ).gte("fecha", desde).lte("fecha", hasta).order("fecha", desc=True).execute()
        
        data = resp.data
        if not data: return pd.DataFrame()
        
        rows = []
        for d in data:
            row = d.copy()
            if d.get('categorias'):
                row['categoria'] = f"{d['categorias']['icono']} {d['categorias']['nombre']}"
            else:
                row['categoria'] = "General"
            if d.get('cuentas'):
                row['cuenta'] = d['cuentas']['nombre']
                row['cuenta_tipo'] = d['cuentas']['tipo']
            del row['categorias'], row['cuentas']
            rows.append(row)
        return pd.DataFrame(rows)
    except:
        return pd.DataFrame()

def guardar_movimiento(fecha, monto, desc, cuenta_id, cat_id, tipo, destino_id=None):
    payload = {
        "fecha": str(fecha), "monto": monto, "descripcion": desc,
        "cuenta_id": cuenta_id, "categoria_id": cat_id, "tipo": tipo
    }
    if destino_id: payload["cuenta_destino_id"] = destino_id
    supabase.table("movimientos").insert(payload).execute()

def actualizar_movimiento(id_mov, campo, valor):
    supabase.table("movimientos").update({campo: valor}).eq("id", id_mov).execute()

def borrar_movimiento(id_mov):
    supabase.table("movimientos").delete().eq("id", id_mov).execute()

# --- CARGA DATOS ---
df_cuentas, df_cats, sueldo = get_data_maestros()

# --- SIDEBAR ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2382/2382461.png", width=50)
    st.title("Lucas Finanzas")
    
    menu = st.radio("Menú", ["📊 Dashboard", "📅 Planificador", "➕ Cargar", "📝 Movimientos", "⚙️ Ajustes"])
    
    st.divider()
    st.caption("Filtro Dashboard")
    today = date.today()
    fecha_inicio = st.date_input("Desde", today.replace(day=1))
    fecha_fin = st.date_input("Hasta", today)

# --- DASHBOARD ---
if menu == "📊 Dashboard":
    df = get_movimientos_periodo(fecha_inicio, fecha_fin)
    
    # Cálculos previos
    fecha_prev_ini = fecha_inicio - relativedelta(months=1)
    fecha_prev_fin = fecha_fin - relativedelta(months=1)
    df_prev = get_movimientos_periodo(fecha_prev_ini, fecha_prev_fin)

    gastos_now = df[df['tipo'].isin(['GASTO', 'PAGO_TARJETA'])]['monto'].sum() if not df.empty else 0
    gastos_prev = df_prev[df_prev['tipo'].isin(['GASTO', 'PAGO_TARJETA'])]['monto'].sum() if not df_prev.empty else 0
    ingresos_now = df[df['tipo'] == 'INGRESO']['monto'].sum() if not df.empty else 0
    total_ingresos = sueldo + ingresos_now
    delta_gastos = ((gastos_now - gastos_prev) / gastos_prev * 100) if gastos_prev > 0 else 0
    consumo_tarjeta = df[df['tipo'] == 'COMPRA_TARJETA']['monto'].sum() if not df.empty else 0
    disponible = total_ingresos - gastos_now

    st.header("Resumen Financiero")
    col1, col2 = st.columns(2)
    with col1:
        with st.container(border=True):
            # Usamos fmt_ars para mostrar lindo
            st.metric("✅ Disponible", fmt_ars(disponible))
            st.caption(f"Ingresos Totales: {fmt_ars(total_ingresos)}")
    with col2:
        with st.container(border=True):
            delta_color = "normal" if delta_gastos < 0 else "inverse"
            st.metric("💸 Gastos Reales", fmt_ars(gastos_now), delta=f"{delta_gastos:.1f}% vs mes pasado", delta_color=delta_color)
            st.caption(f"Deuda Tarjeta: {fmt_ars(consumo_tarjeta)}")

    st.divider()
    c1, c2 = st.columns([2, 1])
    with c1:
        st.subheader("Diario")
        if not df.empty:
            df_g = df[df['tipo'] == 'GASTO'].groupby('fecha')['monto'].sum().reset_index()
            fig = px.bar(df_g, x='fecha', y='monto', color_discrete_sequence=['#FF4B4B'])
            fig.update_layout(xaxis_title=None, yaxis_title=None, height=250)
            st.plotly_chart(fig, use_container_width=True)
    with c2:
        st.subheader("Rubros")
        if not df.empty:
            df_c = df[df['tipo'].isin(['GASTO', 'COMPRA_TARJETA'])].groupby('categoria')['monto'].sum().reset_index()
            fig2 = px.pie(df_c, values='monto', names='categoria', hole=0.5)
            fig2.update_layout(showlegend=False, height=250, margin=dict(t=0, b=0, l=0, r=0))
            st.plotly_chart(fig2, use_container_width=True)

# --- PLANIFICADOR ---
elif menu == "📅 Planificador":
    st.title("Planificar Mes")
    with st.container(border=True):
        c_m, c_a = st.columns(2)
        next_month = date.today() + relativedelta(months=1)
        mes_sel = c_m.selectbox("Mes", range(1, 13), index=next_month.month-1)
        anio_sel = c_a.number_input("Año", value=next_month.year, step=1, format="%d") # Format %d saca la coma al año
        fecha_plan = date(anio_sel, mes_sel, 1)
        
        st.divider()
        st.subheader("1. Tu Sueldo Neto")
        # step=1000 asegura que salte de a miles, format="%i" muestra entero sin decimales
        ingreso_neto = st.number_input("Monto a cobrar", value=int(sueldo), step=1000, format="%i")
        cta_ingreso = st.selectbox("Cuenta Destino", df_cuentas['nombre'])
        
        st.divider()
        st.subheader("2. Gastos Fijos")
        if 'df_plan' not in st.session_state:
            st.session_state.df_plan = pd.DataFrame([
                {"Descripción": "Alquiler", "Monto": 0, "Categoría": "Varios", "Medio Pago": "Efectivo"},
                {"Descripción": "Internet", "Monto": 0, "Categoría": "Servicios", "Medio Pago": "Mercado Pago"},
            ])

        edited_plan = st.data_editor(
            st.session_state.df_plan, 
            num_rows="dynamic", 
            column_config={
                "Categoría": st.column_config.SelectboxColumn(options=df_cats['nombre']),
                "Medio Pago": st.column_config.SelectboxColumn(options=df_cuentas['nombre']),
                "Monto": st.column_config.NumberColumn(format="$%.2f") # Acá dejamos decimal por si acaso
            }, 
            use_container_width=True
        )
        
        total_fijos = edited_plan['Monto'].sum()
        saldo_est = ingreso_neto - total_fijos
        
        st.metric("💰 Saldo Proyectado", fmt_ars(saldo_est), delta=f"Fijos: {fmt_ars(total_fijos)}")
        
        if st.button("🚀 Guardar Plan", type="primary", use_container_width=True):
            # Guardar Ingreso
            id_cta = df_cuentas[df_cuentas['nombre'] == cta_ingreso]['id'].values[0]
            try: id_cat = df_cats[df_cats['nombre'].str.contains("Sueldo")]['id'].values[0]
            except: id_cat = df_cats.iloc[0]['id']
            guardar_movimiento(fecha_plan, ingreso_neto, "Sueldo Planificado", id_cta, id_cat, "INGRESO")
            
            # Guardar Gastos
            c = 0
            for _, r in edited_plan.iterrows():
                if r['Monto'] > 0:
                    cta_g = df_cuentas[df_cuentas['nombre'] == r['Medio Pago']]['id'].values[0]
                    cat_g = df_cats[df_cats['nombre'] == r['Categoría']]['id'].values[0]
                    es_cred = df_cuentas[df_cuentas['nombre'] == r['Medio Pago']]['tipo'].values[0] == 'CREDITO'
                    tipo = "COMPRA_TARJETA" if es_cred else "GASTO"
                    guardar_movimiento(fecha_plan + timedelta(days=5), r['Monto'], r['Descripción'], cta_g, cat_g, tipo)
                    c += 1
            st.success(f"¡Listo! Se guardó el ingreso y {c} gastos para {fecha_plan.strftime('%m/%Y')}.")
            time.sleep(2)
            st.rerun()

# --- CARGAR ---
elif menu == "➕ Cargar":
    st.header("Carga Manual")
    tipo = st.segmented_control("Tipo", ["Gasto", "Ingreso", "Transferencia"], default="Gasto")
    with st.container(border=True):
        c1, c2 = st.columns(2)
        fecha = c1.date_input("Fecha", date.today())
        # Input limpio: format="%i" para enteros
        monto = c2.number_input("Monto", min_value=1, step=100, format="%i")
        desc = st.text_input("Descripción")
        
        if tipo == "Gasto":
            c3, c4 = st.columns(2)
            cta = c3.selectbox("Pago con", df_cuentas['nombre'])
            cat = c4.selectbox("Rubro", df_cats['nombre'])
            if st.button("Guardar", type="primary", use_container_width=True):
                id_c = df_cuentas[df_cuentas['nombre'] == cta]['id'].values[0]
                id_cat = df_cats[df_cats['nombre'] == cat]['id'].values[0]
                es_cr = df_cuentas[df_cuentas['nombre'] == cta]['tipo'].values[0] == 'CREDITO'
                t_db = "COMPRA_TARJETA" if es_cr else "GASTO"
                guardar_movimiento(fecha, monto, desc, id_c, id_cat, t_db)
                st.success("Guardado!"); time.sleep(1); st.rerun()
        
        elif tipo == "Ingreso":
            cta = st.selectbox("Destino", df_cuentas['nombre'])
            cat = st.selectbox("Rubro", df_cats['nombre'])
            if st.button("Guardar", type="primary", use_container_width=True):
                id_c = df_cuentas[df_cuentas['nombre'] == cta]['id'].values[0]
                id_cat = df_cats[df_cats['nombre'] == cat]['id'].values[0]
                guardar_movimiento(fecha, monto, desc, id_c, id_cat, "INGRESO")
                st.success("Guardado!"); time.sleep(1); st.rerun()
                
        elif tipo == "Transferencia":
            orig = st.selectbox("Desde", df_cuentas['nombre'])
            dest = st.selectbox("Hacia", df_cuentas['nombre'])
            if st.button("Transferir", type="primary", use_container_width=True):
                id_o = df_cuentas[df_cuentas['nombre'] == orig]['id'].values[0]
                id_d = df_cuentas[df_cuentas['nombre'] == dest]['id'].values[0]
                id_cat = df_cats.iloc[0]['id']
                guardar_movimiento(fecha, monto, f"Transferencia a {dest}", id_o, id_cat, "TRANSFERENCIA", id_d)
                st.success("Listo!"); time.sleep(1); st.rerun()

# --- MOVIMIENTOS ---
elif menu == "📝 Movimientos":
    df = get_movimientos_periodo(fecha_inicio, fecha_fin)
    if not df.empty:
        df_edit = df[['id', 'fecha', 'descripcion', 'monto', 'cuenta', 'categoria', 'tipo']].copy()
        edited_df = st.data_editor(
            df_edit,
            column_config={
                "id": None,
                "monto": st.column_config.NumberColumn(format="$%.2f"), # Excel style
                "fecha": st.column_config.DateColumn(),
            },
            hide_index=True, use_container_width=True, num_rows="dynamic", key="movs_edit"
        )
        if st.button("Guardar Cambios"):
            cambios = st.session_state['movs_edit']
            for i, u in cambios['edited_rows'].items():
                rid = df_edit.iloc[i]['id']
                for k, v in u.items(): actualizar_movimiento(rid, k, v)
            for i in cambios['deleted_rows']:
                rid = df_edit.iloc[i]['id']
                borrar_movimiento(rid)
            st.toast("Actualizado"); time.sleep(1); st.rerun()

# --- AJUSTES ---
elif menu == "⚙️ Ajustes":
    st.header("Configuración")
    with st.container(border=True):
        # Input limpio de Sueldo
        nuevo = st.number_input("Sueldo Base", value=int(sueldo), step=1000, format="%i")
        if st.button("Actualizar Sueldo"):
            supabase.table("configuracion").upsert({"clave": "sueldo_mensual", "valor": str(nuevo)}).execute()
            st.success("Sueldo Actualizado"); time.sleep(1); st.rerun()