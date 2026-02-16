import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import date, datetime
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

# --- SIDEBAR (Barra Lateral) ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2382/2382461.png", width=50)
    st.title("Lucas Finanzas")
    
    menu = st.radio("Navegación", ["📊 Dashboard", "➕ Cargar", "📝 Movimientos", "⚙️ Ajustes"])
    
    st.divider()
    st.subheader("📅 Periodo")
    today = date.today()
    fecha_inicio = st.date_input("Desde", today.replace(day=1))
    fecha_fin = st.date_input("Hasta", today)

# --- LÓGICA PRINCIPAL ---
df = get_movimientos_periodo(fecha_inicio, fecha_fin)

if menu == "📊 Dashboard":
    st.header(f"Resumen del Mes")
    
    # Cálculos
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

    # --- KPIs CON NUEVO DISEÑO ---
    col1, col2 = st.columns(2)
    
    with col1:
        with st.container(border=True):
            st.metric("✅ Disponible Hoy", f"${disponible:,.0f}", help="Sueldo + Extras - Gastos Reales")
            st.caption(f"Ingresos Totales: ${total_ingresos:,.0f}")

    with col2:
        with st.container(border=True):
            # Lógica de color para el delta (Si gastaste menos es verde)
            delta_color = "normal" if delta_gastos < 0 else "inverse"
            st.metric("💸 Salidas Reales", f"${gastos_now:,.0f}", delta=f"{delta_gastos:.1f}% vs mes pasado", delta_color=delta_color)
            st.caption(f"Deuda Tarjeta acumulada: ${consumo_tarjeta:,.0f}")

    # --- GRÁFICOS ---
    st.divider()
    c_chart1, c_chart2 = st.columns([2, 1])
    
    with c_chart1:
        st.subheader("Gastos Diarios")
        if not df.empty:
            df_gasto_diario = df[df['tipo'] == 'GASTO'].groupby('fecha')['monto'].sum().reset_index()
            fig = px.bar(df_gasto_diario, x='fecha', y='monto', color_discrete_sequence=['#FF4B4B'])
            fig.update_layout(xaxis_title="", yaxis_title="", height=250, margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No hay gastos registrados.")

    with c_chart2:
        st.subheader("Categorías")
        if not df.empty:
            df_cat = df[df['tipo'].isin(['GASTO', 'COMPRA_TARJETA'])].groupby('categoria')['monto'].sum().reset_index()
            if not df_cat.empty:
                fig_pie = px.pie(df_cat, values='monto', names='categoria', hole=0.5)
                fig_pie.update_layout(showlegend=False, height=250, margin=dict(l=0, r=0, t=0, b=0))
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.write("Sin consumos.")

elif menu == "➕ Cargar":
    st.header("Nueva Operación")
    
    tipo_op = st.segmented_control("Tipo", ["Gasto", "Ingreso", "Transferencia"], default="Gasto")
    
    with st.container(border=True):
        c1, c2 = st.columns(2)
        fecha = c1.date_input("Fecha", date.today())
        monto = c2.number_input("Monto ($)", min_value=1.0, step=100.0, format="%.2f")
        desc = st.text_input("Descripción", placeholder="Ej: Supermercado Coto")

        if tipo_op == "Gasto":
            c3, c4 = st.columns(2)
            cuenta = c3.selectbox("Medio de Pago", df_cuentas['nombre'])
            cat = c4.selectbox("Categoría", df_cats['nombre'])
            
            if st.button("Guardar Gasto", type="primary", use_container_width=True):
                id_cta = df_cuentas[df_cuentas['nombre'] == cuenta]['id'].values[0]
                id_cat = df_cats[df_cats['nombre'] == cat]['id'].values[0]
                es_credito = df_cuentas[df_cuentas['nombre'] == cuenta]['tipo'].values[0] == 'CREDITO'
                tipo_db = "COMPRA_TARJETA" if es_credito else "GASTO"
                
                guardar_movimiento(fecha, monto, desc, id_cta, id_cat, tipo_db)
                st.success("¡Gasto guardado!")
                time.sleep(1)
                st.rerun()

        elif tipo_op == "Ingreso":
            cuenta = st.selectbox("Destino", df_cuentas['nombre'])
            cat_nom = st.selectbox("Categoría", df_cats['nombre']) # Idealmente filtrar solo Ingresos
            if st.button("Guardar Ingreso", type="primary", use_container_width=True):
                id_cta = df_cuentas[df_cuentas['nombre'] == cuenta]['id'].values[0]
                id_cat = df_cats[df_cats['nombre'] == cat_nom]['id'].values[0]
                guardar_movimiento(fecha, monto, desc, id_cta, id_cat, "INGRESO")
                st.success("¡Ingreso guardado!")
                time.sleep(1)
                st.rerun()
                
        elif tipo_op == "Transferencia":
            c_orig, c_dest = st.columns(2)
            orig = c_orig.selectbox("Desde", df_cuentas['nombre'])
            dest = c_dest.selectbox("Hacia", df_cuentas['nombre'])
            
            if st.button("Transferir", type="primary", use_container_width=True):
                id_orig = df_cuentas[df_cuentas['nombre'] == orig]['id'].values[0]
                id_dest = df_cuentas[df_cuentas['nombre'] == dest]['id'].values[0]
                id_cat = df_cats.iloc[0]['id']
                guardar_movimiento(fecha, monto, f"Transferencia a {dest}", id_orig, id_cat, "TRANSFERENCIA", id_dest)
                st.success("Transferencia realizada!")
                time.sleep(1)
                st.rerun()

elif menu == "📝 Movimientos":
    st.header("Historial")
    st.info("💡 Doble click en una celda para editar.")
    
    if not df.empty:
        df_edit = df[['id', 'fecha', 'descripcion', 'monto', 'cuenta', 'categoria', 'tipo']].copy()
        
        edited_df = st.data_editor(
            df_edit,
            column_config={
                "id": None, # Ocultar ID
                "monto": st.column_config.NumberColumn("Monto", format="$%.2f"),
                "fecha": st.column_config.DateColumn("Fecha"),
                "tipo": st.column_config.SelectboxColumn("Tipo", options=["GASTO", "INGRESO", "COMPRA_TARJETA"]),
                "categoria": st.column_config.TextColumn("Categoría", disabled=True), # Bloqueado por ahora
                "cuenta": st.column_config.TextColumn("Cuenta", disabled=True),
            },
            hide_index=True,
            use_container_width=True,
            num_rows="dynamic",
            key="editor_movimientos"
        )
        
        if st.button("💾 Guardar Cambios"):
            cambios = st.session_state['editor_movimientos']
            
            # Updates
            for idx, updates in cambios['edited_rows'].items():
                rid = df_edit.iloc[idx]['id']
                for k, v in updates.items():
                    actualizar_movimiento(rid, k, v)
            
            # Deletes
            for idx in cambios['deleted_rows']:
                rid = df_edit.iloc[idx]['id']
                borrar_movimiento(rid)
                
            st.toast("¡Actualizado con éxito!")
            time.sleep(1)
            st.rerun()
    else:
        st.write("No hay datos para mostrar.")

elif menu == "⚙️ Ajustes":
    st.header("Configuración")
    with st.container(border=True):
        nuevo_sueldo = st.number_input("Sueldo Mensual Base", value=sueldo, step=10000.0)
        if st.button("Actualizar Sueldo"):
            supabase.table("configuracion").upsert({"clave": "sueldo_mensual", "valor": str(nuevo_sueldo)}).execute()
            st.success("Sueldo actualizado.")
            time.sleep(1)
            st.rerun()