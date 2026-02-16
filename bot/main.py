import os
import re
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime
from dateutil.relativedelta import relativedelta

from fastapi import FastAPI
from supabase import create_client
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# ==========================================
# 1. CONFIGURACIÓN
# ==========================================
# Variables de entorno de Render
SUPABASE_URL = os.environ.get("SUPABASE_URL")
# Usamos SERVICE_ROLE_KEY para que el bot tenga permisos de escritura totales
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_SECRET")
# Tu ID numérico de Telegram por seguridad (opcional pero recomendado)
ALLOWED_USER_ID = os.environ.get("ALLOWED_USER_ID")

# Inicializar Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Logs
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==========================================
# 2. FUNCIONES DE AYUDA (Lógica de Negocio)
# ==========================================
def get_account_by_name(name):
    """Busca una cuenta por nombre. Si no encuentra, devuelve Efectivo o la primera."""
    try:
        res = supabase.table("cuentas").select("*").execute()
        cuentas = res.data or []
        
        # 1. Búsqueda exacta/parcial
        for acc in cuentas:
            if name.lower() in acc['nombre'].lower():
                return acc
        
        # 2. Si no encuentra y no se especificó nada, busca 'Efectivo'
        for acc in cuentas:
            if "efectivo" in acc['nombre'].lower():
                return acc
                
        # 3. Fallback: la primera que encuentre
        return cuentas[0] if cuentas else None
    except Exception as e:
        logger.error(f"Error buscando cuenta: {e}")
        return None

def get_category_general():
    """Busca la categoría General o Varios."""
    try:
        res = supabase.table("categorias").select("*").execute()
        cats = res.data or []
        for cat in cats:
            if "general" in cat['nombre'].lower() or "varios" in cat['nombre'].lower():
                return cat
        return cats[0] if cats else None
    except Exception as e:
        logger.error(f"Error buscando categoría: {e}")
        return None

# ==========================================
# 3. LÓGICA DEL BOT DE TELEGRAM
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 **Bot Finanzas Pro Activo**\n\n"
        "Ejemplos:\n"
        "⚡ `2500 Cafe` (Gasto hoy)\n"
        "📅 `15000 Super 2026-03-10` (Carga en fecha específica)\n"
        "💳 `50000 Nafta Visa` (Detecta tarjeta y crea cuota)"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. Seguridad
    user_id = str(update.effective_user.id)
    if ALLOWED_USER_ID and user_id != str(ALLOWED_USER_ID):
        await update.message.reply_text("⛔ No autorizado.")
        return

    text = update.message.text
    
    # 2. Extraer Monto (Busca el primer número)
    match_monto = re.search(r'(\d+([.,]\d{1,2})?)', text)
    if not match_monto:
        await update.message.reply_text("🤷‍♂️ No entendí el monto. Ejemplo: '2500 Coto'.")
        return

    monto_str = match_monto.group(1).replace(',', '.')
    monto = float(monto_str)
    
    # Limpiar texto para buscar el resto
    clean_text = text.replace(match_monto.group(0), '').strip()
    
    # 3. Extraer Fecha (Formato YYYY-MM-DD para cargar al mes que quieras)
    fecha_gasto = date.today()
    match_date = re.search(r'(\d{4}-\d{2}-\d{2})', clean_text)
    if match_date:
        try:
            fecha_str = match_date.group(1)
            fecha_gasto = datetime.strptime(fecha_str, "%Y-%m-%d").date()
            clean_text = clean_text.replace(fecha_str, '').strip()
        except: pass

    # 4. Detectar Cuenta (Busca palabras clave)
    # Por defecto 'Efectivo'
    target_account = None
    
    # Obtenemos todas las cuentas para comparar
    try:
        all_accounts_res = supabase.table("cuentas").select("nombre, id, tipo").execute()
        all_accounts = all_accounts_res.data or []
    except: all_accounts = []
    
    words = clean_text.split()
    desc_words = []
    
    # Separamos palabras de la descripción y la cuenta
    for word in words:
        is_acc_name = False
        if all_accounts:
            for acc in all_accounts:
                if word.lower() in acc['nombre'].lower():
                    target_account = acc
                    is_acc_name = True
                    break
        if not is_acc_name:
            desc_words.append(word)
    
    # Si no encontró cuenta explícita, usa Efectivo
    if not target_account:
        target_account = get_account_by_name("Efectivo")

    descripcion = " ".join(desc_words) or "Gasto Telegram"
    categoria = get_category_general()

    if not target_account or not categoria:
        await update.message.reply_text("❌ Error: No hay cuentas o categorías en la BD.")
        return

    # 5. Guardar en Supabase
    try:
        es_credito = target_account['tipo'] == 'CREDITO'
        
        if es_credito:
            # COMPRA TARJETA (Genera compra + 1 cuota)
            compra = supabase.table("compras_tarjeta").insert({
                "fecha_compra": str(fecha_gasto),
                "monto_total": monto,
                "cuotas_total": 1,
                "cuenta_id": target_account['id'],
                "categoria_id": categoria['id'],
                "descripcion": descripcion,
                "source": "telegram_bot",
                "merchant": descripcion
            }).execute()
            
            if compra.data:
                compra_id = compra.data[0]['id']
                supabase.table("cuotas_tarjeta").insert({
                    "compra_id": compra_id,
                    "nro_cuota": 1,
                    "fecha_cuota": str(fecha_gasto), # Impacta en el resumen de esta fecha
                    "monto_cuota": monto,
                    "estado": "pendiente"
                }).execute()
                await update.message.reply_text(f"💳 **Compra Tarjeta**\nDesc: {descripcion}\nMonto: ${monto}\nFecha: {fecha_gasto}\nCuenta: {target_account['nombre']}")
            else:
                await update.message.reply_text("❌ Error creando compra tarjeta.")
                
        else:
            # GASTO NORMAL (Cash/Débito)
            supabase.table("movimientos").insert({
                "fecha": str(fecha_gasto),
                "monto": monto,
                "descripcion": descripcion,
                "cuenta_id": target_account['id'],
                "categoria_id": categoria['id'],
                "tipo": "GASTO",
                "source": "telegram_bot"
            }).execute()
            
            await update.message.reply_text(f"✅ **Gasto Guardado**\nDesc: {descripcion}\nMonto: ${monto}\nFecha: {fecha_gasto}\nCuenta: {target_account['nombre']}")

    except Exception as e:
        logger.error(f"Error DB: {e}")
        await update.message.reply_text(f"❌ Error interno: {str(e)}")

# ==========================================
# 4. GESTIÓN DEL CICLO DE VIDA (FastAPI + Bot)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- ARRANQUE ---
    if not TELEGRAM_TOKEN:
        logger.error("No se encontró TELEGRAM_TOKEN. El bot no arrancará.")
        yield
        return

    # Crear la aplicación del bot
    bot_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Añadir manejadores
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Inicializar y arrancar el bot
    await bot_app.initialize()
    await bot_app.start()
    
    # Comenzar el polling en modo no bloqueante
    await bot_app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    
    logger.info("🤖 Bot de Telegram iniciado correctamente!")
    
    yield # Aquí FastAPI ejecuta el servidor web
    
    # --- APAGADO ---
    logger.info("🛑 Deteniendo Bot de Telegram...")
    await bot_app.updater.stop()
    await bot_app.stop()
    await bot_app.shutdown()

# ==========================================
# 5. APP FASTAPI (Keep-Alive para Render)
# ==========================================
app = FastAPI(lifespan=lifespan)

@app.get("/")
def health_check():
    return {"status": "ok", "bot": "running"}