"""
Referral & Points Manager
Handles referral tracking, commission calculations, and gamification points
"""
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from services.supabase_client import get_supabase_client, SCHEMA_NAME
import secrets
import string


class ReferralPointsManager:
    """Manages referrals and points system"""
    
    def __init__(self):
        self.supabase = get_supabase_client()
        self.schema = SCHEMA_NAME
        
        # Point award configurations
        self.point_awards = {
            'daily_login': {'base': 10, 'cap': 10},
            'run_analysis': {'base': 5, 'cap': 50},  # Max 10 runs
            'add_wallet': {'base': 20, 'cap': 100},  # Max 5 adds
            'share_referral': {'base': 50, 'cap': 50},
            'referral_signup': {'base': 500, 'cap': None},  # Unlimited
            'referral_conversion': {'base': 2000, 'cap': None},  # Unlimited
            'leaderboard_contribution': {'base': 100, 'cap': 100},
            'weekly_streak': {'base': 200, 'cap': 200},
            'monthly_streak': {'base': 1000, 'cap': 1000}
        }
        
        # Tier multipliers
        self.tier_multipliers = {
            'free': 1.0,
            'pro': 2.0,
            'elite': 3.0
        }
        
        # Commission rates
        self.first_month_rate = 0.30  # 30%
        self.recurring_rate = 0.05    # 5%
        self.recurring_duration_months = 60  # 5 years
    
    def _table(self, name: str):
        """Get table reference with schema"""
        return self.supabase.schema(self.schema).table(name)
    
    # =========================================================================
    # REFERRAL CODE MANAGEMENT
    # =========================================================================
    
    def generate_referral_code(self, user_id: str) -> str:
        """Generate unique referral code for user"""
        try:
            # Check if user already has a code
            existing = self._table('referral_codes').select('code').eq(
                'user_id', user_id
            ).eq('active', True).limit(1).execute()
            
            if existing.data:
                return existing.data[0]['code']
            
            # Generate new code: USER_ID[:3] + 5 random chars
            while True:
                code = (user_id[:3] + ''.join(
                    secrets.choice(string.ascii_uppercase + string.digits) for _ in range(5)
                )).upper()
                
                # Check uniqueness
                check = self._table('referral_codes').select('code').eq(
                    'code', code
                ).limit(1).execute()
                
                if not check.data:
                    break
            
            # Insert code
            self._table('referral_codes').insert({
                'user_id': user_id,
                'code': code,
                'active': True
            }).execute()
            
            print(f"[REFERRAL] Generated code {code} for user {user_id[:8]}...")
            return code
            
        except Exception as e:
            print(f"[REFERRAL] Error generating code: {e}")
            raise
    
    def get_referral_code(self, user_id: str) -> Optional[str]:
        """Get user's referral code"""
        try:
            result = self._table('referral_codes').select('code').eq(
                'user_id', user_id
            ).eq('active', True).limit(1).execute()
            
            if result.data:
                return result.data[0]['code']
            
            # Generate if doesn't exist
            return self.generate_referral_code(user_id)
            
        except Exception as e:
            print(f"[REFERRAL] Error getting code: {e}")
            return None
    
    def track_referral_click(self, code: str):
        """Track click on referral link"""
        try:
            # Increment clicks
            result = self._table('referral_codes').select('clicks').eq(
                'code', code
            ).limit(1).execute()
            
            if result.data:
                current_clicks = result.data[0]['clicks'] or 0
                self._table('referral_codes').update({
                    'clicks': current_clicks + 1
                }).eq('code', code).execute()
                
                print(f"[REFERRAL] Click tracked for code {code}")
            
        except Exception as e:
            print(f"[REFERRAL] Error tracking click: {e}")
    
    # =========================================================================
    # REFERRAL SIGNUP & CONVERSION
    # =========================================================================
    
    def create_referral(self, referral_code: str, referee_user_id: str, 
                       referee_email: str) -> bool:
        """Create referral relationship when someone signs up"""
        try:
            # Get referrer from code
            code_result = self._table('referral_codes').select(
                'user_id'
            ).eq('code', referral_code).eq('active', True).limit(1).execute()
            
            if not code_result.data:
                print(f"[REFERRAL] Invalid code: {referral_code}")
                return False
            
            referrer_user_id = code_result.data[0]['user_id']
            
            # Don't allow self-referral
            if referrer_user_id == referee_user_id:
                print(f"[REFERRAL] Self-referral blocked")
                return False
            
            # Get referrer details
            referrer_result = self._table('users').select(
                'email, subscription_tier'
            ).eq('user_id', referrer_user_id).limit(1).execute()
            
            if not referrer_result.data:
                return False
            
            referrer = referrer_result.data[0]
            
            # Create referral record
            self._table('referrals').insert({
                'referrer_user_id': referrer_user_id,
                'referrer_email': referrer['email'],
                'referrer_tier': referrer['subscription_tier'] or 'free',
                'referee_user_id': referee_user_id,
                'referee_email': referee_email,
                'referee_tier': 'free',
                'referral_code': referral_code,
                'status': 'signed_up',
                'signed_up_at': datetime.utcnow().isoformat()
            }).execute()
            
            # Update code stats
            self._table('referral_codes').update({
                'signups': self.supabase.rpc('increment', {'x': 1})
            }).eq('code', referral_code).execute()
            
            # Award points to referrer
            self.award_points(
                referrer_user_id,
                'referral_signup',
                metadata={'referee_id': referee_user_id}
            )
            
            print(f"[REFERRAL] ✅ Created: {referee_user_id[:8]}... via {referral_code}")
            return True
            
        except Exception as e:
            print(f"[REFERRAL] Error creating referral: {e}")
            return False
    
    def handle_subscription_conversion(self, user_id: str, tier: str, 
                                       subscription_amount: float,
                                       whop_subscription_id: str,
                                       whop_customer_id: str) -> Dict:
        """Handle when a referred user upgrades to paid"""
        try:
            # Check if this user was referred
            referral = self._table('referrals').select('*').eq(
                'referee_user_id', user_id
            ).eq('status', 'signed_up').limit(1).execute()
            
            if not referral.data:
                print(f"[REFERRAL] No referral found for {user_id[:8]}...")
                return {'success': False, 'reason': 'not_referred'}
            
            ref = referral.data[0]
            referrer_user_id = ref['referrer_user_id']
            
            # Calculate first month commission (30%)
            first_month_commission = subscription_amount * self.first_month_rate
            
            # Update referral record
            self._table('referrals').update({
                'status': 'converted',
                'converted_at': datetime.utcnow().isoformat(),
                'referee_tier': tier,
                'first_month_commission': first_month_commission,
                'total_earnings': first_month_commission,
                'whop_subscription_id': whop_subscription_id,
                'whop_customer_id': whop_customer_id
            }).eq('id', ref['id']).execute()
            
            # Create earning record
            self._table('referral_earnings').insert({
                'referral_id': ref['id'],
                'referrer_user_id': referrer_user_id,
                'referee_user_id': user_id,
                'amount': first_month_commission,
                'commission_type': 'first_month_30',
                'commission_rate': 30.00,
                'subscription_amount': subscription_amount,
                'subscription_tier': tier,
                'payment_status': 'pending',
                'whop_transaction_id': whop_subscription_id,
                'billing_period_start': datetime.utcnow().isoformat()
            }).execute()
            
            # Update code stats
            self._table('referral_codes').update({
                'conversions': self.supabase.rpc('increment', {'x': 1})
            }).eq('code', ref['referral_code']).execute()
            
            # Update referrer's total earnings
            self._table('users').update({
                'total_referral_earnings': self.supabase.rpc(
                    'increment_decimal', {'x': first_month_commission}
                )
            }).eq('user_id', referrer_user_id).execute()
            
            # Award conversion points to referrer
            self.award_points(
                referrer_user_id,
                'referral_conversion',
                metadata={
                    'referee_id': user_id,
                    'tier': tier,
                    'amount': subscription_amount
                }
            )
            
            print(f"[REFERRAL] 💰 Conversion: {referrer_user_id[:8]}... earned ${first_month_commission:.2f}")
            
            return {
                'success': True,
                'referrer_user_id': referrer_user_id,
                'commission': first_month_commission,
                'commission_type': 'first_month'
            }
            
        except Exception as e:
            print(f"[REFERRAL] Error handling conversion: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'error': str(e)}
    
    def handle_recurring_payment(self, whop_subscription_id: str,
                                subscription_amount: float,
                                billing_period_start: str) -> Dict:
        """Handle recurring monthly payments (5% commission)"""
        try:
            # Find referral by subscription ID
            referral = self._table('referrals').select('*').eq(
                'whop_subscription_id', whop_subscription_id
            ).eq('status', 'converted').limit(1).execute()
            
            if not referral.data:
                return {'success': False, 'reason': 'no_referral'}
            
            ref = referral.data[0]
            
            # Check if subscription is still within 5-year window
            converted_at = datetime.fromisoformat(ref['converted_at'].replace('Z', '+00:00'))
            months_elapsed = (datetime.utcnow() - converted_at).days / 30
            
            if months_elapsed > self.recurring_duration_months:
                print(f"[REFERRAL] Subscription beyond 5-year window")
                return {'success': False, 'reason': 'expired'}
            
            # Calculate recurring commission (5%)
            recurring_commission = subscription_amount * self.recurring_rate
            
            # Create earning record
            self._table('referral_earnings').insert({
                'referral_id': ref['id'],
                'referrer_user_id': ref['referrer_user_id'],
                'referee_user_id': ref['referee_user_id'],
                'amount': recurring_commission,
                'commission_type': 'recurring_5',
                'commission_rate': 5.00,
                'subscription_amount': subscription_amount,
                'subscription_tier': ref['referee_tier'],
                'payment_status': 'pending',
                'whop_transaction_id': whop_subscription_id,
                'billing_period_start': billing_period_start
            }).execute()
            
            # Update referral totals
            new_total_recurring = (ref['total_recurring_commission'] or 0) + recurring_commission
            new_total_earnings = (ref['total_earnings'] or 0) + recurring_commission
            
            self._table('referrals').update({
                'total_recurring_commission': new_total_recurring,
                'total_earnings': new_total_earnings
            }).eq('id', ref['id']).execute()
            
            # Update referrer's total
            self._table('users').update({
                'total_referral_earnings': self.supabase.rpc(
                    'increment_decimal', {'x': recurring_commission}
                )
            }).eq('user_id', ref['referrer_user_id']).execute()
            
            print(f"[REFERRAL] 💵 Recurring: {ref['referrer_user_id'][:8]}... earned ${recurring_commission:.2f}")
            
            return {
                'success': True,
                'referrer_user_id': ref['referrer_user_id'],
                'commission': recurring_commission,
                'commission_type': 'recurring'
            }
            
        except Exception as e:
            print(f"[REFERRAL] Error handling recurring: {e}")
            return {'success': False, 'error': str(e)}
    
    # =========================================================================
    # POINTS SYSTEM
    # =========================================================================
    
    def initialize_user_points(self, user_id: str, tier: str = 'free'):
        """Initialize points account for new user"""
        try:
            # Check if exists
            existing = self._table('user_points').select('user_id').eq(
                'user_id', user_id
            ).limit(1).execute()
            
            if existing.data:
                return
            
            # Create
            self._table('user_points').insert({
                'user_id': user_id,
                'total_points': 0,
                'lifetime_points': 0,
                'current_tier': tier,
                'tier_multiplier': self.tier_multipliers.get(tier, 1.0),
                'daily_streak': 0,
                'last_activity_date': datetime.utcnow().date().isoformat(),
                'level': 1
            }).execute()
            
            print(f"[POINTS] Initialized for {user_id[:8]}...")
            
        except Exception as e:
            print(f"[POINTS] Error initializing: {e}")
    
    def award_points(self, user_id: str, action_type: str, 
                    metadata: Optional[Dict] = None) -> int:
        """Award points for an action with daily cap"""
        try:
            # Get point config
            config = self.point_awards.get(action_type)
            if not config:
                print(f"[POINTS] Unknown action: {action_type}")
                return 0
            
            base_points = config['base']
            daily_cap = config['cap']
            
            # Initialize if needed
            self.initialize_user_points(user_id)
            
            # Get user's tier multiplier
            user_points = self._table('user_points').select(
                'tier_multiplier'
            ).eq('user_id', user_id).limit(1).execute()
            
            multiplier = user_points.data[0]['tier_multiplier'] if user_points.data else 1.0
            
            # Check daily cap
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            
            daily_total = self._table('point_transactions').select(
                'points_earned'
            ).eq('user_id', user_id).eq('action_type', action_type).gte(
                'created_at', today_start.isoformat()
            ).execute()
            
            current_daily_total = sum(t['points_earned'] for t in daily_total.data) if daily_total.data else 0
            
            # Calculate points with cap
            points_earned = int(base_points * multiplier)
            capped = False
            
            if daily_cap and (current_daily_total >= daily_cap):
                points_earned = 0
                capped = True
            elif daily_cap and (current_daily_total + points_earned > daily_cap):
                points_earned = daily_cap - current_daily_total
                capped = True
            
            # Insert transaction
            self._table('point_transactions').insert({
                'user_id': user_id,
                'action_type': action_type,
                'points_earned': points_earned,
                'multiplier_applied': multiplier,
                'base_points': base_points,
                'capped': capped,
                'metadata': metadata
            }).execute()
            
            # Update user totals
            if points_earned > 0:
                self._table('user_points').update({
                    'total_points': self.supabase.rpc('increment', {'x': points_earned}),
                    'lifetime_points': self.supabase.rpc('increment', {'x': points_earned}),
                    'updated_at': datetime.utcnow().isoformat()
                }).eq('user_id', user_id).execute()
                
                print(f"[POINTS] {user_id[:8]}... +{points_earned} ({action_type})")
            
            return points_earned
            
        except Exception as e:
            print(f"[POINTS] Error awarding points: {e}")
            return 0
    
    def update_streak(self, user_id: str) -> int:
        """Update daily streak and award streak bonuses"""
        try:
            # Get current streak info
            user_points = self._table('user_points').select(
                'daily_streak, last_activity_date'
            ).eq('user_id', user_id).limit(1).execute()
            
            if not user_points.data:
                self.initialize_user_points(user_id)
                return 1
            
            data = user_points.data[0]
            last_date = data['last_activity_date']
            current_streak = data['daily_streak'] or 0
            
            today = datetime.utcnow().date()
            
            if last_date == today.isoformat():
                # Already logged in today
                return current_streak
            
            last_activity = datetime.fromisoformat(last_date).date() if last_date else None
            
            if last_activity and last_activity == today - timedelta(days=1):
                # Consecutive day
                new_streak = current_streak + 1
            else:
                # Streak broken
                new_streak = 1
            
            # Update streak
            self._table('user_points').update({
                'daily_streak': new_streak,
                'last_activity_date': today.isoformat(),
                'longest_streak': self.supabase.rpc('greatest', {
                    'a': data.get('longest_streak', 0),
                    'b': new_streak
                })
            }).eq('user_id', user_id).execute()
            
            # Award streak bonuses
            if new_streak % 7 == 0:  # Weekly streak
                self.award_points(user_id, 'weekly_streak')
            
            if new_streak % 30 == 0:  # Monthly streak
                self.award_points(user_id, 'monthly_streak')
            
            return new_streak
            
        except Exception as e:
            print(f"[POINTS] Error updating streak: {e}")
            return 0
    
    def get_user_points(self, user_id: str) -> Dict:
        """Get user's point balance and stats"""
        try:
            result = self._table('user_points').select('*').eq(
                'user_id', user_id
            ).limit(1).execute()
            
            if result.data:
                return result.data[0]
            
            return {
                'total_points': 0,
                'lifetime_points': 0,
                'daily_streak': 0,
                'level': 1
            }
            
        except Exception as e:
            print(f"[POINTS] Error getting points: {e}")
            return {}
    
    def get_leaderboard(self, limit: int = 100, leaderboard_type: str = 'lifetime') -> List[Dict]:
        """Get points leaderboard"""
        try:
            sort_field = 'lifetime_points' if leaderboard_type == 'lifetime' else 'total_points'
            
            result = self._table('user_points').select(
                'user_id, total_points, lifetime_points, current_tier, daily_streak, level'
            ).order(sort_field, desc=True).limit(limit).execute()
            
            return result.data
            
        except Exception as e:
            print(f"[POINTS] Error getting leaderboard: {e}")
            return []


def get_referral_manager():
    """Singleton getter"""
    global _referral_manager
    if '_referral_manager' not in globals():
        _referral_manager = ReferralPointsManager()
    return _referral_manager