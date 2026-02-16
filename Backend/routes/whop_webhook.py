"""
Whop Webhook Handler
Processes payment events from Whop for subscription management and referral tracking
"""
import hmac
import hashlib
from flask import Blueprint, request, jsonify
from datetime import datetime
from services.referral_points_manager import get_referral_manager

whop_bp = Blueprint('whop', __name__, url_prefix='/api/whop')


def verify_whop_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify Whop webhook signature"""
    expected_signature = hmac.new(
        secret.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(expected_signature, signature)


@whop_bp.route('/webhook', methods=['POST'])
def whop_webhook():
    """
    Handle Whop webhook events
    
    Events:
    - payment.succeeded (new subscription or renewal)
    - payment.failed
    - subscription.cancelled
    - subscription.expired
    """
    try:
        # Get raw payload for signature verification
        payload = request.get_data()
        signature = request.headers.get('X-Whop-Signature', '')
        
        # Verify signature (get secret from env)
        import os
        whop_secret = os.environ.get('WHOP_WEBHOOK_SECRET', '')
        
        if whop_secret and not verify_whop_signature(payload, signature, whop_secret):
            print("[WHOP] Invalid signature")
            return jsonify({'error': 'Invalid signature'}), 401
        
        # Parse event
        event = request.json
        event_type = event.get('type')
        data = event.get('data', {})
        
        print(f"\n[WHOP] Received event: {event_type}")
        print(f"[WHOP] Data: {data}")
        
        # Route to appropriate handler
        if event_type == 'payment.succeeded':
            return handle_payment_succeeded(data)
        elif event_type == 'subscription.cancelled':
            return handle_subscription_cancelled(data)
        elif event_type == 'subscription.expired':
            return handle_subscription_expired(data)
        elif event_type == 'payment.failed':
            return handle_payment_failed(data)
        else:
            print(f"[WHOP] Unhandled event type: {event_type}")
            return jsonify({'status': 'ignored'}), 200
        
    except Exception as e:
        print(f"[WHOP] Webhook error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def handle_payment_succeeded(data: dict):
    """Handle successful payment (new subscription or renewal)"""
    try:
        # Extract data
        customer_id = data.get('customer_id')
        subscription_id = data.get('subscription_id')
        amount = float(data.get('amount', 0)) / 100  # Convert cents to dollars
        plan_id = data.get('plan_id')
        metadata = data.get('metadata', {})
        
        user_id = metadata.get('user_id')
        is_first_payment = metadata.get('is_first_payment', False)
        
        if not user_id:
            print(f"[WHOP] No user_id in metadata")
            return jsonify({'error': 'No user_id'}), 400
        
        # Determine tier from plan_id or amount
        tier = determine_tier_from_plan(plan_id, amount)
        
        # Import supabase
        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        supabase = get_supabase_client()
        
        # Update user subscription
        supabase.schema(SCHEMA_NAME).table('users').update({
            'subscription_tier': tier,
            'whop_customer_id': customer_id,
            'whop_subscription_id': subscription_id,
            'subscription_started_at': datetime.utcnow().isoformat() if is_first_payment else None,
            'subscription_expires_at': None  # Active subscription
        }).eq('user_id', user_id).execute()
        
        # Update user points tier multiplier
        manager = get_referral_manager()
        
        tier_multiplier = {
            'free': 1.0,
            'pro': 2.0,
            'elite': 3.0
        }.get(tier, 1.0)
        
        supabase.schema(SCHEMA_NAME).table('user_points').update({
            'current_tier': tier,
            'tier_multiplier': tier_multiplier
        }).eq('user_id', user_id).execute()
        
        print(f"[WHOP] ✅ User {user_id[:8]}... subscription updated to {tier}")
        
        # Handle referral commissions
        if is_first_payment:
            # First month - 30% commission
            result = manager.handle_subscription_conversion(
                user_id=user_id,
                tier=tier,
                subscription_amount=amount,
                whop_subscription_id=subscription_id,
                whop_customer_id=customer_id
            )
            
            if result.get('success'):
                print(f"[WHOP] 💰 First month commission processed: ${result['commission']:.2f}")
        else:
            # Recurring payment - 5% commission
            billing_period_start = data.get('billing_period_start', datetime.utcnow().isoformat())
            
            result = manager.handle_recurring_payment(
                whop_subscription_id=subscription_id,
                subscription_amount=amount,
                billing_period_start=billing_period_start
            )
            
            if result.get('success'):
                print(f"[WHOP] 💵 Recurring commission processed: ${result['commission']:.2f}")
        
        return jsonify({'status': 'success'}), 200
        
    except Exception as e:
        print(f"[WHOP] Error handling payment: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def handle_subscription_cancelled(data: dict):
    """Handle subscription cancellation"""
    try:
        subscription_id = data.get('subscription_id')
        customer_id = data.get('customer_id')
        
        # Find user
        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        supabase = get_supabase_client()
        
        user_result = supabase.schema(SCHEMA_NAME).table('users').select(
            'user_id'
        ).eq('whop_subscription_id', subscription_id).limit(1).execute()
        
        if not user_result.data:
            print(f"[WHOP] User not found for subscription {subscription_id}")
            return jsonify({'error': 'User not found'}), 404
        
        user_id = user_result.data[0]['user_id']
        
        # Downgrade to free
        supabase.schema(SCHEMA_NAME).table('users').update({
            'subscription_tier': 'free',
            'subscription_expires_at': datetime.utcnow().isoformat()
        }).eq('user_id', user_id).execute()
        
        # Update points tier
        supabase.schema(SCHEMA_NAME).table('user_points').update({
            'current_tier': 'free',
            'tier_multiplier': 1.0
        }).eq('user_id', user_id).execute()
        
        # Mark referral as cancelled
        supabase.schema(SCHEMA_NAME).table('referrals').update({
            'status': 'cancelled',
            'cancelled_at': datetime.utcnow().isoformat()
        }).eq('whop_subscription_id', subscription_id).execute()
        
        print(f"[WHOP] ❌ Subscription cancelled for {user_id[:8]}...")
        
        return jsonify({'status': 'success'}), 200
        
    except Exception as e:
        print(f"[WHOP] Error handling cancellation: {e}")
        return jsonify({'error': str(e)}), 500


def handle_subscription_expired(data: dict):
    """Handle subscription expiration"""
    # Similar to cancellation
    return handle_subscription_cancelled(data)


def handle_payment_failed(data: dict):
    """Handle failed payment"""
    try:
        subscription_id = data.get('subscription_id')
        
        print(f"[WHOP] ⚠️ Payment failed for subscription {subscription_id}")
        
        # Optionally: Send notification to user
        # Optionally: Grace period before downgrading
        
        return jsonify({'status': 'acknowledged'}), 200
        
    except Exception as e:
        print(f"[WHOP] Error handling failed payment: {e}")
        return jsonify({'error': str(e)}), 500


def determine_tier_from_plan(plan_id: str, amount: float) -> str:
    """Determine tier from Whop plan ID or amount"""
    # Map your Whop plan IDs to tiers
    plan_mapping = {
        'plan_pro_monthly': 'pro',
        'plan_pro_yearly': 'pro',
        'plan_elite_monthly': 'elite',
        'plan_elite_yearly': 'elite'
    }
    
    if plan_id in plan_mapping:
        return plan_mapping[plan_id]
    
    # Fallback: Determine by amount
    if amount >= 199:
        return 'elite'
    elif amount >= 79:
        return 'pro'
    else:
        return 'free'