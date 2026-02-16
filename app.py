import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import date, datetime, timedelta
import calendar
from dateutil.relativedelta import relativedelta
import plotly.express as px
import time

# --- 1. CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Finanzas Pro", 
    page_icon="💸", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. ESTILOS PRO (CSS INYECTADO) ---
# Esto es lo que le da el look "Fintech"
st.markdown("""
    <style>
    /* Importar fuente moderna */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    /* Estilo para las Métricas (Tarjetas) */
    div[data-testid="stMetric"] {
        background-color: #ffffff;
        border: 1px solid #f0f2f6;
        padding: 20px;
        border-radius: 12px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
        transition: transform 0.2s;
    }
    div[data-testid="stMetric"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 8px rgba(0, 0, 0, 0.1);
    }
    
    /* Encabezados más limpios */
    h1 { font-weight: 700; color: #1e293b; letter-spacing: -1px;}
    h2 { font-weight: 600; color: #334155; letter-spacing: -0.5px;}
    h3 { font-weight: 600; color: #475569;}
    
    /* Botones más atractivos */
    div.stButton > button {
        border-radius: 8px;
        font-weight: 600;
        height: 3rem;
    }
    
    /* Ajuste de tablas */
    div[data-testid="stDataFrame"] {
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        overflow: hidden;
    }
    
    /* Calendario */
    .day-card {
        background-color: white;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 10px;
        text-align: center;
        height: 100px;
        font-size: 0.9rem;
    }
    .day-header {
        text-align: center;
        font-weight: bold;
        color: #64748b;
        margin-bottom: 10px;
    }
    .money-pos { color: #10b981; font-weight: bold; font-size: 0.8rem;}
    .money-neg { color: #ef4444; font-weight: bold; font-size: 0.8rem;}
    
    </style>
""", unsafe_allow_html=True)

# --- 3. LOGIN ---
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False

    if st.session_state.password_correct:
        return True

    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.markdown("<br><br><h2 style='text-align:center;'>🔐 Finanzas Pro</h2>", unsafe_allow_html=True)
        pwd = st.text_input("Ingresá tu contraseña", type="password", label_visibility="collapsed", placeholder="Contraseña")
        if st.button("Ingresar", type="primary", use_container_width=True):
            if pwd == "admin": 
                st.session_state.password_correct = True
                st.rerun()
            else:
                st.toast("🚫 Contraseña incorrecta")
    return False

if not check_password():
    st.stop()

# --- 4. CONEXIÓN & FUNCIONES ---
@st.cache_resource
def init_connection():
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except: st.stop()

supabase = init_connection()

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

def get_maestros():
    cta = pd.DataFrame(supabase.table("cuentas").select("*").execute().data)
    cat = pd.DataFrame(supabase.table("categorias").select("*").execute().data)
    try: su = float(supabase.table("configuracion").select("valor").eq("clave", "sueldo_mensual").execute().data[0]['valor'])
    except: su = 0.0
    return cta, cat, su

def get_movimientos(desde, hasta):
    desde_ext = desde - relativedelta(months=6)
    resp = supabase.table("movimientos").select(
        "*, categorias(nombre, icono), cuentas:cuentas!cuenta_id(nombre, tipo, dia_cierre, dia_vencimiento)"
    ).gte("fecha", str(desde_ext)).lte("fecha", str(hasta)).order("fecha").execute()
    if not resp.data: return pd.DataFrame()
    data = []
    for d in resp.data:
        r = d.copy()
        r['categoria'] = f"{d['categorias']['icono']} {d['categorias']['nombre']}" if d.get('categorias') else "General"
        r['cuenta'] = d['cuentas']['nombre'] if d.get('cuentas') else "Efectivo"
        r['tipo_cta'] = d['cuentas']['tipo'] if d.get('cuentas') else "DEBITO"
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

# --- CARGA GLOBAL ---
df_cta, df_cat, sueldo_base = get_maestros()

# --- 5. SIDEBAR & NAVEGACIÓN ---
with st.sidebar:
    st.markdown("## 🦅 Lucas Finanzas")
    st.markdown("---")
    
    # Navegación con Iconos
    menu = st.radio("", 
        ["📊 Dashboard", "📅 Calendario", "➕ Operaciones", "🎯 Metas", "📝 Historial", "💳 Tarjetas", "⚙️ Ajustes"],
        index=0, label_visibility="collapsed"
    )
    
    st.markdown("---")
    st.caption("Filtro Global")
    c_mes, c_anio = st.columns(2)
    mes_sel = c_mes.selectbox("Mes", range(1, 13), index=date.today().month - 1, label_visibility="collapsed")
    anio_sel = c_anio.number_input("Año", value=date.today().year, step=1, label_visibility="collapsed")
    
    f_ini = date(anio_sel, mes_sel, 1)
    f_fin = f_ini + relativedelta(months=1) - timedelta(days=1)

# ==========================================
# 1. DASHBOARD
# ==========================================
if "Dashboard" in menu:
    st.markdown(f"### Balance de {f_ini.strftime('%B %Y')}")
    df_raw = get_movimientos(f_ini, f_fin)
    
    if not df_raw.empty:
        df_mes = df_raw[(df_raw['fecha'] >= f_ini) & (df_raw['fecha'] <= f_fin)]
        
        # Cálculos
        ing_registrados = df_mes[df_mes['tipo'] == 'INGRESO']['monto'].sum()
        total_ingresos = ing_registrados if ing_registrados > 0 else sueldo_base
        
        gastos_cash = df_mes[df_mes['tipo'] == 'GASTO']['monto'].sum()
        gastos_tj = df_mes[df_mes['tipo'] == 'COMPRA_TARJETA']['monto'].sum()
        
        # Vencimientos
        df_tj = df_raw[df_raw['tipo'] == 'COMPRA_TARJETA'].copy()
        vence_ahora = 0
        if not df_tj.empty:
            df_tj['fecha_vto'] = df_tj.apply(lambda x: calcular_vto_real(x['fecha'], x['cierre'], x['vto']), axis=1)
            vence_ahora = df_tj[(df_tj['fecha_vto'] >= f_ini) & (df_tj['fecha_vto'] <= f_fin)]['monto'].sum()

        disponible = total_ingresos - gastos_cash - vence_ahora
        resultado_neto = total_ingresos - (gastos_cash + gastos_tj)

        # UI: Tarjetas de Métricas
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("💰 Resultado Neto", fmt_ars(resultado_neto), delta="Ingreso - Consumo", delta_color="normal")
        col2.metric("✅ Caja Disponible", fmt_ars(disponible), help="Lo que tenés 'en mano' después de pagar todo.")
        col3.metric("💳 Vence Tarjeta", fmt_ars(vence_ahora), delta="A pagar este mes", delta_color="inverse")
        col4.metric("📉 Consumo Total", fmt_ars(gastos_cash + gastos_tj), delta="Cash + Cuotas nuevas", delta_color="inverse")

        st.markdown("<br>", unsafe_allow_html=True) # Espacio

        # UI: Gráficos Limpios
        c_chart1, c_chart2 = st.columns([2, 1])
        with c_chart1:
            st.markdown("##### 📈 Flujo Diario")
            if not df_mes.empty:
                df_chart = df_mes[df_mes['tipo'] != 'INGRESO']
                if not df_chart.empty:
                    fig = px.bar(df_chart, x='fecha', y='monto', color='categoria', template="plotly_white",
                                 color_discrete_sequence=px.colors.qualitative.Pastel)
                    fig.update_layout(xaxis_title=None, yaxis_title=None, plot_bgcolor="white", showlegend=False, height=320, margin=dict(l=0,r=0,t=0,b=0))
                    st.plotly_chart(fig, use_container_width=True)
                else: st.info("Sin gastos para graficar.")
        
        with c_chart2:
            st.markdown("##### 🍰 Distribución")
            if not df_mes.empty:
                df_chart = df_mes[df_mes['tipo'].isin(['GASTO', 'COMPRA_TARJETA'])]
                if not df_chart.empty:
                    fig_p = px.pie(df_chart, values='monto', names='categoria', hole=0.6, template="plotly_white",
                                   color_discrete_sequence=px.colors.qualitative.Pastel)
                    fig_p.update_layout(showlegend=False, height=320, margin=dict(l=0,r=0,t=0,b=0))
                    st.plotly_chart(fig_p, use_container_width=True)
    else:
        st.warning("No hay datos cargados en este mes. Andá a **➕ Operaciones** para empezar.")

# ==========================================
# 2. CALENDARIO
# ==========================================
elif "Calendario" in menu:
    st.markdown(f"### 📅 Agenda: {f_ini.strftime('%B %Y')}")
    df_cal = get_movimientos(f_ini, f_fin)
    if not df_cal.empty:
        df_cal = df_cal[(df_cal['fecha'] >= f_ini) & (df_cal['fecha'] <= f_fin)]
    
    cal = calendar.Calendar()
    semanas = cal.monthdayscalendar(anio_sel, mes_sel)
    dias = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    
    # Header Días
    cols = st.columns(7)
    for i, d in enumerate(dias):
        cols[i].markdown(f"<div class='day-header'>{d}</div>", unsafe_allow_html=True)
        
    for semana in semanas:
        cols = st.columns(7)
        for i, dia in enumerate(semana):
            with cols[i]:
                if dia != 0:
                    fecha_dia = date(anio_sel, mes_sel, dia)
                    ing_txt, gas_txt = "", ""
                    
                    if not df_cal.empty:
                        evs = df_cal[df_cal['fecha'] == fecha_dia]
                        ing = evs[evs['tipo']=='INGRESO']['monto'].sum()
                        gas = evs[evs['tipo']!='INGRESO']['monto'].sum()
                        
                        if ing > 0: ing_txt = f"<div class='money-pos'>+{fmt_ars(ing)}</div>"
                        if gas > 0: gas_txt = f"<div class='money-neg'>-{fmt_ars(gas)}</div>"
                        
                        # Card HTML
                        st.markdown(f"""
                        <div class="day-card">
                            <div style="font-weight:bold; color:#333;">{dia}</div>
                            {ing_txt}
                            {gas_txt}
                        </div>
                        """, unsafe_allow_html=True)
                        
                        if not evs.empty:
                            with st.popover("Ver Detalles"):
                                st.dataframe(evs[['descripcion', 'monto']], hide_index=True)
                    else:
                        st.markdown(f"""<div class="day-card" style="color:#ccc;">{dia}</div>""", unsafe_allow_html=True)
                else:
                    st.write("")

# ==========================================
# 3. OPERACIONES (CARGAR)
# ==========================================
elif "Operaciones" in menu:
    st.markdown("### Registrar Movimiento")
    
    t1, t2, t3 = st.tabs(["Manual / Cuotas", "🔄 Recurrentes", "📥 Importar Excel"])
    
    with t1:
        with st.container(border=True):
            col_tipo = st.radio("Tipo", ["Gasto", "Ingreso", "Pagar Tarjeta"], horizontal=True, label_visibility="collapsed")
            st.markdown("---")
            
            c1, c2 = st.columns(2)
            f = c1.date_input("Fecha", date.today())
            m = c2.number_input("Monto Total", min_value=0.0, step=100.0)
            d = st.text_input("Descripción", placeholder="Ej: Supermercado, Nafta, Netflix")
            
            c3, c4 = st.columns(2)
            if col_tipo == "Pagar Tarjeta":
                cta_n = c3.selectbox("Desde (Banco/Efvo)", df_cta[df_cta['tipo']!='CREDITO']['nombre'].tolist())
                cta_dest = c4.selectbox("Qué Tarjeta Pagaste", df_cta[df_cta['tipo']=='CREDITO']['nombre'].tolist())
                cat_n = df_cat.iloc[0]['nombre']
            else:
                cta_n = c3.selectbox("Cuenta / Tarjeta", df_cta['nombre'].tolist())
                cat_n = c4.selectbox("Categoría", df_cat['nombre'].tolist())
            
            cuotas = 1
            if col_tipo == "Gasto":
                cuotas = st.slider("Cantidad de Cuotas", 1, 24, 1)
                if cuotas > 1:
                    st.info(f"Se crearán {cuotas} pagos mensuales de {fmt_ars(m/cuotas)}.")

            if st.button("Guardar Operación", type="primary", use_container_width=True):
                id_c = df_cta[df_cta['nombre'] == cta_n]['id'].values[0]
                id_ct = df_cat[df_cat['nombre'] == cat_n]['id'].values[0]
                
                if col_tipo == "Pagar Tarjeta":
                    id_d = df_cta[df_cta['nombre'] == cta_dest]['id'].values[0]
                    db_save(f, m, d, id_c, id_ct, "PAGO_TARJETA", id_d)
                elif col_tipo == "Ingreso":
                    db_save(f, m, d, id_c, id_ct, "INGRESO")
                else:
                    es_cred = df_cta[df_cta['nombre'] == cta_n]['tipo'].values[0] == 'CREDITO'
                    tp = "COMPRA_TARJETA" if es_cred else "GASTO"
                    if cuotas > 1:
                        m_cuota = m / cuotas
                        for i in range(cuotas):
                            f_pago = f + relativedelta(months=i)
                            d_c = f"{d} (Cuota {i+1}/{cuotas})"
                            db_save(f_pago, m_cuota, d_c, id_c, id_ct, tp)
                    else:
                        db_save(f, m, d, id_c, id_ct, tp)
                st.toast("✅ ¡Operación guardada con éxito!")
                time.sleep(1)
                st.rerun()

    with t2:
        df_sus = get_suscripciones()
        if not df_sus.empty:
            c_date, c_info = st.columns([1,2])
            fecha_imp = c_date.date_input("Fecha de Impacto", date.today().replace(day=5))
            c_info.info(f"Los gastos se crearán con fecha: **{fecha_imp.strftime('%d/%m/%Y')}**")
            
            st.write("Ajustá los montos de este mes si cambiaron:")
            ed_sus = st.data_editor(df_sus[['descripcion', 'monto']], use_container_width=True, num_rows="dynamic",
                                    column_config={"monto": st.column_config.NumberColumn("Monto", format="$ %.2f")})
            
            if st.button("🚀 Procesar Fijos", type="primary", use_container_width=True):
                c = 0
                for i, row in ed_sus.iterrows():
                    orig = df_sus.iloc[i]
                    db_save(fecha_imp, row['monto'], row['descripcion'], orig['cuenta_id'], orig['categoria_id'], orig['tipo'])
                    c += 1
                st.toast(f"✅ Se generaron {c} movimientos.")
                time.sleep(2)
                st.rerun()
        else:
            st.warning("Configurá tus gastos fijos en 'Ajustes' primero.")

    with t3:
        st.info("Compatible con Excel (.xlsx) de Santander, Galicia, BBVA.")
        up = st.file_uploader("Arrastrá tu resumen aquí", type=['xlsx', 'csv'])
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
                st.dataframe(df_u.head(3), use_container_width=True)
                
                with st.form("imp_form"):
                    sel = st.selectbox("Tarjeta Destino", df_cta[df_cta['tipo']=='CREDITO']['nombre'].tolist())
                    c1, c2, c3 = st.columns(3)
                    fc = c1.selectbox("Col. Fecha", df_u.columns)
                    dc = c2.selectbox("Col. Detalle", df_u.columns)
                    mc = c3.selectbox("Col. Pesos", df_u.columns)
                    if st.form_submit_button("Importar Movimientos", type="primary"):
                        tid = df_cta[df_cta['nombre']==sel]['id'].values[0]
                        cnt = 0
                        for _, r in df_u.iterrows():
                            try:
                                ms = str(r[mc]).replace('$','').replace(' ','')
                                if ',' in ms and '.' in ms: ms = ms.replace('.','').replace(',','.')
                                elif ',' in ms: ms = ms.replace(',','.')
                                val = abs(float(ms))
                                fval = pd.to_datetime(r[fc], dayfirst=True).date()
                                db_save(fval, val, str(r[dc]), tid, df_cat.iloc[0]['id'], "COMPRA_TARJETA")
                                cnt += 1
                            except: continue
                        st.toast(f"✅ Importación completada: {cnt} items.")
                        time.sleep(2); st.rerun()
            except Exception as e: st.error(f"Error al leer: {e}")

# ==========================================
# 4. METAS
# ==========================================
elif "Metas" in menu:
    st.markdown("### 🎯 Objetivos de Ahorro")
    df_m = get_metas()
    
    col_new, col_view = st.columns([1, 2])
    
    with col_new:
        with st.container(border=True):
            st.markdown("#### Nueva Meta")
            n = st.text_input("Nombre (ej: Auto)")
            o = st.number_input("Objetivo ($)", min_value=1.0)
            l = st.date_input("Fecha Límite")
            if st.button("Crear", type="primary", use_container_width=True):
                save_meta(n, o, l)
                st.rerun()
    
    with col_view:
        if not df_m.empty:
            for _, m in df_m.iterrows():
                with st.container(border=True):
                    c1, c2 = st.columns([3,1])
                    pct = m['ahorrado'] / m['objetivo'] if m['objetivo'] > 0 else 0
                    c1.markdown(f"**{m['nombre']}**")
                    c1.progress(min(pct, 1.0))
                    c1.caption(f"Llevas: {fmt_ars(m['ahorrado'])} de {fmt_ars(m['objetivo'])}")
                    
                    new_val = c2.number_input("Ahorrado", value=float(m['ahorrado']), key=f"v_{m['id']}", label_visibility="collapsed")
                    if c2.button("💾", key=f"s_{m['id']}"):
                        update_meta_ahorro(m['id'], new_val); st.rerun()
                    if c2.button("🗑️", key=f"d_{m['id']}"):
                        delete_meta(m['id']); st.rerun()
        else:
            st.info("Aun no hay metas.")

# ==========================================
# 5. HISTORIAL
# ==========================================
elif "Historial" in menu:
    st.markdown("### 📝 Gestión de Datos")
    
    check_col, _ = st.columns([1,3])
    ver_todo = check_col.checkbox("Ver todo el historial (ignorar mes)")
    
    df_h = get_movimientos(date(2024,1,1), date(2027,1,1)) if ver_todo else get_movimientos(f_ini, f_fin)
    
    if not ver_todo and not df_h.empty:
        df_h = df_h[(df_h['fecha'] >= f_ini) & (df_h['fecha'] <= f_fin)]

    if not df_h.empty:
        # UX: Tabla mejorada con column_config
        st.data_editor(
            df_h[['id', 'fecha', 'descripcion', 'monto', 'cuenta', 'categoria', 'tipo']],
            column_config={
                "monto": st.column_config.NumberColumn("Monto", format="$ %.2f"),
                "tipo": st.column_config.SelectboxColumn("Tipo", options=["GASTO", "INGRESO", "COMPRA_TARJETA", "PAGO_TARJETA"], width="medium"),
                "categoria": st.column_config.TextColumn("Categoría", width="medium"),
            },
            use_container_width=True, hide_index=True
        )
        
        with st.expander("🗑️ Zona de Borrado"):
            opciones = {f"{r['fecha']} | {r['descripcion']} | {fmt_ars(r['monto'])}": r['id'] for _, r in df_h.iterrows()}
            sel = st.selectbox("Seleccionar ítem:", ["..."] + list(opciones.keys()))
            if st.button("Eliminar Seleccionado") and sel != "...":
                db_delete(opciones[sel])
                st.toast("Eliminado")
                time.sleep(1); st.rerun()
            
            st.divider()
            if st.checkbox("Habilitar Borrado Masivo"):
                if st.button("🔥 BORRAR TODO LO VISIBLE", type="primary"):
                    for _, r in df_h.iterrows(): db_delete(r['id'])
                    st.rerun()
    else:
        st.info("No hay datos.")

# ==========================================
# 6. CONFIGURACIÓN (TARJETAS + AJUSTES)
# ==========================================
elif "Tarjetas" in menu:
    st.markdown("### 💳 Configuración de Tarjetas")
    df_c = df_cta[df_cta['tipo']=='CREDITO']
    for _, r in df_c.iterrows():
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([2,1,1,1])
            c1.markdown(f"**{r['nombre']}**")
            ci = c2.number_input("Cierre", 1, 31, int(r.get('dia_cierre') or 23), key=f"ci_{r['id']}")
            vt = c3.number_input("Vto", 1, 31, int(r.get('dia_vencimiento') or 5), key=f"vt_{r['id']}")
            if c4.button("Guardar", key=f"bt_{r['id']}"):
                supabase.table("cuentas").update({"dia_cierre": ci, "dia_vencimiento": vt}).eq("id", r['id']).execute()
                st.toast("Guardado"); time.sleep(1)

elif "Ajustes" in menu:
    st.markdown("### ⚙️ Preferencias")
    
    with st.container(border=True):
        st.markdown("#### 💰 Ingreso Base")
        n_s = st.number_input("Sueldo Neto Mensual", value=int(sueldo_base), step=1000)
        if st.button("Actualizar Sueldo"):
            supabase.table("configuracion").upsert({"clave": "sueldo_mensual", "valor": str(n_s)}).execute()
            st.toast("Sueldo actualizado")
    
    st.markdown("#### 🔄 Gestión de Recurrentes")
    with st.container(border=True):
        with st.form("add_sus"):
            c1, c2, c3, c4 = st.columns(4)
            sd = c1.text_input("Servicio (ej: Internet)")
            sm = c2.number_input("Monto", min_value=0.0)
            sc = c3.selectbox("Pago", df_cta['nombre'].tolist())
            sca = c4.selectbox("Rubro", df_cat['nombre'].tolist())
            if st.form_submit_button("Agregar"):
                sidc = df_cta[df_cta['nombre']==sc]['id'].values[0]
                sidca = df_cat[df_cat['nombre']==sca]['id'].values[0]
                stipo = "COMPRA_TARJETA" if df_cta[df_cta['nombre']==sc]['tipo'].values[0]=='CREDITO' else "GASTO"
                save_suscripcion(sd, sm, sidc, sidca, stipo)
                st.rerun()
        
        df_s = get_suscripciones()
        if not df_s.empty:
            st.dataframe(df_s[['descripcion', 'monto']], use_container_width=True, hide_index=True)
            ds = st.selectbox("Borrar:", ["..."] + df_s['descripcion'].tolist())
            if st.button("Eliminar") and ds != "...":
                did = df_s[df_s['descripcion']==ds]['id'].values[0]
                delete_suscripcion(did); st.rerun()