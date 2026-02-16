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

# --- FUNCIONES DE FORMATO ---
def fmt_ars(valor):
    if valor is None: valor = 0
    s = f"{valor:,.2f}"
    s = s.replace(',', 'X').replace('.', ',').replace('X', '.')
    if s.endswith(",00"): s = s[:-3]
    return f"${s}"

# --- LOGICA TARJETAS ---
def calcular_fecha_vencimiento(fecha_compra, dia_cierre, dia_vencimiento):
    if isinstance(fecha_compra, str):
        fecha_compra = datetime.strptime(fecha_compra, "%Y-%m-%d").date()
    
    try:
        fecha_cierre_mes = date(fecha_compra.year, fecha_compra.month, int(dia_cierre))
    except ValueError:
        fecha_cierre_mes = date(fecha_compra.year, fecha_compra.month, 28)
    
    if fecha_compra <= fecha_cierre_mes:
        mes_vto = fecha_compra + relativedelta(months=1)
    else:
        mes_vto = fecha_compra + relativedelta(months=2)
        
    try:
        return date(mes_vto.year, mes_vto.month, int(dia_vencimiento))
    except ValueError:
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
        # Traemos un margen extra para capturar compras de tarjeta que vencen en el periodo
        desde_ext = desde - relativedelta(months=3)
        resp = supabase.table("movimientos").select(
            "*, categorias(nombre, icono), cuentas:cuentas!cuenta_id(nombre, tipo, dia_cierre, dia_vencimiento)"
        ).gte("fecha", desde_ext).lte("fecha", hasta).order("fecha", desc=True).execute()
        
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
                row['dia_cierre'] = d['cuentas'].get('dia_cierre', 23)
                row['dia_vencimiento'] = d['cuentas'].get('dia_vencimiento', 5)
            
            del row['categorias'], row['cuentas']
            rows.append(row)
        
        df = pd.DataFrame(rows)
        if not df.empty and 'fecha' in df.columns:
            df['fecha'] = pd.to_datetime(df['fecha']).dt.date
        return df
    except:
        return pd.DataFrame()

def guardar_movimiento(fecha, monto, desc, cuenta_id, cat_id, tipo, destino_id=None):
    payload = {
        "fecha": str(fecha), "monto": monto, "descripcion": desc,
        "cuenta_id": cuenta_id, "categoria_id": cat_id, "tipo": tipo
    }
    if destino_id: payload["cuenta_destino_id"] = destino_id
    supabase.table("movimientos").insert(payload).execute()

# --- CARGA INICIAL ---
df_cuentas, df_cats, sueldo = get_data_maestros()

# --- SIDEBAR ---
with st.sidebar:
    st.title("Finanzas Pro")
    menu = st.radio("Menú", ["📊 Dashboard", "💳 Tarjetas", "📅 Planificador", "➕ Cargar Manual", "📝 Historial"])
    st.divider()
    st.caption("📅 Mes a Visualizar")
    today = date.today()
    # Cambiamos a selectores de mes/año para que sea más fácil para el usuario
    sel_mes = st.selectbox("Mes", range(1, 13), index=today.month - 1)
    sel_anio = st.number_input("Año", value=today.year, step=1)
    
    fecha_inicio = date(sel_anio, sel_mes, 1)
    fecha_fin = fecha_inicio + relativedelta(months=1) - timedelta(days=1)

# ==========================================
# 1. DASHBOARD (Sincronizado con el Plan)
# ==========================================
if menu == "📊 Dashboard":
    st.title(f"Balance de {fecha_inicio.strftime('%B %Y')}")
    
    df_todo = get_movimientos_periodo(fecha_inicio, fecha_fin)
    
    if not df_todo.empty:
        # 1. Gastos Reales y Planificados del periodo (No Tarjeta)
        # Filtramos solo lo que ocurre DENTRO del mes seleccionado
        df_mes = df_todo[(df_todo['fecha'] >= fecha_inicio) & (df_todo['fecha'] <= fecha_fin)]
        
        ingresos = df_mes[df_mes['tipo'] == 'INGRESO']['monto'].sum()
        gastos_cash = df_mes[df_mes['tipo'] == 'GASTO']['monto'].sum()
        pagos_tj_realizados = df_mes[df_mes['tipo'] == 'PAGO_TARJETA']['monto'].sum()
        
        # 2. Vencimientos de Tarjeta que caen en este mes
        total_vence_tj = 0
        df_tj = df_todo[df_todo['tipo'] == 'COMPRA_TAR_JETA'] if 'tipo' in df_todo else pd.DataFrame()
        # Nota: el tag 'COMPRA_TARJETA' es el que usamos
        df_tj = df_todo[df_todo['tipo'] == 'COMPRA_TARJETA']
        
        detalles_tj = []
        if not df_tj.empty:
            df_tj['vto'] = df_tj.apply(lambda x: calcular_fecha_vencimiento(x['fecha'], x['dia_cierre'], x['dia_vencimiento']), axis=1)
            # Solo compras que vencen en el mes visualizado
            vencen_hoy = df_tj[(df_tj['vto'] >= fecha_inicio) & (df_tj['vto'] <= fecha_fin)]
            total_vence_tj = vencen_hoy['monto'].sum()
            if not vencen_hoy.empty:
                por_t = vencen_hoy.groupby('cuenta')['monto'].sum()
                for n, m in por_t.items(): detalles_tj.append(f"{n}: {fmt_ars(m)}")

        # 3. Cálculo de Disponible
        # Ingresos - Gastos Cash - Lo que hay que pagar de tarjeta
        disponible = ingresos - gastos_cash - total_vence_tj
        
        c1, c2, c3 = st.columns(3)
        with c1:
            with st.container(border=True):
                st.metric("💰 Proyección Disponible", fmt_ars(disponible))
                st.caption(f"Ingresos: {fmt_ars(ingresos)}")
        with c2:
            with st.container(border=True):
                st.metric("💳 Vencen en el Mes", fmt_ars(total_vence_tj))
                for d in detalles_tj: st.caption(d)
        with c3:
            with st.container(border=True):
                st.metric("💸 Gastos Planificados/Reales", fmt_ars(gastos_cash))
                st.caption(f"Pagos ya hechos: {fmt_ars(pagos_tj_realizados)}")

        st.divider()
        # Gráfico
        df_grp = df_mes[df_mes['tipo'].isin(['GASTO', 'INGRESO'])].groupby('fecha')['monto'].sum().reset_index()
        if not df_grp.empty:
            fig = px.line(df_grp, x='fecha', y='monto', title="Flujo del Mes")
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No hay datos cargados ni planificados para este mes.")

# ==========================================
# 3. PLANIFICADOR
# ==========================================
elif menu == "📅 Planificador":
    st.title("Planificar Mes Futuro")
    # El planificador permite cargar datos a futuro que el Dashboard leerá
    with st.container(border=True):
        c_m, c_a = st.columns(2)
        mes_p = c_m.selectbox("Mes a Planificar", range(1, 13), index=sel_mes-1)
        anio_p = c_a.number_input("Año a Planificar", value=sel_anio)
        f_p = date(anio_p, mes_p, 1)
        
        st.write(f"Cargando gastos para {f_p.strftime('%B %Y')}")
        ing = st.number_input("Sueldo Estimado", value=int(sueldo))
        
        if 'df_p' not in st.session_state:
            st.session_state.df_p = pd.DataFrame([{"Descripción": "Alquiler", "Monto": 0.0, "Categoría": "Varios", "Medio Pago": "Efectivo"}])
        
        edit_p = st.data_editor(st.session_state.df_p, num_rows="dynamic", width="stretch",
            column_config={
                "Categoría": st.column_config.SelectboxColumn(options=df_cats['nombre'].tolist()),
                "Medio Pago": st.column_config.SelectboxColumn(options=df_cuentas['nombre'].tolist())
            })
        
        if st.button("Guardar Planificación", type="primary"):
            # Guardar el sueldo
            c_id = df_cuentas[df_cuentas['nombre'] == "Mercado Pago"]['id'].values[0] # O el que elijas
            guardar_movimiento(f_p, ing, "Sueldo Planificado", c_id, df_cats.iloc[0]['id'], "INGRESO")
            
            # Guardar gastos
            for _, r in edit_p.iterrows():
                if r['Monto'] > 0:
                    mid = df_cuentas[df_cuentas['nombre'] == r['Medio Pago']]['id'].values[0]
                    catid = df_cats[df_cats['nombre'] == r['Categoría']]['id'].values[0]
                    tipo = "COMPRA_TARJETA" if df_cuentas[df_cuentas['nombre'] == r['Medio Pago']]['tipo'].values[0] == 'CREDITO' else "GASTO"
                    guardar_movimiento(f_p + timedelta(days=4), r['Monto'], r['Descripción'], mid, catid, tipo)
            
            st.success("¡Plan Guardado! Ahora podés verlo en el Dashboard seleccionando ese mes.")
            time.sleep(2)
            st.rerun()

# (El resto de secciones: Carga Manual, Historial y Tarjetas se mantienen igual pero con width="stretch")
elif menu == "➕ Cargar Manual":
    st.title("Carga Manual")
    # ... (Misma lógica de carga manual anterior)
    st.info("Usa esta sección para gastos del día a día.")
    with st.form("manual"):
        f = st.date_input("Fecha", date.today())
        m = st.number_input("Monto", min_value=0.0)
        d = st.text_input("Descripción")
        cta = st.selectbox("Cuenta", df_cuentas['nombre'].tolist())
        cat = st.selectbox("Categoría", df_cats['nombre'].tolist())
        if st.form_submit_button("Guardar"):
            id_c = df_cuentas[df_cuentas['nombre'] == cta]['id'].values[0]
            id_cat = df_cats[df_cats['nombre'] == cat]['id'].values[0]
            t = "COMPRA_TARJETA" if df_cuentas[df_cuentas['nombre'] == cta]['tipo'].values[0] == 'CREDITO' else "GASTO"
            guardar_movimiento(f, m, d, id_c, id_cat, t)
            st.success("Cargado")

elif menu == "📝 Historial":
    st.title("Historial")
    df = get_movimientos_periodo(fecha_inicio, fecha_fin)
    if not df.empty:
        st.data_editor(df, width="stretch", hide_index=True)