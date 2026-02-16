import os
import re
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta  # <--- AQUÍ FALTABA TIMEDELTA
from dateutil.relativedelta import relativedelta

from fastapi import FastAPI
from supabase import create_client
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# ==========================================
# 1. CONFIGURACIÓN
# ==========================================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_SECRET") or os.environ.get("TELEGRAM_TOKEN")
ALLOWED_USER_ID = os.environ.get("ALLOWED_USER_ID")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==========================================
# 2. FUNCIONES DE AYUDA
# ==========================================
def fmt_money(val):
    return f"${val:,.0f}".replace(",", ".")

def get_account_by_name(name):
    try:
        res = supabase.table("cuentas").select("*").execute()
        cuentas = res.data or []
        for acc in cuentas:
            if name.lower() in acc['nombre'].lower(): return acc
        for acc in cuentas:
            if "efectivo" in acc['nombre'].lower(): return acc
        return cuentas[0] if cuentas else None
    except: return None

def get_category_general():
    try:
        res = supabase.table("categorias").select("*").execute()
        cats = res.data or []
        for cat in cats:
            if "general" in cat['nombre'].lower(): return cat
        return cats[0] if cats else None
    except: return None

def get_monthly_balance():
    try:
        # Fechas
        today = date.today()
        first_day = date(today.year, today.month, 1)
        # Aquí fallaba antes por falta de timedelta
        last_day = first_day + relativedelta(months=1) - timedelta(days=1)
        
        logger.info(f"🔍 Consultando balance desde {first_day} hasta {last_day}")

        # Consulta DB
        res = supabase.table("movimientos")\
            .select("tipo, monto, fecha")\
            .gte("fecha", str(first_day))\
            .lte("fecha", str(last_day))\
            .execute()
        
        data = res.data or []
        
        # LOG PARA DEBUG: Ver qué devuelve Supabase en la consola de Render
        logger.info(f"📊 Datos encontrados: {len(data)} movimientos")
        
        ingresos = sum(d['monto'] for d in data if d['tipo'] == 'INGRESO')
        gastos = sum(d['monto'] for d in data if d['tipo'] in ['GASTO', 'COMPRA_TARJETA'])
        
        return ingresos, gastos
    except Exception as e:
        logger.error(f"❌ Error calculando balance: {e}")
        return 0, 0

# ==========================================
# 3. LÓGICA REUTILIZABLE
# ==========================================

async def reply_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Función dedicada a enviar el saldo."""
    ing, gas = get_monthly_balance()
    neto = ing - gas
    
    # Nombre del mes en español simple
    meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    mes_nombre = meses[date.today().month - 1]

    await update.message.reply_text(
        f"📅 *Balance {mes_nombre}*\n\n"
        f"📥 Ingresos: `{fmt_money(ing)}`\n"
        f"🛒 Consumo:  `{fmt_money(gas)}`\n"
        f"-------------------\n"
        f"💵 *Neto: {fmt_money(neto)}*",
        parse_mode=ParseMode.MARKDOWN
    )

async def show_menu(update: Update):
    """Muestra el teclado persistente."""
    keyboard = [
        [KeyboardButton("💰 Balance Mes"), KeyboardButton("❓ Ayuda")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("¿Qué quieres hacer?", reply_markup=reply_markup)

# ==========================================
# 4. HANDLERS (COMANDOS Y MENSAJES)
# ==========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Bot Finanzas Pro*\n\n"
        "Escribe un gasto (ej: `1500 Cena`) o usa los botones de abajo.",
        parse_mode=ParseMode.MARKDOWN
    )
    await show_menu(update)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "💡 *Guía Rápida:*\n\n"
        "1️⃣ *Carga Simple:* `1500 Super`\n"
        "2️⃣ *Fecha Específica:* `50000 Alquiler 2026-04-01`\n"
        "3️⃣ *Tarjeta:* `25000 Zapatillas Visa`\n"
        "4️⃣ *Ingreso:* Usa la App web o configura una palabra clave.\n\n"
        "_Toca los botones de abajo para ver tu saldo._"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if ALLOWED_USER_ID and user_id != str(ALLOWED_USER_ID):
        await update.message.reply_text("⛔ No autorizado.")
        return

    text = update.message.text

    # --- BOTONES ---
    if text == "💰 Balance Mes":
        await reply_balance(update, context)
        return

    if text == "❓ Ayuda":
        await help_command(update, context)
        return

    # --- PROCESAR GASTO ---
    match_monto = re.search(r'(\d+([.,]\d{1,2})?)', text)
    if not match_monto:
        await update.message.reply_text("🤷‍♂️ No entendí. Escribe el monto primero (ej: `2500 Taxi`).", parse_mode=ParseMode.MARKDOWN)
        return

    monto = float(match_monto.group(1).replace(',', '.'))
    clean_text = text.replace(match_monto.group(0), '').strip()
    
    fecha_gasto = date.today()
    match_date = re.search(r'(\d{4}-\d{2}-\d{2})', clean_text)
    if match_date:
        try:
            fecha_str = match_date.group(1)
            fecha_gasto = datetime.strptime(fecha_str, "%Y-%m-%d").date()
            clean_text = clean_text.replace(fecha_str, '').strip()
        except: pass

    target_account = None
    try:
        all_accounts_res = supabase.table("cuentas").select("nombre, id, tipo").execute()
        all_accounts = all_accounts_res.data or []
    except: all_accounts = []
    
    words = clean_text.split()
    desc_words = []
    
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
    
    if not target_account:
        target_account = get_account_by_name("Efectivo")

    descripcion = " ".join(desc_words) or "Gasto Telegram"
    categoria = get_category_general()

    if not target_account or not categoria:
        await update.message.reply_text("❌ Error: Faltan cuentas/categorías en DB.")
        return

    try:
        if target_account['tipo'] == 'CREDITO':
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
                supabase.table("cuotas_tarjeta").insert({
                    "compra_id": compra.data[0]['id'],
                    "nro_cuota": 1,
                    "fecha_cuota": str(fecha_gasto),
                    "monto_cuota": monto,
                    "estado": "pendiente"
                }).execute()
                await update.message.reply_text(
                    f"💳 *Tarjeta Detectada*\n\n"
                    f"📝 *Desc:* {descripcion}\n"
                    f"💲 *Monto:* `{fmt_money(monto)}`\n"
                    f"🏦 *Cuenta:* {target_account['nombre']}",
                    parse_mode=ParseMode.MARKDOWN
                )
        else:
            supabase.table("movimientos").insert({
                "fecha": str(fecha_gasto),
                "monto": monto,
                "descripcion": descripcion,
                "cuenta_id": target_account['id'],
                "categoria_id": categoria['id'],
                "tipo": "GASTO",
                "source": "telegram_bot"
            }).execute()
            await update.message.reply_text(
                f"✅ *Gasto Guardado*\n\n"
                f"📝 {descripcion}\n"
                f"💲 `{fmt_money(monto)}`\n"
                f"🏦 {target_account['nombre']}\n"
                f"📅 {fecha_gasto}",
                parse_mode=ParseMode.MARKDOWN
            )

    except Exception as e:
        logger.error(f"Error DB: {e}")
        await update.message.reply_text("❌ Error guardando.")

# ==========================================
# 5. LIFESPAN & APP
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    if not TELEGRAM_TOKEN:
        logger.error("Falta TELEGRAM_TOKEN")
        yield
        return

    bot_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("saldo", reply_balance)) # Handler directo
    bot_app.add_handler(CommandHandler("ayuda", help_command))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    await bot_app.initialize()
    try:
        await bot_app.bot.delete_webhook(drop_pending_updates=True)
    except: pass
    
    await bot_app.start()
    await bot_app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("🤖 Bot con Botones iniciado!")
    
    yield
    
    await bot_app.updater.stop()
    await bot_app.stop()
    await bot_app.shutdown()

app = FastAPI(lifespan=lifespan)

@app.get("/")
def health_check():
    return {"status": "ok", "bot": "interactive"}