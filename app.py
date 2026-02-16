import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import date, timedelta, datetime
import plotly.express as px
import plotly.graph_objects as go

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Finanzas Personales Pro", page_icon="💰", layout="wide")

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

# --- FUNCIONES DE BASE DE DATOS (Optimizadas) ---
def get_cuentas():
    return pd.DataFrame(supabase.table("cuentas").select("*").execute().data)

def get_categorias():
    return pd.DataFrame(supabase.table("categorias").select("*").execute().data)

def get_config(clave):
    try:
        resp = supabase.table("configuracion").select("valor").eq("clave", clave).execute()
        return float(resp.data[0]['valor']) if resp.data else 0.0
    except:
        return 0.0

def get_movimientos(desde, hasta):
    # Query filtrada por fecha (Backend filtering)
    resp = supabase.table("movimientos").select(
        "*, categorias(nombre, icono), cuentas(nombre, tipo)"
    ).gte("fecha", desde).lte("fecha", hasta).execute()
    
    data = resp.data
    if not data:
        return pd.DataFrame()
    
    # Aplanar JSON (Join manual simple)
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
        del row['categorias']
        del row['cuentas']
        rows.append(row)
        
    return pd.DataFrame(rows)

def guardar_movimiento(fecha, monto, desc, cuenta_id, cat_id, tipo, destino_id=None):
    payload = {
        "fecha": str(fecha),
        "monto": monto,
        "descripcion": desc,
        "cuenta_id": cuenta_id,
        "categoria_id": cat_id,
        "tipo": tipo
    }
    if destino_id:
        payload["cuenta_destino_id"] = destino_id
        
    supabase.table("movimientos").insert(payload).execute()

# --- INTERFAZ ---

menu = st.sidebar.selectbox("Navegación", 
    ["📊 Dashboard", "📝 Cargar / Transferir", "📥 Importar CSV", "⚙️ Configuración"]
)

# Filtro Global de Fechas en Sidebar
st.sidebar.divider()
st.sidebar.header("📅 Periodo")
col_f1, col_f2 = st.sidebar.columns(2)
fecha_inicio = col_f1.date_input("Desde", date.today().replace(day=1))
fecha_fin = col_f2.date_input("Hasta", date.today())

# Cargar datos globales
df = get_movimientos(fecha_inicio, fecha_fin)
df_cuentas = get_cuentas()
df_cats = get_categorias()
sueldo = get_config("sueldo_mensual")

if menu == "📊 Dashboard":
    st.title(f"Balance: {fecha_inicio.strftime('%d/%m')} al {fecha_fin.strftime('%d/%m')}")

    if df.empty:
        st.info("No hay movimientos en este rango de fechas.")
    else:
        # --- LÓGICA FINANCIERA ---
        # 1. Gastos Reales (Salida de dinero: Efectivo/Debito + Pagos de Tarjeta)
        gastos_cash = df[df['tipo'] == 'GASTO']['monto'].sum()
        pagos_tarjeta = df[df['tipo'] == 'PAGO_TARJETA']['monto'].sum()
        total_salidas = gastos_cash + pagos_tarjeta
        
        # 2. Deuda Generada (Compras con tarjeta que aun no pagaste necesariamente)
        consumos_tarjeta = df[df['tipo'] == 'COMPRA_TARJETA']['monto'].sum()
        
        # 3. Ingresos
        ingresos = df[df['tipo'] == 'INGRESO']['monto'].sum()

        # 4. Cálculos
        disponible = sueldo + ingresos - total_salidas
        pct_gastado = (total_salidas / (sueldo + ingresos)) * 100 if (sueldo + ingresos) > 0 else 0

        # --- KPIs ---
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("💰 Disponible (Cash)", f"${disponible:,.0f}")
        c2.metric("💸 Salidas Reales", f"${total_salidas:,.0f}", delta=f"{pct_gastado:.1f}% del ingreso")
        c3.metric("💳 Tarjeta (Deuda Mes)", f"${consumos_tarjeta:,.0f}", help="Esto es lo que compraste a crédito este mes.")
        c4.metric("📥 Ingresos Extra", f"${ingresos:,.0f}")

        # --- GRÁFICOS ---
        col_g1, col_g2 = st.columns([2, 1])
        
        with col_g1:
            st.subheader("🛒 Gastos por Categoría")
            # Unimos compras tarjeta + gastos efectivo para ver "En qué consumo"
            df_consumo = df[df['tipo'].isin(['GASTO', 'COMPRA_TARJETA'])]
            
            if not df_consumo.empty:
                gastos_por_cat = df_consumo.groupby('categoria')['monto'].sum().reset_index()
                fig = px.pie(gastos_por_cat, values='monto', names='categoria', hole=0.4)
                fig.update_traces(textposition='inside', textinfo='percent+label')
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.write("Sin consumos.")

        with col_g2:
            st.subheader("⚠️ Alertas de Presupuesto")
            # Calcular gastos por categoría vs Presupuesto
            if not df_consumo.empty and not df_cats.empty:
                # Merge manual para performance
                gastos_cat_id = df_consumo.groupby('categoria_id')['monto'].sum()
                
                for _, cat in df_cats.iterrows():
                    presupuesto = cat['presupuesto_mensual'] or 0
                    if presupuesto > 0:
                        gasto_real = gastos_cat_id.get(cat['id'], 0)
                        pct = gasto_real / presupuesto
                        
                        st.write(f"**{cat['icono']} {cat['nombre']}**")
                        st.progress(min(pct, 1.0))
                        if pct > 1:
                            st.caption(f"❌ Te pasaste: ${gasto_real:,.0f} / ${presupuesto:,.0f}")
                        else:
                            st.caption(f"✅ ${gasto_real:,.0f} / ${presupuesto:,.0f}")

        # --- TABLA ÚLTIMOS MOVIMIENTOS ---
        st.subheader("📝 Detalle de Movimientos")
        st.dataframe(
            df[['fecha', 'descripcion', 'monto', 'tipo', 'cuenta', 'categoria']].sort_values('fecha', ascending=False),
            use_container_width=True,
            hide_index=True
        )

elif menu == "📝 Cargar / Transferir":
    st.title("Nueva Operación")
    
    tab1, tab2 = st.tabs(["Gasto / Ingreso", "Transferencia entre Cuentas"])
    
    with tab1:
        with st.form("form_gasto"):
            col1, col2 = st.columns(2)
            fecha = col1.date_input("Fecha", date.today())
            monto = col2.number_input("Monto", min_value=1.0, step=100.0)
            desc = st.text_input("Descripción")
            
            c_tipo = col1.selectbox("Tipo", ["GASTO", "COMPRA_TARJETA", "INGRESO", "PAGO_TARJETA"])
            
            # Filtro inteligente de cuentas
            if c_tipo in ["COMPRA_TARJETA"]:
                cuentas_filtradas = df_cuentas[df_cuentas['tipo'] == 'CREDITO']
            else:
                cuentas_filtradas = df_cuentas # Todas
                
            cuenta_nom = col2.selectbox("Cuenta", cuentas_filtradas['nombre'])
            cuenta_id = cuentas_filtradas[cuentas_filtradas['nombre'] == cuenta_nom]['id'].values[0]
            
            cat_nom = st.selectbox("Categoría", df_cats['nombre'])
            cat_id = df_cats[df_cats['nombre'] == cat_nom]['id'].values[0]
            
            if st.form_submit_button("Guardar"):
                guardar_movimiento(fecha, monto, desc, cuenta_id, cat_id, c_tipo)
                st.success("Guardado!")
                st.rerun()

    with tab2:
        st.write("Mover plata entre tus cuentas (No afecta balance, solo saldos)")
        with st.form("form_transfer"):
            col1, col2 = st.columns(2)
            monto_t = col1.number_input("Monto a Transferir", min_value=1.0)
            fecha_t = col2.date_input("Fecha Transferencia", date.today())
            
            origen = col1.selectbox("Desde (Origen)", df_cuentas['nombre'], key="orig")
            destino = col2.selectbox("Hacia (Destino)", df_cuentas['nombre'], key="dest")
            
            if st.form_submit_button("Realizar Transferencia"):
                if origen == destino:
                    st.error("El origen y destino no pueden ser iguales.")
                else:
                    id_orig = df_cuentas[df_cuentas['nombre'] == origen]['id'].values[0]
                    id_dest = df_cuentas[df_cuentas['nombre'] == destino]['id'].values[0]
                    # Usamos una categoría 'Varios' o creamos una 'Transferencia'
                    cat_def = df_cats.iloc[0]['id'] 
                    
                    guardar_movimiento(fecha_t, monto_t, f"Transferencia a {destino}", id_orig, cat_def, "TRANSFERENCIA", id_dest)
                    st.success(f"Transferido ${monto_t} de {origen} a {destino}")

elif menu == "📥 Importar CSV":
    st.title("Importación Masiva")
    st.info("Soporta CSV de Mercado Pago y Santander (Formato estándar)")
    
    uploaded_file = st.file_uploader("Subí tu archivo CSV", type=["csv"])
    
    if uploaded_file:
        try:
            df_csv = pd.read_csv(uploaded_file)
            st.write("Vista previa:", df_csv.head())
            
            col_map, col_act = st.columns(2)
            cuenta_destino = col_map.selectbox("A qué cuenta asignar:", df_cuentas['nombre'])
            id_cuenta_csv = df_cuentas[df_cuentas['nombre'] == cuenta_destino]['id'].values[0]
            
            if col_act.button("Procesar e Importar"):
                # Lógica simple de detección de columnas
                count = 0
                cols = [c.lower() for c in df_csv.columns]
                
                # Default Cat
                cat_default = df_cats.iloc[0]['id']
                
                for index, row in df_csv.iterrows():
                    # Adaptar según tu CSV real
                    monto = 0
                    desc = "Importado"
                    fecha = date.today()
                    
                    # Intento MP
                    if 'importe' in cols and 'descripción' in cols: 
                        monto = abs(float(row['Importe'])) # MP usa negativo para gastos
                        desc = row['Descripción']
                    
                    # Intento Santander
                    elif 'importe' in cols and 'sucursal' in cols:
                        monto = abs(float(row['Importe'])) # Limpiar $ si hace falta
                        desc = str(row['Referencia']) + " " + str(row['Descripción'])

                    # Guardar si hay monto
                    if monto > 0:
                        tipo = "GASTO" # Asumimos gasto por defecto en importación
                        # Podrías agregar lógica si monto > 0 es ingreso en el CSV
                        
                        guardar_movimiento(fecha, monto, desc, id_cuenta_csv, cat_default, tipo)
                        count += 1
                
                st.success(f"Se importaron {count} movimientos correctamente.")
                
        except Exception as e:
            st.error(f"Error procesando CSV: {e}")

elif menu == "⚙️ Configuración":
    st.header("Configuración de Presupuestos")
    
    with st.form("conf_sueldo"):
        nuevo_sueldo = st.number_input("Sueldo Mensual", value=sueldo)
        if st.form_submit_button("Actualizar Sueldo"):
            supabase.table("configuracion").upsert({"clave": "sueldo_mensual", "valor": str(nuevo_sueldo)}).execute()
            st.success("Actualizado")
            st.rerun()
            
    st.subheader("Presupuestos por Categoría")
    # Edición rápida de presupuestos
    df_cats_edit = df_cats[['id', 'nombre', 'icono', 'presupuesto_mensual']].copy()
    
    # Usamos data editor de Streamlit (Editable Grid)
    edited_df = st.data_editor(df_cats_edit, column_config={
        "id": None, # Ocultar ID
        "presupuesto_mensual": st.column_config.NumberColumn("Presupuesto Max", format="$%d")
    })
    
    if st.button("Guardar Presupuestos"):
        for index, row in edited_df.iterrows():
            supabase.table("categorias").update({"presupuesto_mensual": row['presupuesto_mensual']}).eq("id", row['id']).execute()
        st.success("Presupuestos actualizados!")