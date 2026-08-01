import os
import random
import logging
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)

# ==============================================================================
# 1. SERVIDOR WEB FALSO PARA RENDER (Mantiene el servicio activo en 'Live')
# ==============================================================================
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

# ==============================================================================
# 2. CONFIGURACIÓN DE ADMIN, RAREZAS, CARTAS Y AUTOMATIZACIÓN
# ==============================================================================
# ⚠️ CAMBIA ESTE NÚMERO POR TU ID REAL DE TELEGRAM
ADMIN_ID = 5352886076 

# Configuraciones de Drops Automáticos
MENSAJES_PARA_DROP = 20    # Dropea una carta cada X mensajes en el chat
MINUTOS_PARA_DROP = 45     # Dropea una carta si pasan X minutos sin importar la actividad

RAREZAS = {
    "UR": {"peso": 1.5, "estrellas": "⭐⭐⭐⭐⭐ [UR]"},
    "SSS": {"peso": 8.5, "estrellas": "⭐⭐⭐⭐ [SSS]"},
    "S": {"peso": 20.0, "estrellas": "⭐⭐⭐ [S]"},
    "A": {"peso": 30.0, "estrellas": "⭐⭐ [A]"},
    "B": {"peso": 40.0, "estrellas": "⭐ [B]"}
}

CARTAS = [
    {"id": "c1", "nombre": "Guerrera Novata", "rareza": "B", "foto": "https://i.imgur.com/EJEMPLO1.jpg"},
    {"id": "c2", "nombre": "Mago del Bosque", "rareza": "A", "foto": "https://i.imgur.com/EJEMPLO2.jpg"},
    {"id": "c3", "nombre": "Caballero Oscuro", "rareza": "S", "foto": "https://i.imgur.com/EJEMPLO3.jpg"},
    {"id": "c4", "nombre": "Reina Celestial", "rareza": "SSS", "foto": "https://i.imgur.com/EJEMPLO4.jpg"},
    {"id": "c5", "nombre": "Deidad Suprema UR", "rareza": "UR", "foto": "https://i.imgur.com/EJEMPLO5.jpg"},
]

# Almacenamiento temporal en memoria
inventarios = {}          # { user_id: [carta1, carta2, ...] }
carta_activa = {}         # { chat_id: carta_actual_sin_reclamar }
ultimo_mensaje_inv = {}   # { user_id: message_id }
contador_mensajes = {}    # { chat_id: int }
tareas_tiempo = {}        # { chat_id: asyncio.Task }

def elegir_carta_aleatoria():
    pool = []
    for carta in CARTAS:
        rareza_info = RAREZAS.get(carta["rareza"], {"peso": 10.0})
        peso = int(rareza_info["peso"] * 10)
        pool.extend([carta] * peso)
    return random.choice(pool)

async def auto_borrar_comando(update: Update):
    """Función auxiliar para borrar el mensaje del comando y evitar spam."""
    if update.message and update.effective_chat.type in ["group", "supergroup"]:
        try:
            await update.message.delete()
        except Exception:
            pass  # Si no tiene permisos de admin para borrar, ignora el error

async def ejecutar_drop(bot, chat_id, carta_forzada=None, motivo=""):
    if carta_forzada:
        carta = carta_forzada
    else:
        carta = elegir_carta_aleatoria()

    carta_activa[chat_id] = carta
    info_rareza = RAREZAS[carta["rareza"]]["estrellas"]

    keyboard = [[InlineKeyboardButton("🃏 ¡RECLAMAR CARTA!", callback_data=f"claim_{carta['id']}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    subtitulo = f"\n_{motivo}_" if motivo else ""

    await bot.send_photo(
        chat_id=chat_id,
        photo=carta["foto"],
        caption=f"🚨 **¡UNA CARTA SALVAJE HA APARECIDO!** 🚨{subtitulo}\n\n"
                f"🎴 **{carta['nombre']}**\n"
                f"📊 Rareza: {info_rareza}\n\n"
                f"_¡El primero en presionar el botón se la queda!_",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

def reiniciar_temporizador_chat(app_or_context, chat_id):
    if chat_id in tareas_tiempo and not tareas_tiempo[chat_id].done():
        tareas_tiempo[chat_id].cancel()

    bot = app_or_context.bot if hasattr(app_or_context, 'bot') else app_or_context

    async def _loop_tiempo():
        while True:
            await asyncio.sleep(MINUTOS_PARA_DROP * 60)
            await ejecutar_drop(bot, chat_id, motivo="Drop automático por tiempo de espera")
            if chat_id in contador_mensajes:
                contador_mensajes[chat_id] = 0

    tareas_tiempo[chat_id] = asyncio.create_task(_loop_tiempo())

# ==============================================================================
# 3. COMANDOS Y MANEJADORES DE MENSAJES
# ==============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await auto_borrar_comando(update)
    chat_id = update.effective_chat.id
    reiniciar_temporizador_chat(context, chat_id)
    await update.message.reply_text(
        "✨ **¡Bienvenido al Sistema de Gacha de Cartas!** ✨\n\n"
        "Comandos disponibles para todos:\n"
        "• `/drop` - Hace aparecer una carta en el grupo.\n"
        "• `/inventario` - Revisa tu colección de cartas.\n\n"
        "Comandos de Administradora:\n"
        "• `/drop ID_carta` - Fuerza la aparición de una carta específica.\n"
        "• `/dar ID_carta` - (Respondiendo a un usuario) Otorga una carta directa.\n"
        "• `/quitar ID_carta` - (Respondiendo a un usuario) Quita esa carta del inventario."
    )

async def drop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await auto_borrar_comando(update)
    chat_id = update.effective_chat.id
    user = update.effective_user
    args = context.args

    carta_forzada = None
    if args and user.id == ADMIN_ID:
        carta_id = args[0]
        carta_forzada = next((c for c in CARTAS if c["id"] == carta_id), None)
        if not carta_forzada:
            msg = await context.bot.send_message(chat_id, f"❌ No existe ninguna carta con el ID `{carta_id}`.")
            await asyncio.sleep(5)
            try: await msg.delete()
            except: pass
            return

    await ejecutar_drop(context.bot, chat_id, carta_forzada=carta_forzada)
    contador_mensajes[chat_id] = 0
    reiniciar_temporizador_chat(context, chat_id)

async def manejar_mensajes_grupo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or update.effective_chat.type not in ["group", "supergroup"]:
        return

    chat_id = update.effective_chat.id

    if chat_id not in tareas_tiempo:
        reiniciar_temporizador_chat(context, chat_id)

    contador_mensajes[chat_id] = contador_mensajes.get(chat_id, 0) + 1

    if contador_mensajes[chat_id] >= MENSAJES_PARA_DROP:
        contador_mensajes[chat_id] = 0
        await ejecutar_drop(context.bot, chat_id, motivo="Drop automático por actividad del grupo")
        reiniciar_temporizador_chat(context, chat_id)

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
    await auto_borrar_comando(update)
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_cards = inventarios.get(user.id, [])

    # Intento seguro de borrar el mensaje anterior de inventario
    if user.id in ultimo_mensaje_inv:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=ultimo_mensaje_inv[user.id])
        except Exception:
            pass

    nombre_usuario = user.username or user.first_name

    if not user_cards:
        try:
            msg = await context.bot.send_message(
                chat_id,
                f"📦 **Inventario de @{nombre_usuario}**\n\n"
                "No tienes cartas en tu colección todavía. ¡Usa `/drop` o presiona el botón cuando aparezca una!"
            )
            ultimo_mensaje_inv[user.id] = msg.message_id
        except Exception as e:
            logging.error(f"Error al enviar inventario vacío: {e}")
        return

    conteo = {"UR": 0, "SSS": 0, "S": 0, "A": 0, "B": 0}
    for c in user_cards:
        if c["rareza"] in conteo:
            conteo[c["rareza"]] += 1

    texto = f"📦 **COLECCIÓN DE CARTAS: @{nombre_usuario}**\n"
    texto += f"📊 **Total de cartas:** {len(user_cards)}\n"
    texto += "----------------------------------\n"
    texto += f"🌟 UR: {conteo['UR']} | ⭐⭐⭐⭐ SSS: {conteo['SSS']} | ⭐⭐⭐ S: {conteo['S']}\n"
    texto += f"⭐⭐ A: {conteo['A']} | ⭐ B: {conteo['B']}\n"
    texto += "----------------------------------\n\n"
    texto += "📜 **Tus últimas cartas obtenidas:**\n"

    for i, c in enumerate(user_cards[-10:], 1):
        estrellas = RAREZAS.get(c["rareza"], {}).get("estrellas", c["rareza"])
        texto += f"{i}. `{c['id']}` - **{c['nombre']}** ({estrellas})\n"

    try:
        msg = await context.bot.send_message(chat_id, texto, parse_mode="Markdown")
        ultimo_mensaje_inv[user.id] = msg.message_id
    except Exception as e:
        logging.error(f"Error enviando mensaje de inventario: {e}")
        try:
            texto_limpio = texto.replace("**", "").replace("`", "").replace("_", "")
            msg = await context.bot.send_message(chat_id, texto_limpio)
            ultimo_mensaje_inv[user.id] = msg.message_id
        except Exception as ex:
            logging.error(f"Error crítico al enviar inventario: {ex}")

async def dar_carta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await auto_borrar_comando(update)
    user = update.effective_user
    chat_id = update.effective_chat.id

    if user.id != ADMIN_ID:
        return

    if not update.message.reply_to_message:
        msg = await context.bot.send_message(chat_id, "⚠️ **Modo de uso:** Responde al mensaje de la persona a la que quieres darle la carta y escribe `/dar ID_CARTA`.")
        await asyncio.sleep(5)
        try: await msg.delete()
        except: pass
        return

    args = context.args
    if not args:
        msg = await context.bot.send_message(chat_id, "⚠️ Indica el ID de la carta. Ejemplo: `/dar c1`")
        await asyncio.sleep(5)
        try: await msg.delete()
        except: pass
        return

    carta_id = args[0]
    carta = next((c for c in CARTAS if c["id"] == carta_id), None)
    if not carta:
        msg = await context.bot.send_message(chat_id, f"❌ No existe ninguna carta con el ID `{carta_id}`.")
        await asyncio.sleep(5)
        try: await msg.delete()
        except: pass
        return

    target_user = update.message.reply_to_message.from_user

    if target_user.id not in inventarios:
        inventarios[target_user.id] = []

    inventarios[target_user.id].append(carta)
    info_rareza = RAREZAS[carta["rareza"]]["estrellas"]

    await context.bot.send_message(
        chat_id,
        f"🎁 **¡CARTA OTORGADA!**\n\n"
        f"Se ha añadido **{carta['nombre']}** ({info_rareza}) directamente al inventario de @{target_user.username or target_user.first_name}."
    )

async def quitar_carta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await auto_borrar_comando(update)
    user = update.effective_user
    chat_id = update.effective_chat.id

    if user.id != ADMIN_ID:
        return

    if not update.message.reply_to_message:
        msg = await context.bot.send_message(chat_id, "⚠️ **Modo de uso:** Responde al mensaje de la persona a la que quieres quitarle la carta y escribe `/quitar ID_CARTA`.")
        await asyncio.sleep(5)
        try: await msg.delete()
        except: pass
        return

    args = context.args
    if not args:
        msg = await context.bot.send_message(chat_id, "⚠️ Indica el ID de la carta. Ejemplo: `/quitar c1`")
        await asyncio.sleep(5)
        try: await msg.delete()
        except: pass
        return

    carta_id = args[0]
    target_user = update.message.reply_to_message.from_user

    if target_user.id not in inventarios or not inventarios[target_user.id]:
        msg = await context.bot.send_message(chat_id, f"❌ @{target_user.username or target_user.first_name} no tiene cartas en su inventario.")
        await asyncio.sleep(5)
        try: await msg.delete()
        except: pass
        return

    user_cards = inventarios[target_user.id]
    carta_a_remover = next((c for c in user_cards if c["id"] == carta_id), None)

    if not carta_a_remover:
        msg = await context.bot.send_message(chat_id, f"❌ El usuario no posee la carta con ID `{carta_id}`.")
        await asyncio.sleep(5)
        try: await msg.delete()
        except: pass
        return

    user_cards.remove(carta_a_remover)
    await context.bot.send_message(
        chat_id,
        f"🗑️ Se ha removido la carta **{carta_a_remover['nombre']}** del inventario de @{target_user.username or target_user.first_name}."
    )

# ==============================================================================
# 4. INICIALIZACIÓN DEL BOT
# ==============================================================================
if __name__ == "__main__":
    TOKEN = os.environ.get("TELEGRAM_TOKEN")
    if not TOKEN:
        print("Error: Falta la variable de entorno TELEGRAM_TOKEN.")
    else:
        app = ApplicationBuilder().token(TOKEN).build()

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("drop", drop))
        app.add_handler(CommandHandler("inventario", inventario))
        app.add_handler(CommandHandler("dar", dar_carta))
        app.add_handler(CommandHandler("quitar", quitar_carta))
        app.add_handler(CallbackQueryHandler(claim_callback, pattern="^claim_"))

        # Contador de mensajes en grupos
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), manejar_mensajes_grupo))

        print("🤖 Bot listo con auto-borrado y web server encendido...")
        app.run_polling()


