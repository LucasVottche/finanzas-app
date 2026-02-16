import streamlit as st
import pandas as pd
from supabase import create_client, Client
from datetime import datetime, date
import plotly.express as px

# 1. Configuración de la Página
st.set_page_config(page_title="Mi Tablero Financiero", page_icon="💰", layout="wide")

# 2. Conexión a Supabase
@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_connection()

# --- FUNCIONES AUXILIARES ---
def get_config(clave):
    response = supabase.table("configuracion").select("valor").eq("clave", clave).execute()
    if response.data:
        return float(response.data[0]['valor'])
    return 0.0

def update_config(clave, valor):
    supabase.table("configuracion").upsert({"clave": clave, "valor": str(valor)}).execute()

def get_data(table):
    response = supabase.table(table).select("*").execute()
    return pd.DataFrame(response.data)

def guardar_movimiento(fecha, monto, descripcion, cuenta_id, categoria_id, tipo):
    data = {
        "fecha": str(fecha),
        "monto": monto,
        "descripcion": descripcion,
        "cuenta_id": cuenta_id,
        "categoria_id": categoria_id,
        "tipo": tipo
    }
    supabase.table("movimientos").insert(data).execute()

# --- INTERFAZ ---

# Barra Lateral (Menú)
menu = st.sidebar.radio("Navegación", ["📊 Dashboard", "📝 Cargar Gasto", "⚙️ Configuración"])

if menu == "📊 Dashboard":
    st.title("💸 Mi Estado Financiero")
    
    # Traer datos
    sueldo = get_config("sueldo_mensual")
    df_mov = get_data("movimientos")
    
    # Filtros de fecha (Mes Actual)
    today = date.today()
    if not df_mov.empty:
        df_mov['fecha'] = pd.to_datetime(df_mov['fecha']).dt.date
        df_mes = df_mov[
            (pd.to_datetime(df_mov['fecha']).dt.month == today.month) & 
            (pd.to_datetime(df_mov['fecha']).dt.year == today.year)
        ]
        total_gastos = df_mes[df_mes['tipo'] == 'GASTO']['monto'].sum()
        total_tarjetas = df_mes[df_mes['tipo'] == 'PAGO_TARJETA']['monto'].sum() # O consumos crédito
    else:
        total_gastos = 0
        total_tarjetas = 0
        df_mes = pd.DataFrame()

    disponible = sueldo - total_gastos

    # KPIs
    col1, col2, col3 = st.columns(3)
    col1.metric("💰 Sueldo Configurado", f"${sueldo:,.0f}")
    col2.metric("💸 Gastos este Mes", f"${total_gastos:,.0f}", delta_color="inverse")
    col3.metric("✅ Disponible Real", f"${disponible:,.0f}", delta=f"{disponible/sueldo*100:.1f}% restante")

    # Barra de progreso del sueldo
    if sueldo > 0:
        progreso = min(total_gastos / sueldo, 1.0)
        st.progress(progreso, text=f"Has gastado el {progreso*100:.1f}% de tu sueldo")
        if progreso > 0.8:
            st.error("⚠️ ¡Cuidado! Estás llegando al límite de tu sueldo.")

    # Gráficos
    c1, c2 = st.columns(2)
    if not df_mes.empty:
        # Gráfico por Categoría (Necesitamos hacer join con nombres, simplificado acá)
        # Para simplificar visualización rápida:
        fig_cat = px.pie(df_mes, values='monto', names='categoria_id', title='Gastos por Categoría')
        c1.plotly_chart(fig_cat, use_container_width=True)
        
        # Tabla últimos movimientos
        c2.subheader("Últimos Movimientos")
        c2.dataframe(df_mes[['fecha', 'descripcion', 'monto', 'tipo']].sort_values('fecha', ascending=False), hide_index=True)
    else:
        st.info("No hay gastos registrados este mes.")


elif menu == "📝 Cargar Gasto":
    st.header("Registrar Nuevo Movimiento")
    
    # Cargar listas desplegables desde DB
    cuentas = get_data("cuentas")
    categorias = get_data("categorias")
    
    with st.form("form_gasto"):
        col1, col2 = st.columns(2)
        fecha = col1.date_input("Fecha", date.today())
        monto = col2.number_input("Monto ($)", min_value=1.0, step=100.0)
        
        desc = st.text_input("Descripción (ej: Super Coto)")
        
        # Selectbox con lógica para obtener ID
        cuenta_nombre = col1.selectbox("Cuenta", cuentas['nombre'])
        cuenta_id = cuentas[cuentas['nombre'] == cuenta_nombre]['id'].values[0]
        
        cat_nombre = col2.selectbox("Categoría", categorias['nombre'])
        cat_id = categorias[categorias['nombre'] == cat_nombre]['id'].values[0]
        
        tipo = st.radio("Tipo", ["GASTO", "INGRESO", "PAGO_TARJETA"], horizontal=True)
        
        submitted = st.form_submit_button("Guardar Movimiento")
        
        if submitted:
            guardar_movimiento(fecha, monto, desc, cuenta_id, cat_id, tipo)
            st.success("✅ ¡Movimiento guardado exitosamente!")
            st.rerun() # Recarga para limpiar

elif menu == "⚙️ Configuración":
    st.header("Configuración")
    
    sueldo_actual = get_config("sueldo_mensual")
    nuevo_sueldo = st.number_input("Definir Sueldo Mensual", value=sueldo_actual, step=1000.0)
    
    if st.button("Actualizar Sueldo"):
        update_config("sueldo_mensual", nuevo_sueldo)
        st.success(f"Sueldo actualizado a ${nuevo_sueldo}")