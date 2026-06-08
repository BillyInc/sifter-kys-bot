"""
Auth API Routes
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request, jsonify
from services.referral_points_manager import get_referral_manager
from services.supabase_client import get_supabase_client, SCHEMA_NAME
from services.email_service import get_email_service

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

# ── Password Reset ────────────────────────────────────────────────────────────

RESET_TOKEN_TTL_HOURS = 1


@auth_bp.route('/forgot-password', methods=['POST'])
def handle_forgot_password():
    """Send a password-reset email with a one-time token."""
    try:
        data = request.json or {}
        email = (data.get('email') or '').strip().lower()
        chat_id = data.get('chat_id')  # optional — set when coming from Telegram

        if not email:
            return jsonify({'error': 'Email is required'}), 400

        supabase = get_supabase_client()
        # Look up the user by email in auth.users
        try:
            user_resp = supabase.auth.admin.list_users()
            users = user_resp if isinstance(user_resp, list) else user_resp.users
            matching = [u for u in users if getattr(u, 'email', '').lower() == email]
            if not matching:
                # Don't leak whether the email exists — return success anyway
                logger.info("[AUTH] forgot-password requested for unknown email: %s", email)
                return jsonify({'success': True, 'message': 'If that email is registered, a reset link has been sent.'}), 200
            user = matching[0]
        except Exception:
            logger.warning("[AUTH] forgot-password: could not list users via admin API")
            return jsonify({'success': True, 'message': 'If that email is registered, a reset link has been sent.'}), 200

        user_id = user.id
        token = secrets.token_urlsafe(48)
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=RESET_TOKEN_TTL_HOURS)).isoformat()

        # Store the reset token in telegram_users (reuse the table as a token store
        # for dashboard users too — the chat_id check in the reset handler
        # discriminates between bot and dashboard flows)
        try:
            existing = (
                supabase.schema(SCHEMA_NAME).table("telegram_users")
                .select("id")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if existing.data:
                supabase.schema(SCHEMA_NAME).table("telegram_users").update({
                    "reset_token": token,
                    "reset_token_expires_at": expires_at,
                }).eq("user_id", user_id).execute()
            else:
                # Bot user may not have a telegram_users row yet
                pass
        except Exception as exc:
            logger.warning("[AUTH] Could not store reset token for %s: %s", user_id, exc)

        # Always send the email
        email_service = get_email_service()
        from config import Config
        dashboard_url = Config.DASHBOARD_URL or "https://sifter.app"
        reset_url = f"{dashboard_url.rstrip('/')}/reset-password?token={token}"
        email_service.send_password_reset(email, reset_url, source="dashboard" if not chat_id else "telegram")

        logger.info("[AUTH] Password reset email sent to %s", email)
        return jsonify({'success': True, 'message': 'If that email is registered, a reset link has been sent.'}), 200

    except Exception as e:
        logger.exception("[AUTH] forgot-password error: %s", e)
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/reset-password', methods=['POST'])
def handle_reset_password():
    """Reset password using a one-time token."""
    try:
        data = request.json or {}
        token = (data.get('token') or '').strip()
        new_password = (data.get('password') or '').strip()

        if not token or not new_password:
            return jsonify({'error': 'Token and new password are required'}), 400
        if len(new_password) < 8:
            return jsonify({'error': 'Password must be at least 8 characters'}), 400

        supabase = get_supabase_client()

        # Validate token against telegram_users table
        res = (
            supabase.schema(SCHEMA_NAME).table("telegram_users")
            .select("user_id, reset_token_expires_at")
            .eq("reset_token", token)
            .limit(1)
            .execute()
        )
        if not res.data:
            return jsonify({'error': 'Invalid or expired reset token'}), 400

        row = res.data[0]
        user_id = row["user_id"]
        expires_at = row.get("reset_token_expires_at")

        if expires_at:
            try:
                exp = datetime.fromisoformat(expires_at)
                if datetime.now(timezone.utc) > exp:
                    return jsonify({'error': 'Reset token has expired. Please request a new one.'}), 400
            except ValueError:
                pass

        # Update the password via Supabase Admin API
        try:
            supabase.auth.admin.update_user_by_id(user_id, {"password": new_password})
        except Exception as exc:
            logger.exception("[AUTH] Password update failed for %s: %s", user_id, exc)
            return jsonify({'error': 'Could not update password. Please try again.'}), 500

        # Clear the reset token
        try:
            supabase.schema(SCHEMA_NAME).table("telegram_users").update({
                "reset_token": None,
                "reset_token_expires_at": None,
            }).eq("user_id", user_id).execute()
        except Exception:
            pass  # non-fatal

        logger.info("[AUTH] Password reset successful for user_id=%s", user_id)
        return jsonify({'success': True, 'message': 'Password has been reset. You can now log in.'}), 200

    except Exception as e:
        logger.exception("[AUTH] reset-password error: %s", e)
        return jsonify({'error': 'Internal server error'}), 500


# ── Magic Link Validation ─────────────────────────────────────────────────────

@auth_bp.route('/magic/<token>', methods=['GET'])
def handle_magic_link(token):
    """Validate a magic-link token and redirect to the Telegram deep link."""
    from flask import redirect

    try:
        supabase = get_supabase_client()
        res = (
            supabase.schema(SCHEMA_NAME).table("magic_links")
            .select("id, token, access_tier, expires_at, used")
            .eq("token", token)
            .limit(1)
            .execute()
        )
        if not res.data:
            return "<h1>Invalid Link</h1><p>This magic link is not valid.</p>", 404

        row = res.data[0]
        if row.get("used"):
            return "<h1>Link Already Used</h1><p>This magic link has already been redeemed.</p>", 410
        if row.get("expires_at"):
            try:
                exp = datetime.fromisoformat(row["expires_at"])
                if datetime.now(timezone.utc) > exp:
                    return "<h1>Link Expired</h1><p>This magic link has expired.</p>", 410
            except ValueError:
                pass

        # Redirect to Telegram deep link — the bot handles MAGIC- prefix
        telegram_bot_username = "SifterTradingBot"  # update if different
        redirect_url = f"https://t.me/{telegram_bot_username}?start=MAGIC-{token}"
        return redirect(redirect_url, code=302)

    except Exception as e:
        logger.exception("[AUTH] magic-link validation error: %s", e)
        return "<h1>Something went wrong</h1><p>Please try again later.</p>", 500


# ── Bot Signup ─────────────────────────────────────────────────────────────────

@auth_bp.route('/bot-signup', methods=['POST'])
def handle_bot_signup():
    """Create a new user account from Telegram (email + password)."""
    try:
        data = request.json or {}
        email = (data.get('email') or '').strip().lower()
        password = (data.get('password') or '').strip()
        chat_id = str(data.get('chat_id') or '').strip()
        referral_code = (data.get('referral_code') or '').strip()

        if not email or not password or not chat_id:
            return jsonify({'error': 'email, password, and chat_id are required'}), 400
        if len(password) < 8:
            return jsonify({'error': 'Password must be at least 8 characters'}), 400

        supabase = get_supabase_client()

        # Create the user in Supabase Auth (service role — email auto-confirmed)
        try:
            auth_response = supabase.auth.admin.create_user({
                "email": email,
                "password": password,
                "email_confirm": True,
            })
            user_id = auth_response.user.id
        except Exception as exc:
            err_str = str(exc).lower()
            if "already" in err_str or "duplicate" in err_str or "exists" in err_str:
                return jsonify({'error': 'An account with this email already exists.'}), 409
            logger.exception("[AUTH] bot-signup: Supabase auth user creation failed")
            return jsonify({'error': 'Could not create account. Please try again.'}), 500

        # The trigger on auth.users INSERT auto-creates the sifter_dev.users row.
        # Link the Telegram chat_id now.
        try:
            existing = (
                supabase.schema(SCHEMA_NAME).table("telegram_users")
                .select("id")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if not existing.data:
                supabase.schema(SCHEMA_NAME).table("telegram_users").insert({
                    "user_id": user_id,
                    "telegram_chat_id": chat_id,
                }).execute()
            else:
                supabase.schema(SCHEMA_NAME).table("telegram_users").update({
                    "telegram_chat_id": chat_id,
                }).eq("user_id", user_id).execute()
        except Exception as exc:
            logger.exception("[AUTH] bot-signup: telegram_users link failed for %s: %s", user_id, exc)
            # User was created but Telegram link failed — still return success
            # with a warning, as the user can re-link via /start

        # Handle referral code
        if referral_code:
            try:
                manager = get_referral_manager()
                result = manager.create_referral(referral_code, user_id, email)
                if result.get('success'):
                    logger.info("[AUTH] Referral created for %s from code %s", user_id[:8], referral_code)
            except Exception:
                pass  # non-fatal

        # Send welcome email
        try:
            email_service = get_email_service()
            email_service.send_welcome(email)
        except Exception:
            pass  # non-fatal

        logger.info("[AUTH] bot-signup success: chat_id=%s, user_id=%s", chat_id, user_id)
        return jsonify({
            'success': True,
            'user_id': user_id,
            'message': 'Account created! Use /menu to get started.',
        }), 201

    except Exception as e:
        logger.exception("[AUTH] bot-signup error: %s", e)
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/bot-login', methods=['POST'])
def handle_bot_login():
    """Log an existing user in from Telegram (email + password) and link chat."""
    try:
        data = request.json or {}
        email = (data.get('email') or '').strip().lower()
        password = (data.get('password') or '').strip()
        chat_id = str(data.get('chat_id') or '').strip()

        if not email or not password or not chat_id:
            return jsonify({'error': 'email, password, and chat_id are required'}), 400

        # Rate-limit by chat_id — login is brute-force-sensitive.
        try:
            from services.redis_pool import get_redis_client
            r = get_redis_client()
            rl_key = f"sifter:login_attempts:{chat_id}"
            attempts = r.incr(rl_key)
            if attempts == 1:
                r.expire(rl_key, 900)  # 15 minutes
            if attempts > 5:
                return jsonify({'error': 'Too many attempts. Try again in 15 minutes.'}), 429
        except Exception:
            pass  # never let a Redis hiccup block legitimate logins

        supabase = get_supabase_client()

        # Verify credentials. sign_in_with_password raises on bad creds.
        try:
            auth_response = supabase.auth.sign_in_with_password({
                "email": email,
                "password": password,
            })
            user = getattr(auth_response, "user", None)
            user_id = user.id if user else None
        except Exception:
            return jsonify({'error': 'Invalid email or password.'}), 401

        if not user_id:
            return jsonify({'error': 'Invalid email or password.'}), 401

        # Link / refresh the Telegram chat_id (same pattern as bot-signup).
        try:
            existing = (
                supabase.schema(SCHEMA_NAME).table("telegram_users")
                .select("id")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if not existing.data:
                supabase.schema(SCHEMA_NAME).table("telegram_users").insert({
                    "user_id": user_id,
                    "telegram_chat_id": chat_id,
                }).execute()
            else:
                supabase.schema(SCHEMA_NAME).table("telegram_users").update({
                    "telegram_chat_id": chat_id,
                }).eq("user_id", user_id).execute()
        except Exception as exc:
            logger.exception("[AUTH] bot-login: telegram_users link failed for %s: %s", user_id, exc)
            return jsonify({'error': 'Logged in but could not link Telegram. Try /start.'}), 500

        # Clear the rate-limit counter on success.
        try:
            get_redis_client().delete(f"sifter:login_attempts:{chat_id}")
        except Exception:
            pass

        logger.info("[AUTH] bot-login success: chat_id=%s, user_id=%s", chat_id, user_id)
        return jsonify({'success': True, 'user_id': user_id}), 200

    except Exception as e:
        logger.exception("[AUTH] bot-login error: %s", e)
        return jsonify({'error': 'Internal server error'}), 500


# ── Legacy Dashboard Signup ────────────────────────────────────────────────────

@auth_bp.route('/signup', methods=['POST'])
def handle_signup():
    """Handle new user signup with referral code"""
    try:
        data = request.json
        user_id = data.get('user_id')
        email = data.get('email')
        referral_code = data.get('referral_code')

        if not user_id or not email:
            return jsonify({'error': 'user_id and email required'}), 400

        manager = get_referral_manager()

        # Create referral relationship if code exists
        if referral_code:
            result = manager.create_referral(referral_code, user_id, email)

            if result.get('success'):
                print(f"[AUTH] ✅ Referral created for {user_id[:8]}... from code {referral_code}")
            else:
                print(f"[AUTH] ⚠️ Referral creation failed: {result.get('error')}")

        return jsonify({'success': True}), 200

    except Exception as e:
        print(f"[AUTH] Signup error: {e}")
        import traceback
        traceback.print_exc()
        logger.exception("Request failed")
        return jsonify({'error': 'Internal server error'}), 500