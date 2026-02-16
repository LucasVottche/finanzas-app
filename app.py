import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
import plotly.express as px
import time

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Finanzas Personales", 
    page_icon="💳", 
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

# --- FUNCIONES DE FORMATO ARGENTINO ---
def fmt_ars(valor):
    if valor is None: valor = 0
    s = f"{valor:,.2f}"
    s = s.replace(',', 'X').replace('.', ',').replace('X', '.')
    if s.endswith(",00"): s = s[:-3]
    return f"${s}"

# --- FUNCIONES LOGICA TARJETA ---
def calcular_fecha_vencimiento(fecha_compra, dia_cierre, dia_vencimiento):
    """
    Calcula cuándo vence una compra basada en el cierre de la tarjeta.
    Ej: Cierre 23, Vto 5.
    Compra 15/02 (antes cierre) -> Vence 05/03
    Compra 25/02 (después cierre) -> Vence 05/04
    """
    if isinstance(fecha_compra, str):
        fecha_compra = datetime.strptime(fecha_compra, "%Y-%m-%d").date()
    
    # Fecha de cierre de ESTE mes de compra
    fecha_cierre_mes = date(fecha_compra.year, fecha_compra.month, dia_cierre)
    
    if fecha_compra <= fecha_cierre_mes:
        # Entra en el resumen del mes siguiente
        mes_vto = fecha_compra + relativedelta(months=1)
    else:
        # Entra en el resumen de 2 meses adelante
        mes_vto = fecha_compra + relativedelta(months=2)
        
    # Armamos la fecha final de vencimiento
    try:
        return date(mes_vto.year, mes_vto.month, dia_vencimiento)
    except ValueError:
        # Por si dia_vencimiento es 31 y el mes tiene 30
        return date(mes_vto.year, mes_vto.month, 28)

# --- BASE DE DATOS ---
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
            "*, categorias(nombre, icono), cuentas:cuentas!cuenta_id(nombre, tipo, dia_cierre, dia_vencimiento)"
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
                # Guardamos datos de cierre para calculos
                row['dia_cierre'] = d['cuentas'].get('dia_cierre', 23)
                row['dia_vencimiento'] = d['cuentas'].get('dia_vencimiento', 5)
            
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

# --- CARGA INICIAL ---
df_cuentas, df_cats, sueldo = get_data_maestros()

# --- SIDEBAR ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2382/2382461.png", width=50)
    st.title("Finanzas Pro")
    
    menu = st.radio("Menú Principal", 
        ["📊 Dashboard", "💳 Tarjetas", "📅 Planificador", "➕ Cargar Manual", "📝 Historial", "⚙️ Configuración"]
    )
    
    st.divider()
    st.caption("📅 Filtro Global")
    today = date.today()
    fecha_inicio = st.date_input("Desde", today.replace(day=1))
    fecha_fin = st.date_input("Hasta", today)

# ==========================================
# 1. DASHBOARD
# ==========================================
if menu == "📊 Dashboard":
    st.title("Tablero de Control")
    
    # Traemos movimientos
    df = get_movimientos_periodo(fecha_inicio, fecha_fin)
    
    # 1. Calcular VENCIMIENTOS DE TARJETA para este mes
    # (No lo que gastaste, sino lo que vence en el mes seleccionado en el filtro 'Hasta')
    total_a_pagar_tarjetas = 0
    detalles_tarjeta = []
    
    # Usamos el mes/año de la fecha "Hasta" como referencia de "Qué mes estoy pagando"
    mes_ref = fecha_fin.month
    anio_ref = fecha_fin.year
    
    # Necesitamos traer un rango más amplio de movimientos históricos para calcular vencimientos
    # (porque una compra de hace 45 días puede vencer hoy)
    df_historico_tj = get_movimientos_periodo(fecha_fin - relativedelta(months=3), fecha_fin)
    
    if not df_historico_tj.empty:
        # Filtramos solo compras con tarjeta
        df_tj_hist = df_historico_tj[df_historico_tj['tipo'] == 'COMPRA_TARJETA'].copy()
        
        if not df_tj_hist.empty:
            # Calculamos fecha de vencimiento real para cada compra
            df_tj_hist['fecha_vto_real'] = df_tj_hist.apply(
                lambda x: calcular_fecha_vencimiento(x['fecha'], x.get('dia_cierre', 23), x.get('dia_vencimiento', 5)), axis=1
            )
            
            # Filtramos las que vencen en el mes seleccionado
            df_vence_ahora = df_tj_hist[
                (pd.to_datetime(df_tj_hist['fecha_vto_real']).dt.month == mes_ref) & 
                (pd.to_datetime(df_tj_hist['fecha_vto_real']).dt.year == anio_ref)
            ]
            
            if not df_vence_ahora.empty:
                total_a_pagar_tarjetas = df_vence_ahora['monto'].sum()
                # Agrupamos por tarjeta para mostrar detalle
                por_tarjeta = df_vence_ahora.groupby('cuenta')['monto'].sum()
                for nombre, monto in por_tarjeta.items():
                    detalles_tarjeta.append(f"{nombre}: {fmt_ars(monto)}")
    
    # 2. Otros Cálculos
    gastos_efectivo = df[df['tipo'] == 'GASTO']['monto'].sum() if not df.empty else 0
    # Pagos de tarjeta ya realizados (Salida de plata real)
    pagos_tj_hechos = df[df['tipo'] == 'PAGO_TARJETA']['monto'].sum() if not df.empty else 0
    
    ingresos = df[df['tipo'] == 'INGRESO']['monto'].sum() if not df.empty else 0
    total_ingresos = sueldo + ingresos
    
    # Disponible = Ingresos - (Gastos Cash + Pagos ya hechos + Deuda que vence y no pagué)
    # Simplificación: Si ya pagué tarjeta (pagos_tj_hechos), se resta del total a pagar
    deuda_pendiente = max(0, total_a_pagar_tarjetas - pagos_tj_hechos)
    
    disponible_final = total_ingresos - gastos_efectivo - pagos_tj_hechos - deuda_pendiente

    # --- VISUALIZACION ---
    col1, col2, col3 = st.columns(3)
    
    with col1:
        with st.container(border=True):
            st.metric("💰 Disponible Real", fmt_ars(disponible_final), help="Después de pagar todo (incluso la tarjeta que vence)")
            st.caption(f"Ingresos Totales: {fmt_ars(total_ingresos)}")
            
    with col2:
        with st.container(border=True):
            st.metric("💳 Vencimientos Tarjeta", fmt_ars(total_a_pagar_tarjetas), help=f"Total a pagar en {mes_ref}/{anio_ref}")
            if detalles_tarjeta:
                for d in detalles_tarjeta:
                    st.caption(f"• {d}")
            else:
                st.caption("Nada vence este mes")
                
    with col3:
        with st.container(border=True):
            st.metric("💸 Gastos Efectivo/Deb", fmt_ars(gastos_efectivo))
            st.caption(f"Pagos Tarjeta ya hechos: {fmt_ars(pagos_tj_hechos)}")

    st.divider()
    
    # Gráfico de barras simple
    st.subheader("Evolución Diaria")
    if not df.empty:
        # Solo mostramos GASTO (cash) y PAGO_TARJETA (salida real de plata)
        df_chart = df[df['tipo'].isin(['GASTO', 'PAGO_TARJETA'])]
        if not df_chart.empty:
            df_grp = df_chart.groupby('fecha')['monto'].sum().reset_index()
            fig = px.bar(df_grp, x='fecha', y='monto', color_discrete_sequence=['#FF4B4B'])
            fig.update_layout(xaxis_title=None, yaxis_title=None, height=300)
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Sin datos para graficar.")

# ==========================================
# 2. TARJETAS (CONFIG Y CARGA)
# ==========================================
elif menu == "💳 Tarjetas":
    st.title("Gestión de Crédito")
    
    tab_conf, tab_imp = st.tabs(["⚙️ Configurar Fechas", "📥 Importar Resumen"])
    
    with tab_conf:
        st.subheader("Configurar Cierres y Vencimientos")
        st.info("Esto es vital para que el Dashboard calcule bien cuándo pagás.")
        
        df_credito = df_cuentas[df_cuentas['tipo'] == 'CREDITO']
        if not df_credito.empty:
            for i, row in df_credito.iterrows():
                with st.container(border=True):
                    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                    c1.markdown(f"### 💳 {row['nombre']}")
                    
                    # Inputs
                    d_cierre = c2.number_input(f"Día Cierre", 1, 31, int(row.get('dia_cierre') or 23), key=f"c_{row['id']}")
                    d_vto = c3.number_input(f"Día Vencimiento", 1, 31, int(row.get('dia_vencimiento') or 5), key=f"v_{row['id']}")
                    
                    if c4.button("Guardar", key=f"btn_{row['id']}"):
                        supabase.table("cuentas").update({
                            "dia_cierre": d_cierre,
                            "dia_vencimiento": d_vto
                        }).eq("id", row['id']).execute()
                        st.success(f"¡{row['nombre']} actualizada!")
                        time.sleep(1)
                        st.rerun()
        else:
            st.warning("No tenés cuentas tipo 'CREDITO'. Creala en Supabase o editá una existente.")

    with tab_imp:
        st.subheader("Importar Excel del Banco")
        st.caption("Sube el CSV o Excel. El sistema detectará las fechas y calculará los vencimientos automáticos.")
        
        uploaded = st.file_uploader("Archivo", type=['csv', 'xlsx'])
        if uploaded:
            # Seleccionar Tarjeta Destino
            tarjeta_dest = st.selectbox("¿A qué tarjeta corresponden estos gastos?", df_credito['nombre'].tolist())
            
            try:
                if uploaded.name.endswith('.csv'):
                    df_up = pd.read_csv(uploaded)
                else:
                    df_up = pd.read_excel(uploaded)
                
                st.write("Vista previa:", df_up.head(3))
                
                with st.form("form_import_tj"):
                    c1, c2, c3 = st.columns(3)
                    col_f = c1.selectbox("Columna Fecha", df_up.columns)
                    col_d = c2.selectbox("Columna Descripción", df_up.columns)
                    col_m = c3.selectbox("Columna Monto/Importe", df_up.columns)
                    cat_def = st.selectbox("Categoría por defecto", df_cats['nombre'].tolist())
                    
                    if st.form_submit_button("Procesar e Importar"):
                        id_tj = df_credito[df_credito['nombre'] == tarjeta_dest]['id'].values[0]
                        id_cat = df_cats[df_cats['nombre'] == cat_def]['id'].values[0]
                        count = 0
                        
                        for _, row in df_up.iterrows():
                            try:
                                # Parsear Fecha
                                f_raw = row[col_f]
                                if isinstance(f_raw, str):
                                    f_obj = pd.to_datetime(f_raw, dayfirst=True).date() # Intenta formato DD/MM/YYYY
                                else:
                                    f_obj = f_raw.date()
                                
                                # Parsear Monto
                                m_raw = row[col_m]
                                if isinstance(m_raw, str):
                                    m_raw = m_raw.replace('$','').replace('.','').replace(',','.')
                                monto = abs(float(m_raw))
                                
                                desc = str(row[col_d])
                                
                                if monto > 0:
                                    guardar_movimiento(f_obj, monto, desc, id_tj, id_cat, "COMPRA_TARJETA")
                                    count += 1
                            except Exception as e:
                                pass # Ignorar filas erróneas
                        
                        st.success(f"✅ Se importaron {count} compras correctamente.")
                        time.sleep(2)
            except Exception as e:
                st.error(f"Error leyendo el archivo: {e}")

# ==========================================
# 3. PLANIFICADOR
# ==========================================
elif menu == "📅 Planificador":
    st.title("Planificar Mes Futuro")
    
    with st.container(border=True):
        c_mes, c_anio = st.columns(2)
        next_m = date.today() + relativedelta(months=1)
        mes_sel = c_mes.selectbox("Mes", range(1, 13), index=next_m.month-1)
        anio_sel = c_anio.number_input("Año", value=next_m.year, step=1, format="%d")
        
        fecha_plan = date(anio_sel, mes_sel, 1)
        st.markdown(f"### Planificando: {fecha_plan.strftime('%B %Y')}")
        
        st.divider()
        st.subheader("1. Ingresos Estimados")
        ingreso_neto = st.number_input("Sueldo Neto a Cobrar", value=int(sueldo), step=1000, format="%i")
        cta_ing = st.selectbox("Cuenta Destino", df_cuentas['nombre'].tolist())
        
        st.divider()
        st.subheader("2. Gastos Fijos")
        
        if 'df_plan' not in st.session_state:
            st.session_state.df_plan = pd.DataFrame([
                {"Descripción": "Alquiler", "Monto": 0.0, "Categoría": "Varios", "Medio Pago": "Efectivo"},
                {"Descripción": "Internet", "Monto": 0.0, "Categoría": "Servicios", "Medio Pago": "Mercado Pago"},
            ])
            
        edited_plan = st.data_editor(
            st.session_state.df_plan,
            num_rows="dynamic",
            column_config={
                "Categoría": st.column_config.SelectboxColumn(options=df_cats['nombre'].tolist()), # .tolist() FIX
                "Medio Pago": st.column_config.SelectboxColumn(options=df_cuentas['nombre'].tolist()), # .tolist() FIX
                "Monto": st.column_config.NumberColumn(format="$%.2f")
            },
            use_container_width=True
        )
        
        total_fijos = edited_plan['Monto'].sum()
        saldo = ingreso_neto - total_fijos
        
        st.metric("💰 Saldo Proyectado (Sin contar tarjeta)", fmt_ars(saldo), delta=f"Fijos: {fmt_ars(total_fijos)}")
        
        if st.button("🚀 Guardar Plan", type="primary", use_container_width=True):
            # Guardar Ingreso
            id_cta = df_cuentas[df_cuentas['nombre'] == cta_ing]['id'].values[0]
            try: id_cat = df_cats[df_cats['nombre'].str.contains("Sueldo")]['id'].values[0]
            except: id_cat = df_cats.iloc[0]['id']
            
            guardar_movimiento(fecha_plan, ingreso_neto, "Sueldo Planificado", id_cta, id_cat, "INGRESO")
            
            # Guardar Gastos
            count = 0
            for _, r in edited_plan.iterrows():
                if r['Monto'] > 0:
                    c_id = df_cuentas[df_cuentas['nombre'] == r['Medio Pago']]['id'].values[0]
                    cat_id = df_cats[df_cats['nombre'] == r['Categoría']]['id'].values[0]
                    es_cr = df_cuentas[df_cuentas['nombre'] == r['Medio Pago']]['tipo'].values[0] == 'CREDITO'
                    tipo = "COMPRA_TARJETA" if es_cr else "GASTO"
                    
                    # Guardamos el día 5 del mes planificado
                    guardar_movimiento(fecha_plan + timedelta(days=4), r['Monto'], r['Descripción'], c_id, cat_id, tipo)
                    count += 1
            
            st.success(f"¡Plan guardado con éxito!")
            time.sleep(2)
            st.rerun()

# ==========================================
# 4. CARGA MANUAL
# ==========================================
elif menu == "➕ Cargar Manual":
    st.title("Nueva Operación")
    
    tipo_op = st.radio("Tipo", ["Gasto / Compra", "Ingreso", "Transferencia", "Pagar Tarjeta"], horizontal=True)
    
    with st.container(border=True):
        c1, c2 = st.columns(2)
        fecha = c1.date_input("Fecha", date.today())
        monto = c2.number_input("Monto", min_value=1.0, step=100.0, format="%.2f")
        desc = st.text_input("Descripción", placeholder="Ej: Supermercado")

        if tipo_op == "Gasto / Compra":
            c3, c4 = st.columns(2)
            cta = c3.selectbox("Medio de Pago", df_cuentas['nombre'].tolist())
            cat = c4.selectbox("Categoría", df_cats['nombre'].tolist())
            
            if st.button("Guardar Gasto", type="primary", use_container_width=True):
                id_c = df_cuentas[df_cuentas['nombre'] == cta]['id'].values[0]
                id_cat = df_cats[df_cats['nombre'] == cat]['id'].values[0]
                es_cr = df_cuentas[df_cuentas['nombre'] == cta]['tipo'].values[0] == 'CREDITO'
                tipo_db = "COMPRA_TARJETA" if es_cr else "GASTO"
                guardar_movimiento(fecha, monto, desc, id_c, id_cat, tipo_db)
                st.success("Guardado!"); time.sleep(1); st.rerun()

        elif tipo_op == "Ingreso":
            cta = st.selectbox("Cuenta Destino", df_cuentas['nombre'].tolist())
            cat = st.selectbox("Rubro", df_cats['nombre'].tolist())
            if st.button("Guardar Ingreso", type="primary", use_container_width=True):
                id_c = df_cuentas[df_cuentas['nombre'] == cta]['id'].values[0]
                id_cat = df_cats[df_cats['nombre'] == cat]['id'].values[0]
                guardar_movimiento(fecha, monto, desc, id_c, id_cat, "INGRESO")
                st.success("Guardado!"); time.sleep(1); st.rerun()

        elif tipo_op == "Transferencia":
            orig = st.selectbox("Desde", df_cuentas['nombre'].tolist())
            dest = st.selectbox("Hacia", df_cuentas['nombre'].tolist())
            if st.button("Transferir", type="primary", use_container_width=True):
                id_o = df_cuentas[df_cuentas['nombre'] == orig]['id'].values[0]
                id_d = df_cuentas[df_cuentas['nombre'] == dest]['id'].values[0]
                id_cat = df_cats.iloc[0]['id']
                guardar_movimiento(fecha, monto, f"Transferencia a {dest}", id_o, id_cat, "TRANSFERENCIA", id_d)
                st.success("Transferido!"); time.sleep(1); st.rerun()
        
        elif tipo_op == "Pagar Tarjeta":
            st.info("Registra el pago del resumen de la tarjeta (salida de plata de tu banco).")
            orig = st.selectbox("Pagar desde (Banco/Efvo)", df_cuentas[df_cuentas['tipo'] != 'CREDITO']['nombre'].tolist())
            dest = st.selectbox("Qué Tarjeta Pagaste", df_cuentas[df_cuentas['tipo'] == 'CREDITO']['nombre'].tolist())
            
            if st.button("Registrar Pago Tarjeta", type="primary", use_container_width=True):
                id_o = df_cuentas[df_cuentas['nombre'] == orig]['id'].values[0]
                id_d = df_cuentas[df_cuentas['nombre'] == dest]['id'].values[0]
                id_cat = df_cats.iloc[0]['id'] # Categoria varios o default
                guardar_movimiento(fecha, monto, f"Pago Resumen {dest}", id_o, id_cat, "PAGO_TARJETA", id_d)
                st.success("Pago Registrado!"); time.sleep(1); st.rerun()

# ==========================================
# 5. HISTORIAL
# ==========================================
elif menu == "📝 Historial":
    st.title("Base de Datos")
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
            hide_index=True, use_container_width=True, num_rows="dynamic", key="movs_edit"
        )
        if st.button("💾 Guardar Cambios"):
            cambios = st.session_state['movs_edit']
            for i, u in cambios['edited_rows'].items():
                rid = df_edit.iloc[i]['id']
                for k, v in u.items(): actualizar_movimiento(rid, k, v)
            for i in cambios['deleted_rows']:
                rid = df_edit.iloc[i]['id']
                borrar_movimiento(rid)
            st.toast("Base actualizada"); time.sleep(1); st.rerun()

# ==========================================
# 6. CONFIGURACION
# ==========================================
elif menu == "⚙️ Configuración":
    st.header("Ajustes Generales")
    with st.container(border=True):
        nuevo = st.number_input("Sueldo Base Mensual", value=int(sueldo), step=1000, format="%i")
        if st.button("Actualizar Sueldo"):
            supabase.table("configuracion").upsert({"clave": "sueldo_mensual", "valor": str(nuevo)}).execute()
            st.success("Guardado!"); time.sleep(1); st.rerun()