import os
import random
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

# --- SERVIDOR WEB FALSO PARA RENDER (Satisface el puerto web obligatorio) ---
def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    class SimpleHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot Gacha is active and running!")
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    server.serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()

# --- 1. CONFIGURACIÓN DE CARTAS Y RAREZAS ---
RAREZAS = {
    "UR": {"peso": 1.5, "estrellas": "⭐⭐⭐⭐⭐ [UR]"},
    "SSS": {"peso": 8.5, "estrellas": "⭐⭐⭐⭐ [SSS]"},
    "S": {"peso": 20.0, "estrellas": "⭐⭐⭐ [S]"},
    "A": {"peso": 30.0, "estrellas": "⭐⭐ [A]"},
    "B": {"peso": 40.0, "estrellas": "⭐ [B]"}
}

CARTAS = [
    {"id": "c1", "nombre": "Culona de Prueba", "rareza": "B", "foto": "[https://t.me/WaifuGachaArchivePrivate/2?size=l](https://t.me/WaifuGachaArchivePrivate/2?size=l)"},
    {"id": "c2", "nombre": "Mago del Bosque", "rareza": "A", "foto": "https://t.me/c/4347933087/26"},
    {"id": "c3", "nombre": "Caballero Oscuro", "rareza": "S", "foto": "https://t.me/c/4347933087/26"},
    {"id": "c4", "nombre": "Reina Celestial", "rareza": "SSS", "foto": "https://t.me/c/4347933087/26"},
    {"id": "c5", "nombre": "Deidad Suprema UR", "rareza": "UR", "foto": "https://i.imgur.com/EJEMPLO5.jpg"},
]

inventarios = {}      
carta_activa = {}     
ultimo_mensaje_inv = {} 

# ⚠️ ¡CAMBIA ESTE 123456789 POR TU ID REAL DE TELEGRAM!
ADMIN_ID = 5352886076 

def elegir_carta_aleatoria():
    pool = []
    for carta in CARTAS:
        rareza_info = RAREZAS.get(carta["rareza"], {"peso": 10.0})
        peso = int(rareza_info["peso"] * 10)
        pool.extend([carta] * peso)
    return random.choice(pool)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✨ **¡Bienvenido al Sistema de Gacha de Cartas!** ✨\n\n"
        "Comandos disponibles:\n"
        "• `/drop` - Intenta invocar una carta en el grupo.\n"
        "• `/inventario` - Revisa tu colección de cartas.\n"
        "• `/dar @usuario ID_carta` - (Admin) Da una carta por concurso.\n"
        "• `/quitar @usuario ID_carta` - (Admin) Quita una carta."
    )

async def drop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    carta = elegir_carta_aleatoria()
    carta_activa[chat_id] = carta
    
    info_rareza = RAREZAS[carta["rareza"]]["estrellas"]
    
    keyboard = [[InlineKeyboardButton("🃏 ¡RECLAMAR CARTA!", callback_data=f"claim_{carta['id']}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_photo(
        chat_id=chat_id,
        photo=carta["foto"],
        caption=f"🚨 **¡UNA CARTA SALVAJE HA APARECIDO!** 🚨\n\n"
                f"🎴 **{carta['nombre']}**\n"
                f"📊 Rareza: {info_rareza}\n\n"
                f"_¡El primero en presionar el botón se la queda!_",
                reply_markup=reply_markup,
                parse_mode="Markdown"
    )

async def claim_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    
    if chat_id not in carta_activa or carta_activa[chat_id] is None:
        await query.answer("❌ ¡Esta carta ya fue reclamada o expiró!", show_alert=True)
        return

    carta = carta_activa[chat_id]
    carta_activa[chat_id] = None 
    
    if user.id not in inventarios:
        inventarios[user.id] = []
    inventarios[user.id].append(carta)
    
    info_rareza = RAREZAS[carta["rareza"]]["estrellas"]
    
    await query.answer(f"🎉 ¡Felicidades! Has reclamado a {carta['nombre']}")
    await query.edit_message_caption(
        caption=f"✅ **CARTA RECLAMADA**\n\n"
                f"🎴 **{carta['nombre']}** ({info_rareza})\n"
                f"👤 Dueño actual: @{user.username or user.first_name}",
        reply_markup=None
    )

async def inventario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_cards = inventarios.get(user.id, [])
    
    if user.id in ultimo_mensaje_inv:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=ultimo_mensaje_inv[user.id])
        except Exception:
            pass 

    if not user_cards:
        msg = await update.message.reply_text(f"📦 **Inventario de @{user.username or user.first_name}**\n\nNo tienes cartas en tu colección todavía. ¡Usa `/drop`!")
        ultimo_mensaje_inv[user.id] = msg.message_id
        return

    conteo = {"UR": 0, "SSS": 0, "S": 0, "A": 0, "B": 0}
    for c in user_cards:
        if c["rareza"] in conteo:
            conteo[c["rareza"]] += 1

    texto = f"📦 **COLECCIÓN DE CARTAS: @{user.username or user.first_name}**\n"
    texto += f"📊 **Total de cartas:** {len(user_cards)}\n"
    texto += "----------------------------------\n"
    texto += f"🌟 UR: {conteo['UR']} | ⭐⭐⭐⭐ SSS: {conteo['SSS']} | ⭐⭐⭐ S/E: {conteo['S']}\n"
    texto += f"⭐⭐ A: {conteo['A']} | ⭐ B: {conteo['B']}\n"
    texto += "----------------------------------\n\n"
    texto += "📜 **Tus últimas cartas obtenidas:**\n"
    
    for i, c in enumerate(user_cards[-10:], 1):
        estrellas = RAREZAS[c["rareza"]]["estrellas"]
        texto += f"{i}. `{c['id']}` - **{c['nombre']}** ({estrellas})\n"
    
    msg = await update.message.reply_text(texto, parse_mode="Markdown")
    ultimo_mensaje_inv[user.id] = msg.message_id

async def dar_carta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("⛔ No tienes permisos de administración.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("⚠️ Uso correcto: `/dar @usuario id_carta`")
        return
    mencion, carta_id = args[0], args[1]
    carta_encontrada = next((c for c in CARTAS if c["id"] == carta_id), None)
    if not carta_encontrada:
        await update.message.reply_text(f"❌ No existe ninguna carta con el ID `{carta_id}`.")
        return
    await update.message.reply_text(f"🎁 Administradora otorgó la carta **{carta_encontrada['nombre']}** a {mencion}.")

async def quitar_carta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("⛔ No tienes permisos.")
        return
    await update.message.reply_text("🛠️ Función de ajuste de rework activada.")

if __name__ == "__main__":
    TOKEN = os.environ.get("TELEGRAM_TOKEN")
    if not TOKEN:
        print("Error: Falta el TELEGRAM_TOKEN.")
    else:
        app = ApplicationBuilder().token(TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("drop", drop))
        app.add_handler(CommandHandler("inventario", inventario))
        app.add_handler(CommandHandler("dar", dar_carta))
        app.add_handler(CommandHandler("quitar", quitar_carta))
        app.add_handler(CallbackQueryHandler(claim_callback, pattern="^claim_"))
        print("🤖 Bot listo y web server encendido...")
        app.run_polling()
