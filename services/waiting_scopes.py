"""Shared keys used to detect active owner/admin input flows.

This module intentionally contains no handler imports so callbacks.py and
messages.py can use the same scope registry without creating a circular import.
"""

WAITING_SCOPE_KEYS = frozenset({
    'shield_add_pending',
    'shield_edit_pending',
    'shield_auto_setting_pending',
    'social_pending',
    'missile_operational_pending',
    'balance_pending',
    'population_pending',
    'population_selected_user',
    'user_game_population_pending',
    'user_game_population_confirm',
    'exchange_text_pending',
    'user_admin_origin',
    'self_country_edit',
    'arsenal_sell_custom_pending',
    'admin_message_pending',
    'balance_selected_country',
    'user_detail_back',
    'store_nav',
    'self_country_edit_name',
    'missile_pending',
    'admin_leadership_bulk_pending',
    'exchange_rate_pending',
    'arsenal_sell_pending',
    'leadership_operation',
    'country_edit_waiting',
    'global_loot_percent_pending',
    'missile_draft',
    'balance_selected_user',
    'economy_pending',
    'security_pending',
    'country_edit',
    'owner_economy_confirm',
    'admin_pending',
    'enigma_pending',
    'social_delete_pending',
    'leadership_back_callback',
    'swap_pending',
    'admin_leadership_pending',
    'shield_adjust_pending',
    'shield_reset_pending',
    'country_edit_name',
    'pending_exchange',
    'admin_panel',
    'bank_pending',
    'golden_pending',
    'golden_stage_scope',
})

# Backwards-compatible private alias for modules that prefer the old naming.
_WAITING_SCOPE_KEYS = WAITING_SCOPE_KEYS
