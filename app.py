import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import date, datetime, timedelta
import calendar
from dateutil.relativedelta import relativedelta
import plotly.express as px
import time

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Finanzas Pro", 
    page_icon="💸", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- ESTILOS PERSONALIZADOS (CSS) ---
st.markdown("""
    <style>
    .block-container {padding-top: 1rem; padding-bottom: 2rem;}
    .stMetric {background-color: #f9f9f9; padding: 10px; border-radius: 10px; border: 1px solid #e0e0e0;}
    h1, h2, h3 {color: #2c3e50;}
    </style>
""", unsafe_allow_html=True)

# --- LOGIN SIMPLE ---
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False

    if st.session_state.password_correct:
        return True

    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.markdown("### 🔐 Bienvenido")
        pwd = st.text_input("Ingresá tu contraseña", type="password")
        if st.button("Ingresar", type="primary", use_container_width=True):
            if pwd == "admin": 
                st.session_state.password_correct = True
                st.rerun()
            else:
                st.error("Contraseña incorrecta")
    return False

if not check_password():
    st.stop()

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
    return f"$ {s[:-3]}" if s.endswith(",00") else f"$ {s}"

def calcular_vto_real(fecha_compra, dia_cierre, dia_vto):
    if isinstance(fecha_compra, str):
        try: fecha_compra = datetime.strptime(fecha_compra, "%Y-%m-%d").date()
        except: return date.today()
    try: f_cierre = date(fecha_compra.year, fecha_compra.month, int(dia_cierre))
    except: f_cierre = date(fecha_compra.year, fecha_compra.month, 28)
    if fecha_compra <= f_cierre: resumen = fecha_compra + relativedelta(months=1)
    else: resumen = fecha_compra + relativedelta(months=2)
    try: return date(resumen.year, resumen.month, int(dia_vto))
    except: return date(resumen.year, resumen.month, 28)

# --- BASE DE DATOS (CRUD) ---
def get_maestros():
    cta = pd.DataFrame(supabase.table("cuentas").select("*").execute().data)
    cat = pd.DataFrame(supabase.table("categorias").select("*").execute().data)
    try: su = float(supabase.table("configuracion").select("valor").eq("clave", "sueldo_mensual").execute().data[0]['valor'])
    except: su = 0.0
    return cta, cat, su

def get_movimientos(desde, hasta):
    desde_ext = desde - relativedelta(months=6) # Margen para cuotas/tarjetas
    resp = supabase.table("movimientos").select(
        "*, categorias(nombre, icono), cuentas:cuentas!cuenta_id(nombre, tipo, dia_cierre, dia_vencimiento)"
    ).gte("fecha", str(desde_ext)).lte("fecha", str(hasta)).order("fecha").execute()
    if not resp.data: return pd.DataFrame()
    data = []
    for d in resp.data:
        r = d.copy()
        r['categoria'] = f"{d['categorias']['icono']} {d['categorias']['nombre']}" if d.get('categorias') else "Sin Cat"
        r['cuenta'] = d['cuentas']['nombre'] if d.get('cuentas') else "Sin Cuenta"
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

def db_delete(id_mov):
    supabase.table("movimientos").delete().eq("id", id_mov).execute()

# --- FUNCIONES V11 (Metas y Suscripciones) ---
def get_suscripciones():
    return pd.DataFrame(supabase.table("suscripciones").select("*").execute().data)

def save_suscripcion(desc, monto, cta_id, cat_id, tipo):
    supabase.table("suscripciones").insert({"descripcion": desc, "monto": monto, "cuenta_id": cta_id, "categoria_id": cat_id, "tipo": tipo}).execute()

def delete_suscripcion(sid):
    supabase.table("suscripciones").delete().eq("id", sid).execute()

def get_metas():
    return pd.DataFrame(supabase.table("metas").select("*").execute().data)

def save_meta(nombre, objetivo, fecha):
    supabase.table("metas").insert({"nombre": nombre, "objetivo": objetivo, "fecha_limite": str(fecha)}).execute()

def update_meta_ahorro(mid, monto_nuevo):
    supabase.table("metas").update({"ahorrado": monto_nuevo}).eq("id", mid).execute()

def delete_meta(mid):
    supabase.table("metas").delete().eq("id", mid).execute()

# --- CARGA DATOS GLOBALES ---
df_cta, df_cat, sueldo_base = get_maestros()

# --- SIDEBAR ---
with st.sidebar:
    st.title("📊 Finanzas Pro")
    st.markdown("---")
    menu = st.radio("Navegación", 
        ["Dashboard", "Calendario", "Metas de Ahorro", "Nueva Operación", "Historial", "Tarjetas", "Configuración"],
        label_visibility="collapsed"
    )
    st.divider()
    st.markdown("### 📅 Período")
    mes_sel = st.selectbox("Mes", range(1, 13), index=date.today().month - 1)
    anio_sel = st.number_input("Año", value=date.today().year, step=1)
    f_ini = date(anio_sel, mes_sel, 1)
    f_fin = f_ini + relativedelta(months=1) - timedelta(days=1)

# ==========================================
# 1. DASHBOARD
# ==========================================
if menu == "Dashboard":
    st.markdown(f"## 📈 Balance de {f_ini.strftime('%B %Y')}")
    df_raw = get_movimientos(f_ini, f_fin)
    
    if not df_raw.empty:
        df_mes = df_raw[(df_raw['fecha'] >= f_ini) & (df_raw['fecha'] <= f_fin)]
        
        # Cálculos Principales
        ing_registrados = df_mes[df_mes['tipo'] == 'INGRESO']['monto'].sum()
        total_ingresos = ing_registrados if ing_registrados > 0 else sueldo_base
        
        gastos_cash = df_mes[df_mes['tipo'] == 'GASTO']['monto'].sum()
        gastos_tj = df_mes[df_mes['tipo'] == 'COMPRA_TARJETA']['monto'].sum()
        
        # Tarjetas Vencimientos (Deuda real a pagar hoy)
        df_tj = df_raw[df_raw['tipo'] == 'COMPRA_TARJETA'].copy()
        vence_ahora = 0
        if not df_tj.empty:
            df_tj['fecha_vto'] = df_tj.apply(lambda x: calcular_vto_real(x['fecha'], x['cierre'], x['vto']), axis=1)
            vence_ahora = df_tj[(df_tj['fecha_vto'] >= f_ini) & (df_tj['fecha_vto'] <= f_fin)]['monto'].sum()

        disponible = total_ingresos - gastos_cash - vence_ahora
        resultado_neto = total_ingresos - (gastos_cash + gastos_tj)

        # --- TARJETAS KPI (Diseño Mejorado) ---
        c1, c2, c3, c4 = st.columns(4)
        
        c1.metric("💰 Resultado Neto", fmt_ars(resultado_neto), delta="Ingresos - Consumo Total", delta_color="normal")
        c2.metric("✅ Caja Disponible", fmt_ars(disponible), help="Lo que te queda real en el bolsillo")
        c3.metric("🛒 Consumo Total", fmt_ars(gastos_cash + gastos_tj), delta="Cash + Tarjeta", delta_color="inverse")
        c4.metric("💳 A Pagar (Resumen)", fmt_ars(vence_ahora), delta="Vence este mes", delta_color="inverse")

        st.markdown("---")
        
        # --- GRÁFICOS ---
        g1, g2 = st.columns([2,1])
        with g1:
            st.subheader("Evolución Diaria")
            if not df_mes.empty:
                df_chart = df_mes[df_mes['tipo'] != 'INGRESO']
                if not df_chart.empty:
                    fig = px.bar(df_chart, x='fecha', y='monto', color='categoria', 
                                 title="", template="plotly_white",
                                 color_discrete_sequence=px.colors.qualitative.Pastel)
                    fig.update_layout(xaxis_title=None, yaxis_title=None, showlegend=True, height=350, margin=dict(l=0,r=0,t=10,b=0))
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No hay gastos registrados aún.")
                    
        with g2:
            st.subheader("Distribución")
            if not df_mes.empty:
                df_chart = df_mes[df_mes['tipo'].isin(['GASTO', 'COMPRA_TARJETA'])]
                if not df_chart.empty:
                    fig_p = px.pie(df_chart, values='monto', names='categoria', hole=0.6, 
                                   template="plotly_white",
                                   color_discrete_sequence=px.colors.qualitative.Pastel)
                    fig_p.update_layout(showlegend=False, height=350, margin=dict(l=0,r=0,t=10,b=0))
                    st.plotly_chart(fig_p, use_container_width=True)
                else:
                    st.info("Sin datos.")
    else:
        st.info("👋 ¡Hola! No hay movimientos en este mes. Andá a **Nueva Operación** para empezar o cargá tu plan en **Configuración**.")

# ==========================================
# 2. CALENDARIO
# ==========================================
elif menu == "Calendario":
    st.header(f"📅 Agenda: {f_ini.strftime('%B %Y')}")
    df_cal = get_movimientos(f_ini, f_fin)
    if not df_cal.empty:
        df_cal = df_cal[(df_cal['fecha'] >= f_ini) & (df_cal['fecha'] <= f_fin)]
    
    cal = calendar.Calendar()
    semanas = cal.monthdayscalendar(anio_sel, mes_sel)
    dias_semana = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    
    # Estilo calendario
    cols = st.columns(7)
    for i, d in enumerate(dias_semana):
        cols[i].markdown(f"<div style='text-align:center; font-weight:bold; background:#e0e0e0; padding:5px; border-radius:5px'>{d}</div>", unsafe_allow_html=True)
    
    st.write("") # Spacer

    for semana in semanas:
        cols = st.columns(7)
        for i, dia in enumerate(semana):
            with cols[i]:
                if dia != 0:
                    fecha_dia = date(anio_sel, mes_sel, dia)
                    with st.container(border=True):
                        st.markdown(f"**{dia}**")
                        if not df_cal.empty:
                            evs = df_cal[df_cal['fecha'] == fecha_dia]
                            ing = evs[evs['tipo']=='INGRESO']['monto'].sum()
                            gas = evs[evs['tipo']!='INGRESO']['monto'].sum()
                            
                            if ing > 0: st.markdown(f":green[+${ing:,.0f}]")
                            if gas > 0: st.markdown(f":red[-${gas:,.0f}]")
                            
                            if not evs.empty:
                                with st.popover("🔍"):
                                    st.dataframe(evs[['descripcion', 'monto']], hide_index=True)

# ==========================================
# 3. METAS
# ==========================================
elif menu == "Metas de Ahorro":
    st.header("🎯 Objetivos")
    
    tab_ver, tab_crear = st.tabs(["Mis Metas", "Nueva Meta"])
    
    with tab_ver:
        df_m = get_metas()
        if not df_m.empty:
            for _, m in df_m.iterrows():
                with st.container(border=True):
                    c1, c2, c3 = st.columns([3, 2, 1])
                    progreso = m['ahorrado'] / m['objetivo'] if m['objetivo'] > 0 else 0
                    
                    c1.subheader(m['nombre'])
                    c1.progress(min(progreso, 1.0))
                    c1.caption(f"Meta: {fmt_ars(m['objetivo'])} | Faltan: {fmt_ars(m['objetivo'] - m['ahorrado'])}")
                    
                    nuevo_ahorro = c2.number_input(f"Monto Ahorrado", value=float(m['ahorrado']), key=f"m_{m['id']}")
                    
                    c3.write("") # Spacer vertical
                    if c3.button("💾 Guardar", key=f"bm_{m['id']}"):
                        update_meta_ahorro(m['id'], nuevo_ahorro)
                        st.rerun()
                    if c3.button("🗑️ Borrar", key=f"bd_{m['id']}"):
                        delete_meta(m['id'])
                        st.rerun()
        else:
            st.info("No tenés metas activas. ¡Creá una para motivarte!")

    with tab_crear:
        with st.form("new_meta"):
            nom = st.text_input("Nombre de la meta (ej: Moto, Viaje)")
            obj = st.number_input("Monto Objetivo ($)", min_value=1.0)
            limite = st.date_input("Fecha Límite Estimada")
            if st.form_submit_button("Crear Meta", type="primary"):
                save_meta(nom, obj, limite)
                st.success("¡Meta creada! A ahorrar se ha dicho."); time.sleep(1); st.rerun()

# ==========================================
# 4. CARGAR
# ==========================================
elif menu == "Nueva Operación":
    st.header("➕ Registrar Movimiento")
    
    t_manual, t_recurrente = st.tabs(["Manual / Cuotas", "🔄 Recurrentes (Suscripciones)"])
    
    with t_manual:
        tipo_op = st.radio("Tipo de Operación", ["Gasto / Compra", "Ingreso", "Pagar Resumen Tarjeta"], horizontal=True)
        
        with st.container(border=True):
            col1, col2 = st.columns(2)
            f = col1.date_input("Fecha", date.today())
            m = col2.number_input("Monto Total ($)", min_value=0.0)
            d = st.text_input("Descripción (Opcional)")
            
            c3, c4 = st.columns(2)
            if tipo_op == "Pagar Resumen Tarjeta":
                cta_n = c3.selectbox("Pagar desde (Banco/Efvo)", df_cta[df_cta['tipo']!='CREDITO']['nombre'].tolist())
                cta_dest = c4.selectbox("Tarjeta a Pagar", df_cta[df_cta['tipo']=='CREDITO']['nombre'].tolist())
                cat_n = df_cat.iloc[0]['nombre']
            else:
                cta_n = c3.selectbox("Cuenta / Medio de Pago", df_cta['nombre'].tolist())
                cat_n = c4.selectbox("Categoría / Rubro", df_cat['nombre'].tolist())
            
            cuotas = 1
            if tipo_op == "Gasto / Compra":
                cuotas = st.number_input("💳 Cantidad de Cuotas", min_value=1, value=1, step=1)
                if cuotas > 1:
                    st.info(f"Se generarán **{cuotas}** movimientos futuros de **{fmt_ars(m/cuotas)}** cada uno.")

            if st.button("Guardar Operación", type="primary", use_container_width=True):
                id_c = df_cta[df_cta['nombre'] == cta_n]['id'].values[0]
                id_ct = df_cat[df_cat['nombre'] == cat_n]['id'].values[0]
                
                if tipo_op == "Pagar Resumen Tarjeta":
                    id_d = df_cta[df_cta['nombre'] == cta_dest]['id'].values[0]
                    db_save(f, m, d, id_c, id_ct, "PAGO_TARJETA", id_d)
                
                elif tipo_op == "Ingreso":
                    db_save(f, m, d, id_c, id_ct, "INGRESO")
                
                else: 
                    es_credito = df_cta[df_cta['nombre'] == cta_n]['tipo'].values[0] == 'CREDITO'
                    tp = "COMPRA_TARJETA" if es_credito else "GASTO"
                    
                    if cuotas > 1:
                        m_cuota = m / cuotas
                        for i in range(cuotas):
                            f_pago = f + relativedelta(months=i)
                            d_cuota = f"{d} (Cuota {i+1}/{cuotas})"
                            db_save(f_pago, m_cuota, d_cuota, id_c, id_ct, tp)
                    else:
                        db_save(f, m, d, id_c, id_ct, tp)
                
                st.success("¡Operación registrada correctamente!"); time.sleep(1); st.rerun()

    with t_recurrente:
        st.subheader("Cargar Gastos Fijos (Recurrentes)")
        df_sus = get_suscripciones()
        if not df_sus.empty:
            c_f1, c_f2 = st.columns([1, 2])
            fecha_impacto = c_f1.date_input("Fecha de impacto", date.today().replace(day=5)) 
            c_f2.info("Seleccioná la fecha. El sistema creará los gastos en ese mes.")
            
            st.write("Podés ajustar los montos antes de confirmar:")
            edited_sus = st.data_editor(
                df_sus[['descripcion', 'monto']], 
                num_rows="dynamic", 
                use_container_width=True,
                column_config={
                    "monto": st.column_config.NumberColumn("Monto", format="$ %.2f")
                }
            )
            
            if st.button(f"🚀 Generar Gastos para el {fecha_impacto.strftime('%d/%m/%Y')}", type="primary", use_container_width=True):
                count = 0
                for i, row in edited_sus.iterrows():
                    original = df_sus.iloc[i]
                    db_save(fecha_impacto, row['monto'], row['descripcion'], original['cuenta_id'], original['categoria_id'], original['tipo'])
                    count += 1
                st.success(f"¡Listo! Se generaron {count} movimientos."); time.sleep(2); st.rerun()
        else:
            st.warning("No tenés gastos recurrentes configurados. Andá a 'Configuración'.")

# ==========================================
# 5. HISTORIAL
# ==========================================
elif menu == "Historial":
    st.header("📝 Historial de Movimientos")
    
    col_check, col_spacer = st.columns([1,3])
    ver_todo = col_check.checkbox("🔍 Ver TODO el historial histórico")
    
    df_h = get_movimientos(date(2024,1,1), date(2027,1,1)) if ver_todo else get_movimientos(f_ini, f_fin)
    
    if ver_todo == False and not df_h.empty:
        df_h = df_h[(df_h['fecha'] >= f_ini) & (df_h['fecha'] <= f_fin)]

    tab_e, tab_d = st.tabs(["Editar Datos", "Eliminar"])
    with tab_e:
        if not df_h.empty:
            st.data_editor(df_h[['id', 'fecha', 'descripcion', 'monto', 'cuenta', 'tipo']], width="stretch", hide_index=True)
        else: st.info("No hay datos para mostrar.")
            
    with tab_d:
        if not df_h.empty:
            ops = {f"{r['fecha']} | {r['descripcion']}": r['id'] for _, r in df_h.iterrows()}
            sel = st.selectbox("Seleccionar movimiento para borrar:", ["..."] + list(ops.keys()))
            if st.button("Eliminar Seleccionado", type="primary") and sel != "...":
                db_delete(ops[sel]); st.success("Eliminado"); time.sleep(1); st.rerun()
                
            st.markdown("---")
            if st.checkbox("Habilitar Borrado Masivo"):
                st.warning(f"¡Cuidado! Vas a borrar {len(df_h)} registros visibles.")
                if st.button("BORRAR TODO LO VISIBLE", type="primary"):
                    for _, r in df_h.iterrows(): db_delete(r['id'])
                    st.rerun()

# ==========================================
# 6. TARJETAS
# ==========================================
elif menu == "Tarjetas":
    st.header("💳 Gestión de Tarjetas")
    t1, t2 = st.tabs(["Configuración", "Importar Resumen"])
    with t1:
        df_c = df_cta[df_cta['tipo']=='CREDITO']
        for _, r in df_c.iterrows():
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([2,1,1,1])
                c1.markdown(f"### {r['nombre']}")
                ci = c2.number_input("Día Cierre", 1, 31, int(r.get('dia_cierre') or 23), key=f"c{r['id']}")
                vt = c3.number_input("Día Vencimiento", 1, 31, int(r.get('dia_vencimiento') or 5), key=f"v{r['id']}")
                if c4.button("Guardar", key=f"b{r['id']}", use_container_width=True):
                    supabase.table("cuentas").update({"dia_cierre": ci, "dia_vencimiento": vt}).eq("id", r['id']).execute()
                    st.rerun()
    with t2:
        st.info("Soporta Excel (.xlsx) y CSV de Santander, Galicia, BBVA, etc.")
        up = st.file_uploader("Subir Archivo", type=['xlsx', 'csv'])
        if up:
            try:
                if up.name.endswith('.csv'): df_u = pd.read_csv(up)
                else:
                    raw = pd.read_excel(up)
                    head = 0
                    for i in range(len(raw)):
                        if 'Fecha' in raw.iloc[i].values or 'FECHA' in raw.iloc[i].values: head = i+1; break
                    df_u = pd.read_excel(up, skiprows=head)
                df_u = df_u.dropna(how='all').reset_index(drop=True)
                st.dataframe(df_u.head(), width="stretch")
                
                with st.form("imp"):
                    st.write("Mapeo de Columnas:")
                    sel = st.selectbox("Tarjeta Destino", df_cta[df_cta['tipo']=='CREDITO']['nombre'].tolist())
                    c1, c2, c3 = st.columns(3)
                    fc = c1.selectbox("Fecha", df_u.columns); dc = c2.selectbox("Descripción", df_u.columns); mc = c3.selectbox("Monto / Pesos", df_u.columns)
                    
                    if st.form_submit_button("Procesar Importación", type="primary"):
                        tid = df_cta[df_cta['nombre']==sel]['id'].values[0]
                        count = 0
                        for _, r in df_u.iterrows():
                            try:
                                ms = str(r[mc]).replace('$','').replace(' ','')
                                if ',' in ms and '.' in ms: ms = ms.replace('.','').replace(',','.')
                                elif ',' in ms: ms = ms.replace(',','.')
                                val = abs(float(ms))
                                fval = pd.to_datetime(r[fc], dayfirst=True).date()
                                db_save(fval, val, str(r[dc]), tid, df_cat.iloc[0]['id'], "COMPRA_TARJETA")
                                count += 1
                            except: continue
                        st.success(f"¡Éxito! {count} movimientos importados."); time.sleep(2); st.rerun()
            except Exception as e: st.error(f"Error al leer archivo: {str(e)}")

# ==========================================
# 7. AJUSTES
# ==========================================
elif menu == "Configuración":
    st.header("⚙️ Ajustes Generales")
    
    with st.expander("💰 Sueldo Base Mensual", expanded=True):
        ns = st.number_input("Monto Neto ($)", value=int(sueldo_base), step=1000)
        if st.button("Actualizar Sueldo Base", type="primary"):
            supabase.table("configuracion").upsert({"clave": "sueldo_mensual", "valor": str(ns)}).execute()
            st.success("Actualizado"); time.sleep(1); st.rerun()
            
    with st.expander("🔄 Administrar Gastos Recurrentes (Suscripciones)", expanded=False):
        st.info("Cargá aquí tus gastos fijos (Netflix, Alquiler, Gimnasio) para generarlos rápidamente cada mes.")
        with st.form("new_sus"):
            c1, c2 = st.columns(2)
            sd = c1.text_input("Descripción (ej: Internet)")
            sm = c2.number_input("Monto ($)", min_value=0.0)
            c3, c4 = st.columns(2)
            sc = c3.selectbox("Se paga con:", df_cta['nombre'].tolist())
            sca = c4.selectbox("Rubro", df_cat['nombre'].tolist())
            
            if st.form_submit_button("Agregar Nuevo Recurrente"):
                sidc = df_cta[df_cta['nombre']==sc]['id'].values[0]
                sidca = df_cat[df_cat['nombre']==sca]['id'].values[0]
                es_cred = df_cta[df_cta['nombre']==sc]['tipo'].values[0] == 'CREDITO'
                stipo = "COMPRA_TARJETA" if es_cred else "GASTO"
                save_suscripcion(sd, sm, sidc, sidca, stipo)
                st.success("Guardado"); st.rerun()
        
        df_sus = get_suscripciones()
        if not df_sus.empty:
            st.dataframe(df_sus[['descripcion', 'monto']], hide_index=True, use_container_width=True)
            c_del, c_btn = st.columns([3,1])
            ds = c_del.selectbox("Borrar Recurrente:", ["..."] + df_sus['descripcion'].tolist())
            if c_btn.button("Eliminar") and ds != "...":
                did = df_sus[df_sus['descripcion']==ds]['id'].values[0]
                delete_suscripcion(did)
                st.rerun()