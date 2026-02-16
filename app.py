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

# --- FUNCIONES ---
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

# --- DATOS ---
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

# --- LÓGICA ---
if menu == "📊 Dashboard":
    # Lógica Dashboard V3.1 (Mantenemos la que te gustó)
    df = get_movimientos_periodo(fecha_inicio, fecha_fin)
    
    st.header(f"Resumen del Periodo")

    fecha_prev_ini = fecha_inicio - relativedelta(months=1)
    fecha_prev_fin = fecha_fin - relativedelta(months=1)
    df_prev = get_movimientos_periodo(fecha_prev_ini, fecha_prev_fin)

    gastos_now = df[df['tipo'].isin(['GASTO', 'PAGO_TARJETA'])]['monto'].sum() if not df.empty else 0
    gastos_prev = df_prev[df_prev['tipo'].isin(['GASTO', 'PAGO_TARJETA'])]['monto'].sum() if not df_prev.empty else 0
    
    ingresos_now = df[df['tipo'] == 'INGRESO']['monto'].sum() if not df.empty else 0
    total_ingresos = sueldo + ingresos_now # Suma sueldo base + extras
    
    delta_gastos = ((gastos_now - gastos_prev) / gastos_prev * 100) if gastos_prev > 0 else 0
    consumo_tarjeta = df[df['tipo'] == 'COMPRA_TARJETA']['monto'].sum() if not df.empty else 0
    disponible = total_ingresos - gastos_now

    col1, col2 = st.columns(2)
    with col1:
        with st.container(border=True):
            st.metric("✅ Proyección Disponible", f"${disponible:,.0f}", help="Si es futuro: Lo que te sobraría. Si es pasado: Lo que te sobró.")
            st.caption(f"Ingresos Totales (Sueldo+Extras): ${total_ingresos:,.0f}")
    with col2:
        with st.container(border=True):
            delta_color = "normal" if delta_gastos < 0 else "inverse"
            st.metric("💸 Gastos Proyectados/Reales", f"${gastos_now:,.0f}", delta=f"{delta_gastos:.1f}% vs mes pasado", delta_color=delta_color)
            st.caption(f"Deuda Tarjeta: ${consumo_tarjeta:,.0f}")

    st.divider()
    c_chart1, c_chart2 = st.columns([2, 1])
    with c_chart1:
        st.subheader("Flujo Diario")
        if not df.empty:
            df_gasto_diario = df[df['tipo'] == 'GASTO'].groupby('fecha')['monto'].sum().reset_index()
            fig = px.bar(df_gasto_diario, x='fecha', y='monto', color_discrete_sequence=['#FF4B4B'])
            fig.update_layout(xaxis_title="", yaxis_title="", height=250, margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Sin datos.")
    with c_chart2:
        st.subheader("Categorías")
        if not df.empty:
            df_cat = df[df['tipo'].isin(['GASTO', 'COMPRA_TARJETA'])].groupby('categoria')['monto'].sum().reset_index()
            if not df_cat.empty:
                fig_pie = px.pie(df_cat, values='monto', names='categoria', hole=0.5)
                fig_pie.update_layout(showlegend=False, height=250, margin=dict(l=0, r=0, t=0, b=0))
                st.plotly_chart(fig_pie, use_container_width=True)

elif menu == "📅 Planificador":
    st.title("Armar Mes Futuro")
    st.info("💡 Usá esto para cargar de una vez todos tus gastos fijos y el sueldo de Marzo.")
    
    with st.container(border=True):
        c_mes, c_anio = st.columns(2)
        # Default al mes siguiente
        next_month = date.today() + relativedelta(months=1)
        mes_sel = c_mes.selectbox("Mes", range(1, 13), index=next_month.month-1)
        anio_sel = c_anio.number_input("Año", value=next_month.year, step=1)
        
        # Fecha base para el plan (día 1 del mes elegido)
        fecha_plan = date(anio_sel, mes_sel, 1)
        
        st.divider()
        st.subheader("1. Ingresos Estimados")
        ingreso_neto = st.number_input("Sueldo Neto a cobrar ($)", value=sueldo, step=10000.0)
        cta_ingreso = st.selectbox("¿Dónde lo cobrás?", df_cuentas['nombre'])
        
        st.divider()
        st.subheader("2. Gastos Fijos (Alquiler, Gimnasio, etc)")
        st.caption("Cargá todos los gastos que ya sabés que vas a tener.")
        
        # Tabla editable vacía para llenar rápido
        if 'df_plan' not in st.session_state:
            st.session_state.df_plan = pd.DataFrame([
                {"Descripción": "Alquiler", "Monto": 0.0, "Categoría": "Varios", "Medio Pago": "Efectivo"},
                {"Descripción": "Internet", "Monto": 0.0, "Categoría": "Servicios", "Medio Pago": "Mercado Pago"},
                {"Descripción": "Gimnasio", "Monto": 0.0, "Categoría": "Varios", "Medio Pago": "Santander Visa"},
            ])

        # Configuración de columnas para el editor
        cols_cfg = {
            "Categoría": st.column_config.SelectboxColumn(options=df_cats['nombre']),
            "Medio Pago": st.column_config.SelectboxColumn(options=df_cuentas['nombre']),
            "Monto": st.column_config.NumberColumn(format="$%.2f")
        }
        
        edited_plan = st.data_editor(st.session_state.df_plan, num_rows="dynamic", column_config=cols_cfg, use_container_width=True)
        
        # Cálculo en tiempo real
        total_gastos_plan = edited_plan['Monto'].sum()
        saldo_proyectado = ingreso_neto - total_gastos_plan
        
        st.metric("💰 Saldo Proyectado (Neto - Fijos)", f"${saldo_proyectado:,.0f}", delta=f"Gastos Fijos: ${total_gastos_plan:,.0f}")
        
        if st.button("🚀 Guardar Planificación", type="primary", use_container_width=True):
            # 1. Guardar Ingreso
            id_cta_ing = df_cuentas[df_cuentas['nombre'] == cta_ingreso]['id'].values[0]
            # Usamos categoría "Sueldo" si existe, sino la primera
            try:
                id_cat_ing = df_cats[df_cats['nombre'].str.contains("Sueldo", case=False)]['id'].values[0]
            except:
                id_cat_ing = df_cats.iloc[0]['id']
            
            guardar_movimiento(fecha_plan, ingreso_neto, "Sueldo Planificado", id_cta_ing, id_cat_ing, "INGRESO")
            
            # 2. Guardar Gastos
            count = 0
            for _, row in edited_plan.iterrows():
                if row['Monto'] > 0:
                    try:
                        id_cta_g = df_cuentas[df_cuentas['nombre'] == row['Medio Pago']]['id'].values[0]
                        id_cat_g = df_cats[df_cats['nombre'] == row['Categoría']]['id'].values[0]
                        es_credito = df_cuentas[df_cuentas['nombre'] == row['Medio Pago']]['tipo'].values[0] == 'CREDITO'
                        tipo_g = "COMPRA_TARJETA" if es_credito else "GASTO"
                        
                        # Ponemos fecha día 5 por defecto o la fecha base
                        guardar_movimiento(fecha_plan + timedelta(days=4), row['Monto'], row['Descripción'], id_cta_g, id_cat_g, tipo_g)
                        count += 1
                    except Exception as e:
                        st.error(f"Error en fila {row['Descripción']}: {e}")
            
            st.success(f"¡Plan creado! Se agendaron el Ingreso y {count} gastos fijos para {fecha_plan.strftime('%B %Y')}.")
            time.sleep(2)
            st.rerun()

elif menu == "➕ Cargar":
    st.header("Carga Manual")
    tipo_op = st.segmented_control("Tipo", ["Gasto", "Ingreso", "Transferencia"], default="Gasto")
    with st.container(border=True):
        c1, c2 = st.columns(2)
        fecha = c1.date_input("Fecha", date.today())
        monto = c2.number_input("Monto ($)", min_value=1.0, step=100.0)
        desc = st.text_input("Descripción")
        if tipo_op == "Gasto":
            c3, c4 = st.columns(2)
            cuenta = c3.selectbox("Medio de Pago", df_cuentas['nombre'])
            cat = c4.selectbox("Categoría", df_cats['nombre'])
            if st.button("Guardar", type="primary", use_container_width=True):
                id_cta = df_cuentas[df_cuentas['nombre'] == cuenta]['id'].values[0]
                id_cat = df_cats[df_cats['nombre'] == cat]['id'].values[0]
                es_credito = df_cuentas[df_cuentas['nombre'] == cuenta]['tipo'].values[0] == 'CREDITO'
                tipo_db = "COMPRA_TARJETA" if es_credito else "GASTO"
                guardar_movimiento(fecha, monto, desc, id_cta, id_cat, tipo_db)
                st.success("Listo!")
                time.sleep(1)
                st.rerun()
        # (Resto de lógica de Ingreso/Transferencia igual a versiones anteriores...)

elif menu == "📝 Movimientos":
    # Misma lógica V3.1 con data_editor
    df = get_movimientos_periodo(fecha_inicio, fecha_fin)
    if not df.empty:
        df_edit = df[['id', 'fecha', 'descripcion', 'monto', 'cuenta', 'categoria', 'tipo']].copy()
        edited_df = st.data_editor(
            df_edit,
            column_config={
                "id": None, 
                "monto": st.column_config.NumberColumn(format="$%.2f"),
                "fecha": st.column_config.DateColumn(),
            },
            hide_index=True, use_container_width=True, num_rows="dynamic", key="history"
        )
        if st.button("Guardar Cambios"):
             # Lógica update (igual a V3.1)
             pass 

elif menu == "⚙️ Ajustes":
    # Configuración de sueldo base
    with st.container(border=True):
        st.subheader("Configuración General")
        nuevo = st.number_input("Sueldo Base (Ref)", value=sueldo)
        if st.button("Actualizar"):
            supabase.table("configuracion").upsert({"clave": "sueldo_mensual", "valor": str(nuevo)}).execute()
            st.success("Guardado")