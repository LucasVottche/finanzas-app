import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import date, timedelta, datetime
import plotly.express as px

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Finanzas Personales", page_icon="💰", layout="wide")

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

# --- FUNCIONES DE BASE DE DATOS ---
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
    try:
        # CORRECCIÓN IMPORTANTE: "cuentas!cuenta_id" soluciona el error de ambigüedad
        resp = supabase.table("movimientos").select(
            "*, categorias(nombre, icono), cuentas:cuentas!cuenta_id(nombre, tipo)"
        ).gte("fecha", desde).lte("fecha", hasta).execute()
        
        data = resp.data
        if not data:
            return pd.DataFrame()
        
        rows = []
        for d in data:
            row = d.copy()
            # Aplanar Categoría
            if d.get('categorias'):
                row['categoria'] = f"{d['categorias']['icono']} {d['categorias']['nombre']}"
            else:
                row['categoria'] = "General"
            
            # Aplanar Cuenta
            if d.get('cuentas'):
                row['cuenta'] = d['cuentas']['nombre']
                row['cuenta_tipo'] = d['cuentas']['tipo']
            
            # Limpiar
            row.pop('categorias', None)
            row.pop('cuentas', None)
            rows.append(row)
            
        return pd.DataFrame(rows)
        
    except Exception as e:
        st.error(f"Error trayendo datos: {e}")
        return pd.DataFrame()

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

menu = st.sidebar.selectbox("Menú", 
    ["📊 Dashboard", "📝 Cargar", "📥 Importar CSV", "⚙️ Configuración"]
)

# Filtro de Fechas
st.sidebar.divider()
col_f1, col_f2 = st.sidebar.columns(2)
fecha_inicio = col_f1.date_input("Desde", date.today().replace(day=1))
fecha_fin = col_f2.date_input("Hasta", date.today())

# Carga de Datos
df = get_movimientos(fecha_inicio, fecha_fin)
df_cuentas = get_cuentas()
df_cats = get_categorias()
sueldo = get_config("sueldo_mensual")

if menu == "📊 Dashboard":
    st.title(f"Resumen del Mes")

    if df.empty:
        st.info("No hay movimientos cargados en estas fechas.")
        # Mostramos al menos el sueldo
        st.metric("💰 Sueldo Base", f"${sueldo:,.0f}")
    else:
        # --- CÁLCULOS ---
        # Salidas reales de dinero (Efectivo/Debito + Pagos Tarjeta)
        gastos_reales = df[df['tipo'].isin(['GASTO', 'PAGO_TARJETA'])]['monto'].sum()
        
        # Deuda de tarjeta (Compras crédito)
        consumo_tarjeta = df[df['tipo'] == 'COMPRA_TARJETA']['monto'].sum()
        
        # Ingresos extra (Aguinaldo, ventas, etc)
        ingresos_extra = df[df['tipo'] == 'INGRESO']['monto'].sum()

        # Disponible REAL
        # (Sueldo + Extras) - (Lo que ya salió de tu cuenta)
        total_ingresos = sueldo + ingresos_extra
        disponible = total_ingresos - gastos_reales

        # --- KPIs (¡Acá volví a poner el Sueldo!) ---
        c1, c2, c3, c4 = st.columns(4)
        
        c1.metric("💰 Sueldo Base", f"${sueldo:,.0f}")
        c2.metric("📥 Ingresos Extra", f"${ingresos_extra:,.0f}")
        c3.metric("💸 Gastos Totales", f"${gastos_reales:,.0f}", help="Incluye gastos en efectivo/débito y pagos de tarjeta realizados")
        
        # El disponible lo destacamos
        c4.metric("✅ Disponible Hoy", f"${disponible:,.0f}", delta=f"Deuda Tarjeta: -${consumo_tarjeta:,.0f}")

        # --- GRÁFICOS ---
        col_g1, col_g2 = st.columns([2, 1])
        
        with col_g1:
            st.subheader("En qué se fue la plata")
            # Filtramos GASTO y COMPRA_TARJETA para ver el consumo real por rubro
            df_consumo = df[df['tipo'].isin(['GASTO', 'COMPRA_TARJETA'])]
            
            if not df_consumo.empty:
                gastos_por_cat = df_consumo.groupby('categoria')['monto'].sum().reset_index()
                fig = px.pie(gastos_por_cat, values='monto', names='categoria', hole=0.4)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.write("Sin datos de consumo.")

        with col_g2:
            st.subheader("Presupuestos")
            # Semáforo de gastos
            if not df_consumo.empty and not df_cats.empty:
                gastos_cat = df_consumo.groupby('categoria_id')['monto'].sum()
                for _, cat in df_cats.iterrows():
                    presupuesto = cat.get('presupuesto_mensual', 0) or 0
                    if presupuesto > 0:
                        gasto = gastos_cat.get(cat['id'], 0)
                        pct = min(gasto / presupuesto, 1.0)
                        color = "red" if gasto > presupuesto else "green"
                        st.write(f"{cat['icono']} {cat['nombre']}")
                        st.progress(pct)
                        st.caption(f"${gasto:,.0f} / ${presupuesto:,.0f}")

        # --- DETALLE ---
        st.divider()
        st.subheader("Últimos Movimientos")
        st.dataframe(
            df[['fecha', 'descripcion', 'monto', 'cuenta', 'categoria', 'tipo']].sort_values('fecha', ascending=False),
            use_container_width=True,
            hide_index=True
        )

elif menu == "📝 Cargar":
    st.header("Cargar Operación")
    
    tipo_op = st.radio("Tipo", ["Gasto / Compra", "Ingreso", "Transferencia", "Pagar Tarjeta"], horizontal=True)
    
    with st.form("form_carga"):
        col1, col2 = st.columns(2)
        fecha = col1.date_input("Fecha", date.today())
        monto = col2.number_input("Monto", min_value=1.0, step=100.0)
        desc = st.text_input("Descripción (Opcional)")
        
        # Lógica dinámica según tipo
        if tipo_op == "Transferencia":
            origen = col1.selectbox("Desde", df_cuentas['nombre'])
            destino = col2.selectbox("Hacia", df_cuentas['nombre'])
            cat_id = df_cats.iloc[0]['id'] # Default
            tipo_db = "TRANSFERENCIA"
        
        elif tipo_op == "Pagar Tarjeta":
            # Pagás desde una cuenta débito a una crédito (generalmente)
            origen = col1.selectbox("Pagar desde (Debito/Efvo)", df_cuentas[df_cuentas['tipo'] != 'CREDITO']['nombre'])
            destino = col2.selectbox("Qué Tarjeta (Destino)", df_cuentas[df_cuentas['tipo'] == 'CREDITO']['nombre'])
            cat_id = df_cats.iloc[0]['id']
            tipo_db = "PAGO_TARJETA" # En realidad es una transferencia especial que baja deuda

        else: # Gasto o Ingreso
            destino = None
            if tipo_op == "Gasto / Compra":
                cuenta = col1.selectbox("Medio de Pago", df_cuentas['nombre'])
                # Si es tarjeta de crédito -> COMPRA_TARJETA, sino GASTO
                es_credito = df_cuentas[df_cuentas['nombre'] == cuenta]['tipo'].values[0] == 'CREDITO'
                tipo_db = "COMPRA_TARJETA" if es_credito else "GASTO"
            else:
                cuenta = col1.selectbox("Cuenta Destino", df_cuentas['nombre'])
                tipo_db = "INGRESO"
            
            cat_nom = col2.selectbox("Categoría", df_cats['nombre'])
            cat_id = df_cats[df_cats['nombre'] == cat_nom]['id'].values[0]
            origen = cuenta # Para unificar variable
            
        if st.form_submit_button("Guardar Operación"):
            # Obtener IDs
            id_origen = df_cuentas[df_cuentas['nombre'] == origen]['id'].values[0]
            id_destino = None
            if tipo_op in ["Transferencia", "Pagar Tarjeta"]:
                id_destino = df_cuentas[df_cuentas['nombre'] == destino]['id'].values[0]
            
            guardar_movimiento(fecha, monto, desc, id_origen, cat_id, tipo_db, id_destino)
            st.success("✅ Guardado correctamente")
            st.rerun()

elif menu == "📥 Importar CSV":
    st.header("Importador Inteligente")
    st.info("Subí el CSV de Mercado Pago o Santander tal cual te lo descargás.")
    uploaded_file = st.file_uploader("Arrastrá el archivo acá", type=["csv"])
    
    if uploaded_file:
        df_csv = pd.read_csv(uploaded_file)
        st.write("Columnas detectadas:", list(df_csv.columns))
        # Acá iría la lógica de parseo que te pasé antes...
        st.warning("⚠️ Recordá seleccionar la cuenta correcta antes de procesar.")
        cuenta_dest = st.selectbox("Asignar a cuenta:", df_cuentas['nombre'])
        
        if st.button("Procesar"):
            # Lógica simplificada de importación
            id_cta = df_cuentas[df_cuentas['nombre'] == cuenta_dest]['id'].values[0]
            cat_def = df_cats.iloc[0]['id']
            count = 0
            
            cols = [c.lower() for c in df_csv.columns]
            for _, row in df_csv.iterrows():
                try:
                    # Intento Santander
                    if 'importe' in cols and 'sucursal' in cols:
                        monto = abs(float(row['Importe'] if isinstance(row['Importe'], (int, float)) else row['Importe'].replace('$','').replace('.','').replace(',','.')))
                        desc = str(row.get('Descripción', 'Importado'))
                        guardar_movimiento(date.today(), monto, desc, id_cta, cat_def, "GASTO")
                        count += 1
                    # Intento MP (Ajustar según CSV real)
                    elif 'importe' in cols: 
                        monto = abs(float(row['Importe']))
                        desc = str(row.get('Descripción', 'Importado'))
                        guardar_movimiento(date.today(), monto, desc, id_cta, cat_def, "GASTO")
                        count += 1
                except:
                    pass
            st.success(f"Importados {count} movimientos.")

elif menu == "⚙️ Configuración":
    st.header("Ajustes")
    
    nuevo = st.number_input("Sueldo Mensual Base", value=sueldo)
    if st.button("Guardar Sueldo"):
        supabase.table("configuracion").upsert({"clave": "sueldo_mensual", "valor": str(nuevo)}).execute()
        st.success("Guardado!")
        st.rerun()