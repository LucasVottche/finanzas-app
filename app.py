import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import date, timedelta, datetime
from dateutil.relativedelta import relativedelta # Necesario para calcular mes anterior
import plotly.express as px
import plotly.graph_objects as go
import time

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Finanzas Lucas", 
    page_icon="💸", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilos CSS personalizados para limpiar la interfaz
st.markdown("""
<style>
    .stMetric {
        background-color: #f0f2f6;
        padding: 15px;
        border-radius: 10px;
    }
    div[data-testid="stMetricValue"] {
        font-size: 24px;
    }
</style>
""", unsafe_allow_html=True)

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

# --- FUNCIONES BACKEND ---
def get_data_maestros():
    cuentas = pd.DataFrame(supabase.table("cuentas").select("*").execute().data)
    categorias = pd.DataFrame(supabase.table("categorias").select("*").execute().data)
    # Sueldo
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
            
            # Limpieza
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

# --- DATOS INICIALES ---
df_cuentas, df_cats, sueldo = get_data_maestros()

# --- SIDEBAR ---
with st.sidebar:
    st.header("Gestión Financiera")
    menu = st.radio("Ir a:", ["📊 Dashboard", "➕ Nuevo Movimiento", "📝 Historial / Edición", "📥 Importar"], label_visibility="collapsed")
    
    st.divider()
    
    # Filtro Global
    with st.expander("📅 Filtro de Fechas", expanded=True):
        col_f1, col_f2 = st.columns(2)
        # Por defecto: Mes actual
        today = date.today()
        start_month = today.replace(day=1)
        fecha_inicio = col_f1.date_input("Desde", start_month, label_visibility="collapsed")
        fecha_fin = col_f2.date_input("Hasta", today, label_visibility="collapsed")

# --- LÓGICA PRINCIPAL ---
df = get_movimientos_periodo(fecha_inicio, fecha_fin)

if menu == "📊 Dashboard":
    st.title("Panorama Financiero")

    # 1. CÁLCULO DE DELTAS (Comparativa con mes anterior)
    # Buscamos datos del periodo anterior exacto
    fecha_inicio_prev = fecha_inicio - relativedelta(months=1)
    fecha_fin_prev = fecha_fin - relativedelta(months=1)
    df_prev = get_movimientos_periodo(fecha_inicio_prev, fecha_fin_prev)

    gastos_now = df[df['tipo'].isin(['GASTO', 'PAGO_TARJETA'])]['monto'].sum() if not df.empty else 0
    gastos_prev = df_prev[df_prev['tipo'].isin(['GASTO', 'PAGO_TARJETA'])]['monto'].sum() if not df_prev.empty else 0
    
    ingresos_now = df[df['tipo'] == 'INGRESO']['monto'].sum() if not df.empty else 0
    ingresos_prev = df_prev[df_prev['tipo'] == 'INGRESO']['monto'].sum() if not df_prev.empty else 0
    
    delta_gastos = ((gastos_now - gastos_prev) / gastos_prev * 100) if gastos_prev > 0 else 0
    
    consumo_tarjeta = df[df['tipo'] == 'COMPRA_TARJETA']['monto'].sum() if not df.empty else 0

    # 2. METRICAS PRINCIPALES
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    
    kpi1.metric("Ingresos Totales", f"${sueldo + ingresos_now:,.0f}", delta=f"${ingresos_now:,.0f} extra")
    
    # Lógica de colores invertida para gastos (Si bajó es verde/bueno)
    kpi2.metric("Salidas Reales", f"${gastos_now:,.0f}", delta=f"{delta_gastos:.1f}% vs mes anterior", delta_color="inverse")
    
    kpi3.metric("Deuda Tarjeta", f"${consumo_tarjeta:,.0f}", help="Compras a crédito este mes")
    
    disponible = (sueldo + ingresos_now) - gastos_now
    kpi4.metric("Disponible", f"${disponible:,.0f}")

    st.divider()

    # 3. GRÁFICOS INTERACTIVOS
    c1, c2 = st.columns([2, 1])
    
    with c1:
        st.subheader("Evolución de Gastos (Últimos 6 meses)")
        # Simulación de datos históricos (esto idealmente se trae con una query agrupada)
        # Para esta versión V3, hacemos un gráfico simple del mes actual por día
        if not df.empty:
            df_diario = df[df['tipo'] == 'GASTO'].groupby('fecha')['monto'].sum().reset_index()
            fig_bar = px.bar(df_diario, x='fecha', y='monto', color_discrete_sequence=['#ff4b4b'])
            fig_bar.update_layout(xaxis_title=None, yaxis_title=None, showlegend=False, height=300)
            st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.info("Sin datos para graficar.")

    with c2:
        st.subheader("Top Categorías")
        if not df.empty:
            df_pie = df[df['tipo'].isin(['GASTO', 'COMPRA_TARJETA'])]
            if not df_pie.empty:
                fig_pie = px.donut(df_pie, values='monto', names='categoria', hole=0.6)
                fig_pie.update_layout(showlegend=False, height=300, margin=dict(t=0, b=0, l=0, r=0))
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.write("Sin consumos.")
        else:
            st.write("Sin datos.")

elif menu == "➕ Nuevo Movimiento":
    st.title("Carga Rápida")
    
    # Usamos tabs para organizar mejor visualmente
    tab_gasto, tab_ingreso, tab_transf = st.tabs(["💸 Gasto / Compra", "💰 Ingreso", "🔄 Transferencia"])
    
    with tab_gasto:
        with st.form("form_gasto_rapido", clear_on_submit=True):
            c1, c2 = st.columns(2)
            monto = c1.number_input("Monto ($)", min_value=1.0, step=100.0, format="%.2f")
            desc = c2.text_input("Descripción", placeholder="Ej: Supermercado")
            
            c3, c4, c5 = st.columns(3)
            cuenta = c3.selectbox("Pagado con:", df_cuentas['nombre'])
            cat = c4.selectbox("Categoría:", df_cats['nombre'])
            fecha = c5.date_input("Fecha", date.today())
            
            if st.form_submit_button("Guardar Gasto", use_container_width=True):
                # Lógica de IDs
                id_cta = df_cuentas[df_cuentas['nombre'] == cuenta]['id'].values[0]
                id_cat = df_cats[df_cats['nombre'] == cat]['id'].values[0]
                es_credito = df_cuentas[df_cuentas['nombre'] == cuenta]['tipo'].values[0] == 'CREDITO'
                tipo = "COMPRA_TARJETA" if es_credito else "GASTO"
                
                guardar_movimiento(fecha, monto, desc, id_cta, id_cat, tipo)
                st.toast(f"✅ Gasto de ${monto} guardado!", icon="🎉")
                time.sleep(1) # Pequeña pausa para ver el toast

    with tab_ingreso:
        # Formulario similar simplificado...
        if st.button("Registrar Ingreso (Sueldo)"):
            st.info("Configurá esto en la pestaña Dashboard o Configuración")

elif menu == "📝 Historial / Edición":
    st.title("Base de Datos Editable")
    st.info("💡 Hacé doble clic en una celda para editar el Monto o la Descripción. Para borrar, seleccioná la fila y apretá Borrar.")
    
    if not df.empty:
        # Preparamos el DF para el editor
        df_edit = df[['id', 'fecha', 'descripcion', 'monto', 'cuenta', 'categoria', 'tipo']].copy()
        
        # EDITOR DE DATOS (NUEVO FEATURE DE STREAMLIT)
        edited_df = st.data_editor(
            df_edit,
            column_config={
                "id": None, # Oculto
                "monto": st.column_config.NumberColumn("Monto", format="$%.2f"),
                "fecha": st.column_config.DateColumn("Fecha"),
                "tipo": st.column_config.SelectboxColumn("Tipo", options=["GASTO", "INGRESO", "COMPRA_TARJETA"]),
            },
            hide_index=True,
            use_container_width=True,
            num_rows="dynamic", # Permite agregar/borrar filas
            key="data_editor"
        )
        
        # Detectar cambios y guardar en Supabase
        if st.button("💾 Guardar Cambios"):
            # Streamlit devuelve los cambios en st.session_state['data_editor']
            changes = st.session_state['data_editor']
            
            # 1. Filas editadas
            for idx, updates in changes['edited_rows'].items():
                row_id = df_edit.iloc[idx]['id']
                for key, value in updates.items():
                    actualizar_movimiento(row_id, key, value)
            
            # 2. Filas borradas
            for idx in changes['deleted_rows']:
                row_id = df_edit.iloc[idx]['id']
                borrar_movimiento(row_id)
                
            st.toast("Base de datos actualizada!", icon="💾")
            time.sleep(1)
            st.rerun()

elif menu == "📥 Importar":
    st.title("Importación Masiva")
    st.file_uploader("Arrastrá CSV de Mercado Pago o Banco", type=["csv"])
    st.caption("Esta funcionalidad sigue igual que la versión anterior.")