"""Premium helpers (thin layer over users) so features import from one place."""
from database import users

is_premium = users.is_premium
add_premium = users.add_premium
remove_premium = users.remove_premium
premium_left = users.premium_left
use_trial = users.use_trial
