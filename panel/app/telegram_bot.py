"""Telegram bot for panel management"""
import asyncio
import logging
import os
import shutil
import zipfile
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import Node, Tunnel, Settings
import httpx

logger = logging.getLogger(__name__)

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
    from telegram.ext import (
        Application, CommandHandler, CallbackQueryHandler, ContextTypes,
        ConversationHandler, MessageHandler, filters
    )
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    logger.warning("python-telegram-bot not installed. Telegram bot will not work.")


# Conversation states
(WAITING_FOR_NODE_NAME, WAITING_FOR_NODE_IP, WAITING_FOR_NODE_PORT, WAITING_FOR_NODE_ROLE,
 WAITING_FOR_TUNNEL_NAME, WAITING_FOR_TUNNEL_CORE, WAITING_FOR_TUNNEL_TYPE, WAITING_FOR_TUNNEL_PORTS,
 WAITING_FOR_TUNNEL_IRAN_NODE, WAITING_FOR_TUNNEL_FOREIGN_NODE, WAITING_FOR_TUNNEL_REMOTE_IP) = range(11)


class TelegramBot:
    """Telegram bot for managing panel"""
    
    def __init__(self):
        self.application: Optional[Application] = None
        self.enabled = False
        self.bot_token: Optional[str] = None
        self.admin_ids: List[str] = []
        self.backup_task: Optional[asyncio.Task] = None
        self.backup_enabled = False
        self.backup_interval = 60
        self.backup_interval_unit = "minutes"
        self.user_languages: Dict[int, str] = {}  # user_id -> language (en/fa)
        self.user_states: Dict[int, Dict] = {}  # user_id -> state data
    
    async def load_settings(self):
        """Load settings from database"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Settings).where(Settings.key == "telegram"))
            setting = result.scalar_one_or_none()
            if setting and setting.value:
                self.enabled = setting.value.get("enabled", False)
                self.bot_token = setting.value.get("bot_token")
                self.admin_ids = setting.value.get("admin_ids", [])
                self.backup_enabled = setting.value.get("backup_enabled", False)
                self.backup_interval = setting.value.get("backup_interval", 60)
                self.backup_interval_unit = setting.value.get("backup_interval_unit", "minutes")
            else:
                self.enabled = False
                self.bot_token = None
                self.admin_ids = []
                self.backup_enabled = False
                self.backup_interval = 60
                self.backup_interval_unit = "minutes"
    
    def get_lang(self, user_id: int) -> str:
        """Get user language"""
        return self.user_languages.get(user_id, "en")
    
    def t(self, user_id: int, key: str, **kwargs) -> str:
        """Translate text"""
        lang = self.get_lang(user_id)
        translations = {
            "en": {
                "welcome": "👋 Welcome to Smite Panel Bot!\n\nSelect an action:",
                "access_denied": "❌ Access denied. You are not an admin.",
                "add_iran_node": "➕ Add Iran Node",
                "add_foreign_node": "➕ Add Foreign Node",
                "remove_iran_node": "➖ Remove Iran Node",
                "remove_foreign_node": "➖ Remove Foreign Node",
                "create_tunnel": "🔗 Create Tunnel",
                "remove_tunnel": "🗑️ Remove Tunnel",
                "node_stats": "📊 Node Stats",
                "tunnel_stats": "📊 Tunnel Stats",
                "logs": "📋 Logs",
                "backup": "📦 Backup",
                "language": "🌐 Language",
                "enter_node_name": "Enter node name:",
                "enter_node_ip": "Enter node IP address:",
                "enter_node_port": "Enter node API port (default: 8888):",
                "node_added": "✅ Node added successfully!",
                "node_removed": "✅ Node removed successfully!",
                "select_node_to_remove": "Select node to remove:",
                "enter_tunnel_name": "Enter tunnel name:",
                "select_tunnel_core": "Select tunnel core:",
                "select_tunnel_type": "Select tunnel type:",
                "enter_tunnel_ports": "Enter tunnel ports (comma-separated, e.g., 8080,8081,8082):",
                "select_iran_node": "Select Iran node:",
                "select_foreign_node": "Select foreign node:",
                "enter_remote_ip": "Enter remote IP (default: 127.0.0.1):",
                "tunnel_created": "✅ Tunnel created successfully!",
                "select_tunnel_to_remove": "Select tunnel to remove:",
                "tunnel_removed": "✅ Tunnel removed successfully!",
                "cancel": "❌ Cancelled",
                "back": "🔙 Back",
                "english": "🇬🇧 English",
                "farsi": "🇮🇷 Farsi",
                "language_set": "✅ Language set to {lang}",
                "no_nodes": "📭 No nodes found.",
                "no_tunnels": "📭 No tunnels found.",
                "error": "❌ Error: {error}",
            },
            "fa": {
                "welcome": "👋 به ربات پنل اسمیت خوش آمدید!\n\nیک عمل را انتخاب کنید:",
                "access_denied": "❌ دسترسی رد شد. شما ادمین نیستید.",
                "add_iran_node": "➕ افزودن نود ایران",
                "add_foreign_node": "➕ افزودن نود خارجی",
                "remove_iran_node": "➖ حذف نود ایران",
                "remove_foreign_node": "➖ حذف نود خارجی",
                "create_tunnel": "🔗 ایجاد تونل",
                "remove_tunnel": "🗑️ حذف تونل",
                "node_stats": "📊 آمار نودها",
                "tunnel_stats": "📊 آمار تونل‌ها",
                "logs": "📋 لاگ‌ها",
                "backup": "📦 پشتیبان",
                "language": "🌐 زبان",
                "enter_node_name": "نام نود را وارد کنید:",
                "enter_node_ip": "آدرس IP نود را وارد کنید:",
                "enter_node_port": "پورت API نود را وارد کنید (پیش‌فرض: 8888):",
                "node_added": "✅ نود با موفقیت افزوده شد!",
                "node_removed": "✅ نود با موفقیت حذف شد!",
                "select_node_to_remove": "نود را برای حذف انتخاب کنید:",
                "enter_tunnel_name": "نام تونل را وارد کنید:",
                "select_tunnel_core": "هسته تونل را انتخاب کنید:",
                "select_tunnel_type": "نوع تونل را انتخاب کنید:",
                "enter_tunnel_ports": "پورت‌های تونل را وارد کنید (جدا شده با کاما، مثال: 8080,8081,8082):",
                "select_iran_node": "نود ایران را انتخاب کنید:",
                "select_foreign_node": "نود خارجی را انتخاب کنید:",
                "enter_remote_ip": "IP از راه دور را وارد کنید (پیش‌فرض: 127.0.0.1):",
                "tunnel_created": "✅ تونل با موفقیت ایجاد شد!",
                "select_tunnel_to_remove": "تونل را برای حذف انتخاب کنید:",
                "tunnel_removed": "✅ تونل با موفقیت حذف شد!",
                "cancel": "❌ لغو شد",
                "back": "🔙 بازگشت",
                "english": "🇬🇧 انگلیسی",
                "farsi": "🇮🇷 فارسی",
                "language_set": "✅ زبان به {lang} تنظیم شد",
                "no_nodes": "📭 نودی یافت نشد.",
                "no_tunnels": "📭 تونلی یافت نشد.",
                "error": "❌ خطا: {error}",
            }
        }
        text = translations.get(lang, translations["en"]).get(key, key)
        return text.format(**kwargs) if kwargs else text
    
    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        return str(user_id) in self.admin_ids
    
    async def start(self):
        """Start Telegram bot"""
        if not TELEGRAM_AVAILABLE:
            logger.error("python-telegram-bot not available. Cannot start bot.")
            return False
        
        await self.load_settings()
        
        if not self.enabled or not self.bot_token:
            logger.info("Telegram bot not enabled or token not set")
            return False
        
        # Stop existing instance if running
        await self.stop()
        
        try:
            self.application = Application.builder().token(self.bot_token).build()
            
            # Conversation handler for adding nodes
            add_node_conv = ConversationHandler(
                entry_points=[CallbackQueryHandler(self.add_node_start, pattern="^add_node_")],
                states={
                    WAITING_FOR_NODE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_node_name)],
                    WAITING_FOR_NODE_IP: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_node_ip)],
                    WAITING_FOR_NODE_PORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_node_port)],
                },
                fallbacks=[CallbackQueryHandler(self.cancel_operation, pattern="^cancel$")],
            )
            
            # Conversation handler for removing nodes
            remove_node_conv = ConversationHandler(
                entry_points=[CallbackQueryHandler(self.remove_node_start, pattern="^remove_node_")],
                states={
                    WAITING_FOR_NODE_NAME: [CallbackQueryHandler(self.remove_node_confirm, pattern="^rm_node_")],
                },
                fallbacks=[CallbackQueryHandler(self.cancel_operation, pattern="^cancel$")],
            )
            
            # Conversation handler for creating tunnels
            create_tunnel_conv = ConversationHandler(
                entry_points=[CallbackQueryHandler(self.create_tunnel_start, pattern="^create_tunnel$")],
                states={
                    WAITING_FOR_TUNNEL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.create_tunnel_name)],
                    WAITING_FOR_TUNNEL_CORE: [CallbackQueryHandler(self.create_tunnel_core, pattern="^core_")],
                    WAITING_FOR_TUNNEL_TYPE: [CallbackQueryHandler(self.create_tunnel_type, pattern="^type_")],
                    WAITING_FOR_TUNNEL_PORTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.create_tunnel_ports)],
                    WAITING_FOR_TUNNEL_IRAN_NODE: [CallbackQueryHandler(self.create_tunnel_iran_node, pattern="^iran_node_")],
                    WAITING_FOR_TUNNEL_FOREIGN_NODE: [CallbackQueryHandler(self.create_tunnel_foreign_node, pattern="^foreign_node_")],
                    WAITING_FOR_TUNNEL_REMOTE_IP: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.create_tunnel_remote_ip)],
                },
                fallbacks=[CallbackQueryHandler(self.cancel_operation, pattern="^cancel$")],
            )
            
            # Conversation handler for removing tunnels
            remove_tunnel_conv = ConversationHandler(
                entry_points=[CallbackQueryHandler(self.remove_tunnel_start, pattern="^remove_tunnel$")],
                states={
                    WAITING_FOR_TUNNEL_NAME: [CallbackQueryHandler(self.remove_tunnel_confirm, pattern="^rm_tunnel_")],
                },
                fallbacks=[CallbackQueryHandler(self.cancel_operation, pattern="^cancel$")],
            )
            
            self.application.add_handler(CommandHandler("start", self.cmd_start))
            self.application.add_handler(CommandHandler("help", self.cmd_help))
            self.application.add_handler(CommandHandler("nodes", self.cmd_nodes))
            self.application.add_handler(CommandHandler("tunnels", self.cmd_tunnels))
            self.application.add_handler(CommandHandler("status", self.cmd_status))
            self.application.add_handler(CommandHandler("backup", self.cmd_backup))
            self.application.add_handler(CommandHandler("logs", self.cmd_logs))
            self.application.add_handler(add_node_conv)
            self.application.add_handler(remove_node_conv)
            self.application.add_handler(create_tunnel_conv)
            self.application.add_handler(remove_tunnel_conv)
            self.application.add_handler(CallbackQueryHandler(self.handle_callback))
            
            await self.application.initialize()
            await self.application.start()
            
            # Use drop_pending_updates to avoid conflicts
            await self.application.updater.start_polling(drop_pending_updates=True)
            
            await self.start_backup_task()
            
            logger.info("Telegram bot started successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to start Telegram bot: {e}", exc_info=True)
            # Clean up on failure
            await self.stop()
            return False
    
    async def stop(self):
        """Stop Telegram bot"""
        await self.stop_backup_task()
        
        if self.application:
            try:
                if self.application.updater and self.application.updater.running:
                    await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()
            except Exception as e:
                logger.warning(f"Error stopping Telegram bot: {e}")
            finally:
                self.application = None
                logger.info("Telegram bot stopped")
    
    async def start_backup_task(self):
        """Start automatic backup task"""
        await self.stop_backup_task()
        await self.load_settings()
        
        if self.backup_enabled and self.admin_ids:
            self.backup_task = asyncio.create_task(self._backup_loop())
            logger.info(f"Automatic backup task started: interval={self.backup_interval} {self.backup_interval_unit}")
    
    async def stop_backup_task(self):
        """Stop automatic backup task"""
        if self.backup_task:
            self.backup_task.cancel()
            try:
                await self.backup_task
            except asyncio.CancelledError:
                pass
            self.backup_task = None
            logger.info("Automatic backup task stopped")
    
    async def _backup_loop(self):
        """Background task for automatic backups"""
        try:
            while True:
                await self.load_settings()
                
                if not self.backup_enabled or not self.admin_ids:
                    await asyncio.sleep(60)
                    continue
                
                if self.backup_interval_unit == "hours":
                    sleep_seconds = self.backup_interval * 3600
                else:
                    sleep_seconds = self.backup_interval * 60
                
                await asyncio.sleep(sleep_seconds)
                
                if not self.backup_enabled:
                    continue
                
                try:
                    backup_path = await self.create_backup()
                    if backup_path and self.application and self.application.bot:
                        for admin_id_str in self.admin_ids:
                            try:
                                admin_id = int(admin_id_str)
                                with open(backup_path, 'rb') as f:
                                    await self.application.bot.send_document(
                                        chat_id=admin_id,
                                        document=f,
                                        filename=f"smite_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                                        caption=f"🔄 Automatic backup - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                                    )
                            except Exception as e:
                                logger.error(f"Failed to send backup to admin {admin_id_str}: {e}")
                        
                        if os.path.exists(backup_path):
                            os.remove(backup_path)
                        logger.info("Automatic backup sent successfully")
                except Exception as e:
                    logger.error(f"Error in automatic backup: {e}", exc_info=True)
        except asyncio.CancelledError:
            logger.info("Backup loop cancelled")
            raise
        except Exception as e:
            logger.error(f"Backup loop error: {e}", exc_info=True)
    
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text(self.t(update.effective_user.id, "access_denied"))
            return
        
        await self.show_main_menu(update.message)
    
    async def show_main_menu(self, message):
        """Show main menu with buttons"""
        user_id = message.from_user.id
        keyboard = [
            [
                InlineKeyboardButton(self.t(user_id, "add_iran_node"), callback_data="add_node_iran"),
                InlineKeyboardButton(self.t(user_id, "add_foreign_node"), callback_data="add_node_foreign"),
            ],
            [
                InlineKeyboardButton(self.t(user_id, "remove_iran_node"), callback_data="remove_node_iran"),
                InlineKeyboardButton(self.t(user_id, "remove_foreign_node"), callback_data="remove_node_foreign"),
            ],
            [
                InlineKeyboardButton(self.t(user_id, "create_tunnel"), callback_data="create_tunnel"),
                InlineKeyboardButton(self.t(user_id, "remove_tunnel"), callback_data="remove_tunnel"),
            ],
            [
                InlineKeyboardButton(self.t(user_id, "node_stats"), callback_data="node_stats"),
                InlineKeyboardButton(self.t(user_id, "tunnel_stats"), callback_data="tunnel_stats"),
            ],
            [
                InlineKeyboardButton(self.t(user_id, "logs"), callback_data="logs"),
                InlineKeyboardButton(self.t(user_id, "backup"), callback_data="cmd_backup"),
            ],
            [
                InlineKeyboardButton(self.t(user_id, "language"), callback_data="select_language"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.reply_text(self.t(user_id, "welcome"), reply_markup=reply_markup)
    
    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text(self.t(update.effective_user.id, "access_denied"))
            return
        
        help_text = """📋 Available Commands:

/start - Show main menu
/nodes - List all nodes
/tunnels - List all tunnels
/status - Show panel status
/logs - Show recent logs
/backup - Create and send backup

Use buttons in messages to interact with nodes and tunnels."""
        
        await update.message.reply_text(help_text)
    
    # Node management
    async def add_node_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start adding a node"""
        query = update.callback_query
        await query.answer()
        
        if not self.is_admin(query.from_user.id):
            await query.edit_message_text(self.t(query.from_user.id, "access_denied"))
            return ConversationHandler.END
        
        role = "iran" if "iran" in query.data else "foreign"
        self.user_states[query.from_user.id] = {"role": role, "step": "name"}
        
        cancel_btn = InlineKeyboardButton(self.t(query.from_user.id, "cancel"), callback_data="cancel")
        reply_markup = InlineKeyboardMarkup([[cancel_btn]])
        await query.edit_message_text(self.t(query.from_user.id, "enter_node_name"), reply_markup=reply_markup)
        return WAITING_FOR_NODE_NAME
    
    async def add_node_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle node name input"""
        user_id = update.message.from_user.id
        if user_id not in self.user_states:
            return ConversationHandler.END
        
        self.user_states[user_id]["name"] = update.message.text
        self.user_states[user_id]["step"] = "ip"
        
        cancel_btn = InlineKeyboardButton(self.t(user_id, "cancel"), callback_data="cancel")
        reply_markup = InlineKeyboardMarkup([[cancel_btn]])
        await update.message.reply_text(self.t(user_id, "enter_node_ip"), reply_markup=reply_markup)
        return WAITING_FOR_NODE_IP
    
    async def add_node_ip(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle node IP input"""
        user_id = update.message.from_user.id
        if user_id not in self.user_states:
            return ConversationHandler.END
        
        self.user_states[user_id]["ip"] = update.message.text
        self.user_states[user_id]["step"] = "port"
        
        cancel_btn = InlineKeyboardButton(self.t(user_id, "cancel"), callback_data="cancel")
        reply_markup = InlineKeyboardMarkup([[cancel_btn]])
        await update.message.reply_text(self.t(user_id, "enter_node_port"), reply_markup=reply_markup)
        return WAITING_FOR_NODE_PORT
    
    async def add_node_port(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle node port input and create node"""
        user_id = update.message.from_user.id
        if user_id not in self.user_states:
            return ConversationHandler.END
        
        try:
            port = int(update.message.text) if update.message.text.strip() else 8888
        except ValueError:
            await update.message.reply_text("Invalid port. Using default 8888.")
            port = 8888
        
        state = self.user_states[user_id]
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8000/api/nodes",
                    json={
                        "name": state["name"],
                        "ip_address": state["ip"],
                        "api_port": port,
                        "metadata": {"role": state["role"]}
                    }
                )
                if response.status_code == 200:
                    await update.message.reply_text(self.t(user_id, "node_added"))
                else:
                    await update.message.reply_text(self.t(user_id, "error", error=response.text))
        except Exception as e:
            logger.error(f"Error adding node: {e}", exc_info=True)
            await update.message.reply_text(self.t(user_id, "error", error=str(e)))
        
        del self.user_states[user_id]
        return ConversationHandler.END
    
    async def remove_node_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start removing a node"""
        query = update.callback_query
        await query.answer()
        
        if not self.is_admin(query.from_user.id):
            await query.edit_message_text(self.t(query.from_user.id, "access_denied"))
            return ConversationHandler.END
        
        role = "iran" if "iran" in query.data else "foreign"
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Node))
            nodes = result.scalars().all()
            nodes = [n for n in nodes if n.node_metadata.get("role") == role]
            
            if not nodes:
                await query.edit_message_text(self.t(query.from_user.id, "no_nodes"))
                return ConversationHandler.END
            
            keyboard = []
            for node in nodes:
                keyboard.append([InlineKeyboardButton(
                    f"🗑️ {node.name}",
                    callback_data=f"rm_node_{node.id}"
                )])
            keyboard.append([InlineKeyboardButton(self.t(query.from_user.id, "cancel"), callback_data="cancel")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(self.t(query.from_user.id, "select_node_to_remove"), reply_markup=reply_markup)
            return WAITING_FOR_NODE_NAME
    
    async def remove_node_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Confirm and remove node"""
        query = update.callback_query
        await query.answer()
        
        node_id = query.data.replace("rm_node_", "")
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.delete(f"http://localhost:8000/api/nodes/{node_id}")
                if response.status_code == 200:
                    await query.edit_message_text(self.t(query.from_user.id, "node_removed"))
                else:
                    await query.edit_message_text(self.t(query.from_user.id, "error", error=response.text))
        except Exception as e:
            logger.error(f"Error removing node: {e}", exc_info=True)
            await query.edit_message_text(self.t(query.from_user.id, "error", error=str(e)))
        
        return ConversationHandler.END
    
    # Tunnel management
    async def create_tunnel_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start creating a tunnel"""
        query = update.callback_query
        await query.answer()
        
        if not self.is_admin(query.from_user.id):
            await query.edit_message_text(self.t(query.from_user.id, "access_denied"))
            return ConversationHandler.END
        
        self.user_states[query.from_user.id] = {"step": "name"}
        
        cancel_btn = InlineKeyboardButton(self.t(query.from_user.id, "cancel"), callback_data="cancel")
        reply_markup = InlineKeyboardMarkup([[cancel_btn]])
        await query.edit_message_text(self.t(query.from_user.id, "enter_tunnel_name"), reply_markup=reply_markup)
        return WAITING_FOR_TUNNEL_NAME
    
    async def create_tunnel_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle tunnel name input"""
        user_id = update.message.from_user.id
        if user_id not in self.user_states:
            return ConversationHandler.END
        
        self.user_states[user_id]["name"] = update.message.text
        self.user_states[user_id]["step"] = "core"
        
        keyboard = [
            [InlineKeyboardButton("GOST", callback_data="core_gost")],
            [InlineKeyboardButton("Rathole", callback_data="core_rathole")],
            [InlineKeyboardButton("Backhaul", callback_data="core_backhaul")],
            [InlineKeyboardButton("Chisel", callback_data="core_chisel")],
            [InlineKeyboardButton("FRP", callback_data="core_frp")],
            [InlineKeyboardButton(self.t(user_id, "cancel"), callback_data="cancel")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(self.t(user_id, "select_tunnel_core"), reply_markup=reply_markup)
        return WAITING_FOR_TUNNEL_CORE
    
    async def create_tunnel_core(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle tunnel core selection"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        if user_id not in self.user_states:
            return ConversationHandler.END
        
        core = query.data.replace("core_", "")
        self.user_states[user_id]["core"] = core
        self.user_states[user_id]["step"] = "type"
        
        # Determine available types based on core
        types = []
        if core == "gost":
            types = [("TCP", "tcp"), ("UDP", "udp"), ("gRPC", "grpc"), ("TCPMux", "tcpmux")]
        elif core == "rathole":
            types = [("TCP", "tcp"), ("WebSocket", "ws")]
        elif core == "backhaul":
            types = [("TCP", "tcp"), ("UDP", "udp"), ("WebSocket", "ws"), ("WSMux", "wsmux"), ("TCPMux", "tcpmux")]
        elif core == "frp":
            types = [("TCP", "tcp"), ("UDP", "udp")]
        elif core == "chisel":
            types = [("Chisel", "chisel")]
        
        keyboard = []
        for type_name, type_val in types:
            keyboard.append([InlineKeyboardButton(type_name, callback_data=f"type_{type_val}")])
        keyboard.append([InlineKeyboardButton(self.t(user_id, "cancel"), callback_data="cancel")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(self.t(user_id, "select_tunnel_type"), reply_markup=reply_markup)
        return WAITING_FOR_TUNNEL_TYPE
    
    async def create_tunnel_type(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle tunnel type selection"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        if user_id not in self.user_states:
            return ConversationHandler.END
        
        tunnel_type = query.data.replace("type_", "")
        self.user_states[user_id]["type"] = tunnel_type
        self.user_states[user_id]["step"] = "ports"
        
        cancel_btn = InlineKeyboardButton(self.t(user_id, "cancel"), callback_data="cancel")
        reply_markup = InlineKeyboardMarkup([[cancel_btn]])
        await query.edit_message_text(self.t(user_id, "enter_tunnel_ports"), reply_markup=reply_markup)
        return WAITING_FOR_TUNNEL_PORTS
    
    async def create_tunnel_ports(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle tunnel ports input"""
        user_id = update.message.from_user.id
        if user_id not in self.user_states:
            return ConversationHandler.END
        
        ports_str = update.message.text
        ports = [int(p.strip()) for p in ports_str.split(",") if p.strip().isdigit()]
        
        if not ports:
            await update.message.reply_text("Invalid ports. Please enter comma-separated numbers.")
            return WAITING_FOR_TUNNEL_PORTS
        
        self.user_states[user_id]["ports"] = ports
        core = self.user_states[user_id]["core"]
        
        # For cores that need nodes, ask for nodes
        if core in ["rathole", "backhaul", "frp", "chisel"]:
            self.user_states[user_id]["step"] = "iran_node"
            # Get Iran nodes
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(Node))
                nodes = result.scalars().all()
                iran_nodes = [n for n in nodes if n.node_metadata.get("role") == "iran"]
                
                if not iran_nodes:
                    await update.message.reply_text("No Iran nodes found. Please add an Iran node first.")
                    del self.user_states[user_id]
                    return ConversationHandler.END
                
                keyboard = []
                for node in iran_nodes:
                    keyboard.append([InlineKeyboardButton(
                        f"🇮🇷 {node.name}",
                        callback_data=f"iran_node_{node.id}"
                    )])
                keyboard.append([InlineKeyboardButton(self.t(user_id, "cancel"), callback_data="cancel")])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(self.t(user_id, "select_iran_node"), reply_markup=reply_markup)
                return WAITING_FOR_TUNNEL_IRAN_NODE
        else:
            # For GOST, ask for remote IP
            self.user_states[user_id]["step"] = "remote_ip"
            cancel_btn = InlineKeyboardButton(self.t(user_id, "cancel"), callback_data="cancel")
            reply_markup = InlineKeyboardMarkup([[cancel_btn]])
            await update.message.reply_text(self.t(user_id, "enter_remote_ip"), reply_markup=reply_markup)
            return WAITING_FOR_TUNNEL_REMOTE_IP
    
    async def create_tunnel_iran_node(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle Iran node selection"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        if user_id not in self.user_states:
            return ConversationHandler.END
        
        iran_node_id = query.data.replace("iran_node_", "")
        self.user_states[user_id]["iran_node_id"] = iran_node_id
        self.user_states[user_id]["step"] = "foreign_node"
        
        # Get foreign nodes
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Node))
            nodes = result.scalars().all()
            foreign_nodes = [n for n in nodes if n.node_metadata.get("role") == "foreign"]
            
            if not foreign_nodes:
                await query.edit_message_text("No foreign nodes found. Please add a foreign node first.")
                del self.user_states[user_id]
                return ConversationHandler.END
            
            keyboard = []
            for node in foreign_nodes:
                keyboard.append([InlineKeyboardButton(
                    f"🌍 {node.name}",
                    callback_data=f"foreign_node_{node.id}"
                )])
            keyboard.append([InlineKeyboardButton(self.t(user_id, "cancel"), callback_data="cancel")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(self.t(user_id, "select_foreign_node"), reply_markup=reply_markup)
            return WAITING_FOR_TUNNEL_FOREIGN_NODE
    
    async def create_tunnel_foreign_node(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle foreign node selection and create tunnel"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        if user_id not in self.user_states:
            return ConversationHandler.END
        
        foreign_node_id = query.data.replace("foreign_node_", "")
        state = self.user_states[user_id]
        
        # Build spec based on core
        spec = {"ports": state["ports"]}
        
        if state["core"] == "gost":
            spec["remote_ip"] = state.get("remote_ip", "127.0.0.1")
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8000/api/tunnels",
                    json={
                        "name": state["name"],
                        "core": state["core"],
                        "type": state["type"],
                        "iran_node_id": state.get("iran_node_id"),
                        "foreign_node_id": foreign_node_id,
                        "spec": spec
                    }
                )
                if response.status_code == 200:
                    await query.edit_message_text(self.t(user_id, "tunnel_created"))
                else:
                    await query.edit_message_text(self.t(user_id, "error", error=response.text))
        except Exception as e:
            logger.error(f"Error creating tunnel: {e}", exc_info=True)
            await query.edit_message_text(self.t(user_id, "error", error=str(e)))
        
        del self.user_states[user_id]
        return ConversationHandler.END
    
    async def create_tunnel_remote_ip(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle remote IP input and create GOST tunnel"""
        user_id = update.message.from_user.id
        if user_id not in self.user_states:
            return ConversationHandler.END
        
        remote_ip = update.message.text.strip() or "127.0.0.1"
        state = self.user_states[user_id]
        
        spec = {
            "ports": state["ports"],
            "remote_ip": remote_ip
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8000/api/tunnels",
                    json={
                        "name": state["name"],
                        "core": state["core"],
                        "type": state["type"],
                        "spec": spec
                    }
                )
                if response.status_code == 200:
                    await update.message.reply_text(self.t(user_id, "tunnel_created"))
                else:
                    await update.message.reply_text(self.t(user_id, "error", error=response.text))
        except Exception as e:
            logger.error(f"Error creating tunnel: {e}", exc_info=True)
            await update.message.reply_text(self.t(user_id, "error", error=str(e)))
        
        del self.user_states[user_id]
        return ConversationHandler.END
    
    async def remove_tunnel_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start removing a tunnel"""
        query = update.callback_query
        await query.answer()
        
        if not self.is_admin(query.from_user.id):
            await query.edit_message_text(self.t(query.from_user.id, "access_denied"))
            return ConversationHandler.END
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Tunnel))
            tunnels = result.scalars().all()
            
            if not tunnels:
                await query.edit_message_text(self.t(query.from_user.id, "no_tunnels"))
                return ConversationHandler.END
            
            keyboard = []
            for tunnel in tunnels:
                keyboard.append([InlineKeyboardButton(
                    f"🗑️ {tunnel.name} ({tunnel.core})",
                    callback_data=f"rm_tunnel_{tunnel.id}"
                )])
            keyboard.append([InlineKeyboardButton(self.t(query.from_user.id, "cancel"), callback_data="cancel")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(self.t(query.from_user.id, "select_tunnel_to_remove"), reply_markup=reply_markup)
            return WAITING_FOR_TUNNEL_NAME
    
    async def remove_tunnel_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Confirm and remove tunnel"""
        query = update.callback_query
        await query.answer()
        
        tunnel_id = query.data.replace("rm_tunnel_", "")
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.delete(f"http://localhost:8000/api/tunnels/{tunnel_id}")
                if response.status_code == 200:
                    await query.edit_message_text(self.t(query.from_user.id, "tunnel_removed"))
                else:
                    await query.edit_message_text(self.t(query.from_user.id, "error", error=response.text))
        except Exception as e:
            logger.error(f"Error removing tunnel: {e}", exc_info=True)
            await query.edit_message_text(self.t(query.from_user.id, "error", error=str(e)))
        
        return ConversationHandler.END
    
    async def cancel_operation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel current operation"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        if user_id in self.user_states:
            del self.user_states[user_id]
        
        await query.edit_message_text(self.t(user_id, "cancel"))
        await self.show_main_menu(query.message)
        return ConversationHandler.END
    
    # Stats and info
    async def cmd_nodes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /nodes command"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text(self.t(update.effective_user.id, "access_denied"))
            return
        
        await self.cmd_nodes_callback(update.message)
    
    async def cmd_tunnels(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /tunnels command"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text(self.t(update.effective_user.id, "access_denied"))
            return
        
        await self.cmd_tunnels_callback(update.message)
    
    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text(self.t(update.effective_user.id, "access_denied"))
            return
        
        await self.cmd_status_callback(update.message)
    
    async def cmd_backup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /backup command"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text(self.t(update.effective_user.id, "access_denied"))
            return
        
        await update.message.reply_text("📦 Creating backup...")
        
        try:
            backup_path = await self.create_backup()
            if backup_path:
                with open(backup_path, 'rb') as f:
                    await update.message.reply_document(
                        document=f,
                        filename=f"smite_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                        caption="✅ Backup created successfully"
                    )
                os.remove(backup_path)
            else:
                await update.message.reply_text("❌ Failed to create backup")
        except Exception as e:
            logger.error(f"Error creating backup: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error creating backup: {str(e)}")
    
    async def cmd_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /logs command"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text(self.t(update.effective_user.id, "access_denied"))
            return
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get("http://localhost:8000/api/logs?limit=20")
                if response.status_code == 200:
                    logs = response.json().get("logs", [])
                    if logs:
                        text = "📋 Recent Logs:\n\n"
                        for log in logs[-10:]:
                            text += f"`{log.get('level', 'INFO')}` {log.get('message', '')[:100]}\n\n"
                        await update.message.reply_text(text, parse_mode="Markdown")
                    else:
                        await update.message.reply_text("No logs available.")
                else:
                    await update.message.reply_text("Failed to fetch logs.")
        except Exception as e:
            logger.error(f"Error fetching logs: {e}", exc_info=True)
            await update.message.reply_text(f"Error: {str(e)}")
    
    async def create_backup(self) -> Optional[str]:
        """Create backup archive"""
        try:
            from app.config import settings
            import os
            
            backup_dir = Path("/tmp/smite_backup")
            backup_dir.mkdir(exist_ok=True)
            
            db_path = Path("./data/smite.db")
            if db_path.exists():
                shutil.copy2(db_path, backup_dir / "smite.db")
            
            env_path = Path(".env")
            if env_path.exists():
                shutil.copy2(env_path, backup_dir / ".env")
            
            docker_compose = Path("docker-compose.yml")
            if docker_compose.exists():
                shutil.copy2(docker_compose, backup_dir / "docker-compose.yml")
            
            certs_dir = Path("./certs")
            if certs_dir.exists():
                shutil.copytree(certs_dir, backup_dir / "certs", dirs_exist_ok=True)
            
            node_cert_path = Path(settings.node_cert_path)
            if not node_cert_path.is_absolute():
                node_cert_path = Path(os.getcwd()) / node_cert_path
            if node_cert_path.exists():
                (backup_dir / "node_certs").mkdir(exist_ok=True)
                shutil.copy2(node_cert_path, backup_dir / "node_certs" / "ca.crt")
            
            node_key_path = Path(settings.node_key_path)
            if not node_key_path.is_absolute():
                node_key_path = Path(os.getcwd()) / node_key_path
            if node_key_path.exists():
                (backup_dir / "node_certs").mkdir(exist_ok=True)
                shutil.copy2(node_key_path, backup_dir / "node_certs" / "ca.key")
            
            server_cert_path = Path(settings.node_server_cert_path)
            if not server_cert_path.is_absolute():
                server_cert_path = Path(os.getcwd()) / server_cert_path
            if server_cert_path.exists():
                (backup_dir / "server_certs").mkdir(exist_ok=True)
                shutil.copy2(server_cert_path, backup_dir / "server_certs" / "ca-server.crt")
            
            server_key_path = Path(settings.node_server_key_path)
            if not server_key_path.is_absolute():
                server_key_path = Path(os.getcwd()) / server_key_path
            if server_key_path.exists():
                (backup_dir / "server_certs").mkdir(exist_ok=True)
                shutil.copy2(server_key_path, backup_dir / "server_certs" / "ca-server.key")
            
            data_dir = Path("./data")
            if data_dir.exists():
                (backup_dir / "data").mkdir(exist_ok=True)
                for item in data_dir.iterdir():
                    if item.is_file() and item.suffix in ['.json', '.yaml', '.toml']:
                        shutil.copy2(item, backup_dir / "data" / item.name)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = f"/tmp/smite_backup_{timestamp}.zip"
            
            with zipfile.ZipFile(backup_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(backup_dir):
                    for file in files:
                        file_path = Path(root) / file
                        arcname = file_path.relative_to(backup_dir)
                        zipf.write(file_path, arcname)
            
            shutil.rmtree(backup_dir)
            
            return backup_file
        except Exception as e:
            logger.error(f"Error creating backup: {e}", exc_info=True)
            return None
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback queries"""
        query = update.callback_query
        await query.answer()
        
        if not self.is_admin(query.from_user.id):
            await query.edit_message_text(self.t(query.from_user.id, "access_denied"))
            return
        
        data = query.data
        
        if data == "select_language":
            keyboard = [
                [InlineKeyboardButton(self.t(query.from_user.id, "english"), callback_data="lang_en")],
                [InlineKeyboardButton(self.t(query.from_user.id, "farsi"), callback_data="lang_fa")],
                [InlineKeyboardButton(self.t(query.from_user.id, "back"), callback_data="back_to_menu")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("🌐 Select Language:", reply_markup=reply_markup)
        elif data.startswith("lang_"):
            lang = data.replace("lang_", "")
            self.user_languages[query.from_user.id] = lang
            lang_name = "English" if lang == "en" else "Farsi"
            await query.edit_message_text(self.t(query.from_user.id, "language_set", lang=lang_name))
            await asyncio.sleep(1)
            await self.show_main_menu(query.message)
        elif data == "back_to_menu":
            await self.show_main_menu(query.message)
        elif data == "node_stats":
            await self.cmd_nodes_callback(query.message)
        elif data == "tunnel_stats":
            await self.cmd_tunnels_callback(query.message)
        elif data == "logs":
            await self.cmd_logs_callback(query)
        elif data == "cmd_nodes":
            await self.cmd_nodes_callback(query.message)
        elif data == "cmd_tunnels":
            await self.cmd_tunnels_callback(query.message)
        elif data == "cmd_backup":
            await self.cmd_backup_callback(query)
        elif data == "cmd_status":
            await self.cmd_status_callback(query.message)
    
    async def cmd_nodes_callback(self, message):
        """Handle nodes command from callback"""
        user_id = message.from_user.id if hasattr(message, 'from_user') else message.chat.id
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Node))
            nodes = result.scalars().all()
            
            if not nodes:
                text = self.t(user_id, "no_nodes")
                if hasattr(message, 'edit_message_text'):
                    await message.edit_message_text(text)
                else:
                    await message.reply_text(text)
                return
            
            text = "🖥️ Nodes:\n\n"
            for node in nodes:
                status = "🟢" if node.status == "active" else "🔴"
                role = node.node_metadata.get("role", "unknown") if node.node_metadata else "unknown"
                text += f"{status} {node.name} ({role})\n"
                text += f"   ID: {node.id[:8]}...\n\n"
            
            keyboard = []
            for node in nodes:
                keyboard.append([
                    InlineKeyboardButton(
                        f"📊 {node.name}",
                        callback_data=f"node_info_{node.id}"
                    )
                ])
            keyboard.append([InlineKeyboardButton(self.t(user_id, "back"), callback_data="back_to_menu")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            if hasattr(message, 'edit_message_text'):
                await message.edit_message_text(text, reply_markup=reply_markup)
            else:
                await message.reply_text(text, reply_markup=reply_markup)
    
    async def cmd_tunnels_callback(self, message):
        """Handle tunnels command from callback"""
        user_id = message.from_user.id if hasattr(message, 'from_user') else message.chat.id
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Tunnel))
            tunnels = result.scalars().all()
            
            if not tunnels:
                text = self.t(user_id, "no_tunnels")
                if hasattr(message, 'edit_message_text'):
                    await message.edit_message_text(text)
                else:
                    await message.reply_text(text)
                return
            
            text = f"🔗 Tunnels ({len(tunnels)}):\n\n"
            for tunnel in tunnels[:10]:
                status = "🟢" if tunnel.status == "active" else "🔴"
                text += f"{status} {tunnel.name} ({tunnel.core})\n"
            
            if len(tunnels) > 10:
                text += f"\n... and {len(tunnels) - 10} more"
            
            keyboard = []
            for tunnel in tunnels[:5]:
                keyboard.append([
                    InlineKeyboardButton(
                        f"🔗 {tunnel.name}",
                        callback_data=f"tunnel_info_{tunnel.id}"
                    )
                ])
            keyboard.append([InlineKeyboardButton(self.t(user_id, "back"), callback_data="back_to_menu")])
            
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            if hasattr(message, 'edit_message_text'):
                await message.edit_message_text(text, reply_markup=reply_markup)
            else:
                await message.reply_text(text, reply_markup=reply_markup)
    
    async def cmd_status_callback(self, message):
        """Handle status command from callback"""
        user_id = message.from_user.id if hasattr(message, 'from_user') else message.chat.id
        async with AsyncSessionLocal() as session:
            nodes_result = await session.execute(select(Node))
            nodes = nodes_result.scalars().all()
            
            tunnels_result = await session.execute(select(Tunnel))
            tunnels = tunnels_result.scalars().all()
            
            active_nodes = sum(1 for n in nodes if n.status == "active")
            active_tunnels = sum(1 for t in tunnels if t.status == "active")
            
            text = f"""📊 Panel Status:

🖥️ Nodes: {active_nodes}/{len(nodes)} active
🔗 Tunnels: {active_tunnels}/{len(tunnels)} active
"""
            
            keyboard = [
                [
                    InlineKeyboardButton("🖥️ View Nodes", callback_data="cmd_nodes"),
                    InlineKeyboardButton("🔗 View Tunnels", callback_data="cmd_tunnels")
                ],
                [
                    InlineKeyboardButton("📦 Create Backup", callback_data="cmd_backup"),
                    InlineKeyboardButton("🔄 Refresh", callback_data="cmd_status")
                ],
                [
                    InlineKeyboardButton(self.t(user_id, "back"), callback_data="back_to_menu")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            if hasattr(message, 'edit_message_text'):
                await message.edit_message_text(text, reply_markup=reply_markup)
            else:
                await message.reply_text(text, reply_markup=reply_markup)
    
    async def cmd_backup_callback(self, query):
        """Handle backup command from callback"""
        await query.edit_message_text("📦 Creating backup...")
        
        try:
            backup_path = await self.create_backup()
            if backup_path:
                with open(backup_path, 'rb') as f:
                    await query.message.reply_document(
                        document=f,
                        filename=f"smite_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                        caption="✅ Backup created successfully"
                    )
                os.remove(backup_path)
                await query.edit_message_text("✅ Backup created and sent successfully!")
            else:
                await query.edit_message_text("❌ Failed to create backup")
        except Exception as e:
            logger.error(f"Error creating backup: {e}", exc_info=True)
            await query.edit_message_text(f"❌ Error creating backup: {str(e)}")
    
    async def cmd_logs_callback(self, query):
        """Handle logs command from callback"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get("http://localhost:8000/api/logs?limit=20")
                if response.status_code == 200:
                    logs = response.json().get("logs", [])
                    if logs:
                        text = "📋 Recent Logs:\n\n"
                        for log in logs[-10:]:
                            text += f"`{log.get('level', 'INFO')}` {log.get('message', '')[:100]}\n\n"
                        await query.edit_message_text(text, parse_mode="Markdown")
                    else:
                        await query.edit_message_text("No logs available.")
                else:
                    await query.edit_message_text("Failed to fetch logs.")
        except Exception as e:
            logger.error(f"Error fetching logs: {e}", exc_info=True)
            await query.edit_message_text(f"Error: {str(e)}")


telegram_bot = TelegramBot()
