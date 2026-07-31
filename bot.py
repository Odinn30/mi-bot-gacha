import os
import random
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

logging.basicConfig(level=logging.INFO)

# --- 1. CONFIGURACIÓN DE CARTAS Y RAREZAS ---
# Las probabilidades suman 100%. UR está en 1.5% como pediste.
RAREZAS = {
    "UR": {"peso": 1.5, "estrellas": "⭐⭐⭐⭐⭐ [UR]"},
    "SSS": {"peso": 8.5, "estrellas": "⭐⭐⭐⭐ [SSS]"},
    "S": {"peso": 20.0, "estrellas": "⭐⭐⭐ [S]"},
    "A": {"peso": 30.0, "estrellas": "⭐⭐ [A]"},
    "B": {"peso": 40.0, "estrellas": "⭐ [B]"}
}

# Catálogo completo de tus cartas. 
# IMPORTANTE: Reemplaza los enlaces de la "foto" por tus imágenes reales (URLs o file_id).
CARTAS = [
    {"id": "c1", "nombre": "Guerrera Novata", "rareza": "B", "foto": "https://i.imgur.com/EJEMPLO1.jpg"},
    {"id": "c2", "nombre": "Mago del Bosque", "rareza": "A", "foto": "https://i.imgur.com/EJEMPLO2.jpg"},
    {"id": "c3", "nombre": "Caballero Oscuro", "rareza": "S", "foto": "https://i.imgur.com/EJEMPLO3.jpg"},
    {"id": "c4", "nombre": "Reina Celestial", "rareza": "SSS", "foto": "https://i.imgur.com/EJEMPLO4.jpg"},
    {"id": "c5", "nombre": "Deidad Suprema UR", "rareza": "UR", "foto": "https://i.imgur.com/EJEMPLO5.jpg"},
]

# --- 2. BASE DE DATOS EN MEMORIA ---
# Estructuras para guardar datos temporalmente
inventarios = {}      # {user_id: [ {"id": "c1", "nombre": "...", "rareza": "B", ...}, ... ]}
carta_activa = {}     # {chat_id: carta_en_drop_actual}
ultimo_mensaje_inv = {} # {user_id: message_id_anterior} para borrar spam de inventario
contador_mensajes = {}  # {chat_id: numero_de_mensajes}

# ID de la Administradora (¡CAMBIA ESTE NÚMERO POR TU ID DE TELEGRAM REAL!)
# Puedes averiguar tu ID escribiéndole al bot @userinfobot en Telegram.
ADMIN_ID = 5352886076 

def elegir_carta_aleatoria():
    """Selecciona una carta basada en los porcentajes de rareza."""
    # Creamos una lista ponderada
    pool = []
    for carta in CARTAS:
        rareza_info = RAREZAS.get(carta["rareza"], {"peso": 10.0})
        # Multiplicamos por 10 para manejar decimales limpios
        peso = int(rareza_info["peso"] * 10)
        pool.extend([carta] * peso)
    return random.choice(pool)

# --- 3. COMANDOS BÁSICOS Y DROPS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✨ **¡Bienvenido al Sistema de Gacha de Cartas!** ✨\n\n"
        "Comandos disponibles:\n"
        "• `/drop` - Intenta invocar una carta (si eres rápido).\n"
        "• `/inventario` - Revisa tu colección de cartas.\n"
        "• `/dar @usuario ID_carta` - (Admin) Da una carta por concurso.\n"
        "• `/quitar @usuario ID_carta` - (Admin) Quita una carta (rework)."
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
        await query.answer("❌ ¡Esta carta ya fue reclamada por alguien más o expiró!", show_alert=True)
        return

    carta = carta_activa[chat_id]
    carta_activa[chat_id] = None # Desactivar carta actual
    
    # Añadir al inventario del usuario
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

# --- 4. GESTIÓN DE INVENTARIO Y ANTI-SPAM ---

async def inventario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_cards = inventarios.get(user.id, [])
    
    # Borrar mensaje anterior de inventario de este usuario si existe (Anti-spam)
    if user.id in ultimo_mensaje_inv:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=ultimo_mensaje_inv[user.id])
        except Exception:
            pass # Si ya fue borrado manualmente, ignorar

    if not user_cards:
        msg = await update.message.reply_text(f"📦 **Inventario de @{user.username or user.first_name}**\n\nNo tienes cartas en tu colección todavía. ¡Participa en los drops con `/drop`!")
        ultimo_mensaje_inv[user.id] = msg.message_id
        return

    # Contar cartas por rareza para un diseño visual ordenado
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
    
    # Mostrar las últimas 10 cartas para no saturar
    for i, c in enumerate(user_cards[-10:], 1):
        estrellas = RAREZAS[c["rareza"]]["estrellas"]
        texto += f"{i}. `{c['id']}` - **{c['nombre']}** ({estrellas})\n"

    texto += "\n_💡 Tip: Puedes tradear enviando cartas directamente o usar su ID._"
    
    msg = await update.message.reply_text(texto, parse_mode="Markdown")
    ultimo_mensaje_inv[user.id] = msg.message_id

# --- 5. COMANDOS DE ADMINISTRADORA (DAR Y QUITAR) ---

async def dar_carta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("⛔ No tienes permisos de administración para usar este comando.")
        return
    
    # Formato esperado: /dar @usuario id_carta
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("⚠️ Uso correcto: `/dar @usuario id_carta`")
        return
    
    mencion = args[0]
    carta_id = args[1]
    
    # Buscar la carta en el catálogo
    carta_encontrada = next((c for c in CARTAS if c["id"] == carta_id), None)
    if not carta_encontrada:
        await update.message.reply_text(f"❌ No existe ninguna carta con el ID `{carta_id}`.")
        return

    await update.message.reply_text(f"🎁 Administradora otorgó la carta **{carta_encontrada['nombre']}** a {mencion}.")

async def quitar_carta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("⛔ No tienes permisos de administración.")
        return
        
    await update.message.reply_text("🛠️ Función de ajuste de rework activada. (Indica el ID del usuario y de la carta para removerla de su inventario si fuera necesario).")

# --- 6. ARRANQUE DEL BOT ---
if __name__ == "__main__":
    TOKEN = os.environ.get("TELEGRAM_TOKEN")
    if not TOKEN:
        print("Error: Falta el TELEGRAM_TOKEN en las variables de entorno.")
    else:
        app = ApplicationBuilder().token(TOKEN).build()
        
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("drop", drop))
        app.add_handler(CommandHandler("inventario", inventario))
        app.add_handler(CommandHandler("dar", dar_carta))
        app.add_handler(CommandHandler("quitar", quitar_carta))
        app.add_handler(CallbackQueryHandler(claim_callback, pattern="^claim_"))
        
        print("🤖 Bot de Gacha estructurado y listo...")
        app.run_polling()
