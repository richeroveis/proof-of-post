"""Direct-mode tests for the ProofOfPost RuleRegistry contract.

Direct mode executes only the leader function of run_nondet (validators are
captured, not run), so these tests cover: bond gate, input validation, access
control, entry state machine (PENDING -> COMPLIANT / NON_COMPLIANT /
INCONCLUSIVE / CANCELLED), slashing/refund accounting, the appeal-window
reservation invariant, appeals, views, and the comparative validator logic
(via direct_vm.run_validator).

Native GEN refunds (emit_transfer) are a no-op in direct mode, so we assert the
contract's internal accounting rather than recipient wallet balances. That
boundary is why the reviewer F1 attack (withdraw slashed collateral while still
appealable) is pinned here on the LEDGER fields - reserved/available/withdrawn
- and its payout side is proven live in docs/onchain-activity.md.
"""

import json

import pytest

MIN_BOND = 10 ** 18  # 1 GEN, atto-scale u256
RULES_BLOB = "Must be written in English\nMust be under 100 words"


def _assert_ledger(contract):
    """Financial invariants (docs/remediation-plan.md) after every transition.

    I1 slashed_total >= withdrawn + reserved (no underflow / double spend)
    I2 reserved_slashed == sum of bonds of entries still inside their window
    I3 bonded_pending == sum of bonds of PENDING entries
    I4 available_slashed == slashed_total - withdrawn_slashed - reserved_slashed
    """
    stats = contract.get_stats()
    slashed = int(stats["slashed_total"])
    withdrawn = int(stats["withdrawn_slashed"])
    reserved = int(stats["reserved_slashed"])
    pending = int(stats["bonded_pending"])
    available = int(stats["available_slashed"])
    tick = int(stats["tick"])

    assert slashed >= withdrawn + reserved, "I1 violated"
    assert available == slashed - withdrawn - reserved, "I4 violated"

    entries = contract.list_entries(0, 1000)
    reserved_sum = 0
    pending_sum = 0
    for e in entries:
        bond = int(e["bond"])
        if e["status"] == "PENDING":
            pending_sum += bond
        if e["status"] == "NON_COMPLIANT" and int(e["appeal_deadline"]) > 0:
            # deadline > 0 with tick past it is a legitimate transient:
            # expiry is swept (finalized) only inside the next write.
            reserved_sum += bond
    assert reserved == reserved_sum, "I2 violated"
    assert pending == pending_sum, "I3 violated"


def _hex(addr) -> str:
    """Normalize a fixture address (bytes outside the sandbox) to 0x-hex.

    The harness's create_address() falls back to raw bytes because the GenVM
    `genlayer` module is only importable inside the sandbox, and the contract
    returns addresses as EIP-55 checksummed strings, so compare case-insensitively.
    """
    if isinstance(addr, (bytes, bytearray)):
        return "0x" + bytes(addr).hex()
    return str(addr)


def _deploy(direct_deploy):
    return direct_deploy("contracts/rule_registry.py", MIN_BOND)


def _mock_llm(direct_vm, statuses):
    """Register an LLM mock returning the given per-rule statuses by index."""
    checks = [{"index": i, "status": s} for i, s in enumerate(statuses)]
    direct_vm.mock_llm(
        r"compliance adjudicator",
        json.dumps({"checks": checks, "reason": "fixture"}),
    )


def test_deploy_initial_state(direct_vm, direct_deploy, direct_owner):
    contract = _deploy(direct_deploy)
    stats = contract.get_stats()
    assert int(stats["total"]) == 0
    assert int(stats["verified"]) == 0
    assert int(stats["min_bond"]) == MIN_BOND
    assert int(stats["slashed_total"]) == 0
    assert stats["owner"].lower() == _hex(direct_owner).lower()


def test_submit_below_min_bond_reverts(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND - 1
    with direct_vm.expect_revert("Bond below minimum"):
        contract.submit("t", "hello world", RULES_BLOB)


def test_submit_empty_content_reverts(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    with direct_vm.expect_revert("Empty content"):
        contract.submit("t", "   ", RULES_BLOB)


def test_submit_no_rules_reverts(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    with direct_vm.expect_revert("No rules provided"):
        contract.submit("t", "some content", "   ")


def test_submit_creates_pending_entry(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    entry_id = contract.submit("My Post", "A short english post.", RULES_BLOB)

    entry = contract.get_entry(entry_id)
    assert entry["status"] == "PENDING"
    assert entry["submitter"].lower() == _hex(direct_alice).lower()
    assert int(entry["bond"]) == MIN_BOND
    assert entry["rules"] == ["Must be written in English", "Must be under 100 words"]
    assert contract.get_stats()["total"] == "1"


def test_view_missing_entry_returns_empty(direct_vm, direct_deploy):
    contract = _deploy(direct_deploy)
    assert contract.get_entry(999) == {}


def test_evaluate_compliant_refunds_and_verifies(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    entry_id = contract.submit("t", "A compliant english post.", RULES_BLOB)

    _mock_llm(direct_vm, ["SATISFIED", "SATISFIED"])
    direct_vm.value = 0
    status = contract.evaluate(entry_id)

    assert status == "COMPLIANT"
    assert contract.get_entry(entry_id)["status"] == "COMPLIANT"
    assert contract.get_stats()["verified"] == "1"
    # COMPLIANT: no slash
    assert contract.get_stats()["slashed_total"] == "0"
    _assert_ledger(contract)


def test_evaluate_non_compliant_slashes(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    entry_id = contract.submit("t", "Un contenu francais.", RULES_BLOB)

    _mock_llm(direct_vm, ["VIOLATED", "SATISFIED"])
    direct_vm.value = 0
    status = contract.evaluate(entry_id)

    assert status == "NON_COMPLIANT"
    assert contract.get_stats()["slashed_total"] == str(MIN_BOND)
    assert contract.get_stats()["verified"] == "0"
    # F1: the slashed bond is RESERVED while the verdict is appealable
    assert contract.get_stats()["reserved_slashed"] == str(MIN_BOND)
    assert contract.get_stats()["available_slashed"] == "0"
    entry = contract.get_entry(entry_id)
    assert entry["checks"][0]["status"] == "VIOLATED"
    _assert_ledger(contract)


def test_evaluate_inconclusive_when_unverifiable(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    entry_id = contract.submit("t", "Ambiguous content here.", RULES_BLOB)

    _mock_llm(direct_vm, ["UNVERIFIABLE", "SATISFIED"])
    direct_vm.value = 0
    status = contract.evaluate(entry_id)

    assert status == "INCONCLUSIVE"
    # INCONCLUSIVE refunds (no slash, no verify credit)
    assert contract.get_stats()["slashed_total"] == "0"
    assert contract.get_stats()["verified"] == "0"


def test_malformed_llm_forces_error(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    entry_id = contract.submit("t", "content", RULES_BLOB)

    # Non-list 'checks' -> ERROR_LLM -> leader raises -> evaluate reverts
    direct_vm.mock_llm(r"compliance adjudicator", json.dumps({"checks": "oops"}))
    direct_vm.value = 0
    with direct_vm.expect_revert("LLM_ERROR"):
        contract.evaluate(entry_id)


def test_evaluate_twice_reverts(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    entry_id = contract.submit("t", "content", RULES_BLOB)

    _mock_llm(direct_vm, ["SATISFIED", "SATISFIED"])
    direct_vm.value = 0
    contract.evaluate(entry_id)
    with direct_vm.expect_revert("Entry not pending"):
        contract.evaluate(entry_id)


def test_evaluate_unauthorized_reverts(direct_vm, direct_deploy, direct_alice, direct_charlie):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    entry_id = contract.submit("t", "content", RULES_BLOB)

    _mock_llm(direct_vm, ["SATISFIED", "SATISFIED"])
    direct_vm.value = 0
    with direct_vm.prank(direct_charlie):
        with direct_vm.expect_revert("Not authorized"):
            contract.evaluate(entry_id)


def test_appeal_flips_non_compliant_to_compliant(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    entry_id = contract.submit("t", "content", RULES_BLOB)

    _mock_llm(direct_vm, ["VIOLATED", "SATISFIED"])
    direct_vm.value = 0
    contract.evaluate(entry_id)
    assert contract.get_stats()["slashed_total"] == str(MIN_BOND)

    # Flip verdict on appeal -> refund, un-slash, verify
    direct_vm.clear_mocks()
    _mock_llm(direct_vm, ["SATISFIED", "SATISFIED"])
    status = contract.appeal(entry_id)

    assert status == "COMPLIANT"
    assert contract.get_stats()["slashed_total"] == "0"
    assert contract.get_stats()["reserved_slashed"] == "0"
    assert contract.get_stats()["verified"] == "1"
    assert contract.get_entry(entry_id)["appeal_count"] == "1"
    assert contract.get_entry(entry_id)["appeal_deadline"] == "0"
    _assert_ledger(contract)


def test_appeal_only_by_submitter(direct_vm, direct_deploy, direct_alice, direct_charlie):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    entry_id = contract.submit("t", "content", RULES_BLOB)
    _mock_llm(direct_vm, ["VIOLATED", "SATISFIED"])
    direct_vm.value = 0
    contract.evaluate(entry_id)

    with direct_vm.prank(direct_charlie):
        with direct_vm.expect_revert("Only submitter can appeal"):
            contract.appeal(entry_id)


def test_appeal_requires_non_compliant(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    entry_id = contract.submit("t", "content", RULES_BLOB)
    _mock_llm(direct_vm, ["SATISFIED", "SATISFIED"])
    direct_vm.value = 0
    contract.evaluate(entry_id)  # COMPLIANT -> cannot appeal

    with direct_vm.expect_revert("Only NON_COMPLIANT can be appealed"):
        contract.appeal(entry_id)


def test_appeal_limit(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    entry_id = contract.submit("t", "content", RULES_BLOB)

    # Stay NON_COMPLIANT so appeals keep consuming the budget.
    _mock_llm(direct_vm, ["VIOLATED", "SATISFIED"])
    direct_vm.value = 0
    contract.evaluate(entry_id)
    contract.appeal(entry_id)  # 1
    contract.appeal(entry_id)  # 2
    with direct_vm.expect_revert("Appeal limit reached"):
        contract.appeal(entry_id)  # 3 -> capped at MAX_APPEALS(2)
    _assert_ledger(contract)


# -----------------------------------------------------------------------------
# Reviewer regression: F1 slashed-bond reservation vs treasury withdrawal
# -----------------------------------------------------------------------------
def _slash_one(direct_vm, direct_deploy, direct_alice):
    """Deploy + submit + NON_COMPLIANT verdict; returns (contract, entry_id)."""
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    entry_id = contract.submit("t", "content", RULES_BLOB)
    _mock_llm(direct_vm, ["VIOLATED", "SATISFIED"])
    direct_vm.value = 0
    contract.evaluate(entry_id)
    return contract, entry_id


def test_attack_withdraw_while_appealable_fails_then_win_refunds(
    direct_vm, direct_deploy, direct_alice, direct_owner
):
    """EXACT reviewer attack: slashed bond must survive a treasury raid and a
    later winning appeal must still be refundable."""
    contract, entry_id = _slash_one(direct_vm, direct_deploy, direct_alice)

    # 1) Treasury tries to withdraw the slashed bond while still appealable.
    direct_vm.sender = direct_owner
    with direct_vm.expect_revert("Collateral reserved for appeal window"):
        contract.withdraw_slashed(MIN_BOND)
    _assert_ledger(contract)
    # The window is still open, so the sweep released nothing:
    assert contract.get_stats()["reserved_slashed"] == str(MIN_BOND)

    # 2) A valid appeal reverses the verdict -> refund, liability released.
    direct_vm.sender = direct_alice
    direct_vm.clear_mocks()
    _mock_llm(direct_vm, ["SATISFIED", "SATISFIED"])
    assert contract.appeal(entry_id) == "COMPLIANT"

    stats = contract.get_stats()
    assert stats["slashed_total"] == "0"
    assert stats["reserved_slashed"] == "0"
    assert stats["withdrawn_slashed"] == "0"
    assert stats["verified"] == "1"
    _assert_ledger(contract)

    # 3) Nothing is withdrawable anymore - the money belongs to the appellant.
    direct_vm.sender = direct_owner
    with direct_vm.expect_revert("Exceeds available slashed"):
        contract.withdraw_slashed(MIN_BOND)


def test_losing_appeals_exhaust_liability_then_finalized(direct_vm, direct_deploy, direct_alice):
    contract, entry_id = _slash_one(direct_vm, direct_deploy, direct_alice)

    contract.appeal(entry_id)  # upheld, count 1: still reserved
    assert contract.get_stats()["reserved_slashed"] == str(MIN_BOND)
    _assert_ledger(contract)

    contract.appeal(entry_id)  # upheld, count 2: liability exhausted -> finalized
    stats = contract.get_stats()
    assert stats["reserved_slashed"] == "0"
    assert stats["slashed_total"] == str(MIN_BOND)
    assert stats["available_slashed"] == str(MIN_BOND)
    assert contract.get_entry(entry_id)["appeal_deadline"] == "0"
    _assert_ledger(contract)


def test_appeal_window_expiry_releases_reservation(direct_vm, direct_deploy, direct_alice, direct_owner):
    contract, entry_id = _slash_one(direct_vm, direct_deploy, direct_alice)
    deadline = int(contract.get_entry(entry_id)["appeal_deadline"])

    # Advance the lifecycle clock past the window with unrelated settled writes.
    direct_vm.value = MIN_BOND
    while int(contract.get_stats()["tick"]) < deadline:
        contract.submit("filler", "filler content", RULES_BLOB)
        direct_vm.value = MIN_BOND
    direct_vm.value = 0

    # Window closed: appeal rejected, but withdraw no longer blocked by F1.
    with direct_vm.expect_revert("Appeal window expired"):
        contract.appeal(entry_id)
    # The sweep inside the withdraw finalizes the expired reservation; the
    # owner then reaches the native-balance guard (direct mode holds none),
    # proving the availability check passed.
    direct_vm.sender = direct_owner
    with direct_vm.expect_revert("Insufficient contract balance"):
        contract.withdraw_slashed(MIN_BOND)
    _assert_ledger(contract)

    # The direct harness persists mid-write state across a revert (on-chain,
    # a reverted transaction rolls back atomically - proven live in Phase 9);
    # the assertion that matters here is that the sweep ran and the
    # availability check PASSED, reaching the native-balance guard.
    assert contract.get_stats()["reserved_slashed"] == "0"
    assert contract.get_entry(entry_id)["appeal_deadline"] == "0"


def test_multiple_slashed_entries_block_until_all_finalized(direct_vm, direct_deploy, direct_alice, direct_owner):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    e1 = contract.submit("a", "content", RULES_BLOB)
    direct_vm.value = MIN_BOND
    e2 = contract.submit("b", "content", RULES_BLOB)
    _mock_llm(direct_vm, ["VIOLATED", "SATISFIED"])
    direct_vm.value = 0
    contract.evaluate(e1)
    contract.evaluate(e2)
    assert contract.get_stats()["reserved_slashed"] == str(2 * MIN_BOND)

    # Finalize only e1 (two upheld appeals): its share becomes withdrawable,
    # but pulling MORE than the finalized share is still blocked by e2.
    contract.appeal(e1)
    contract.appeal(e1)
    assert contract.get_stats()["reserved_slashed"] == str(MIN_BOND)
    assert contract.get_stats()["available_slashed"] == str(MIN_BOND)
    direct_vm.sender = direct_owner
    with direct_vm.expect_revert("Collateral reserved for appeal window"):
        contract.withdraw_slashed(2 * MIN_BOND)
    _assert_ledger(contract)


def test_withdraw_zero_and_over_cap_rejected(direct_vm, direct_deploy, direct_alice, direct_owner):
    contract, entry_id = _slash_one(direct_vm, direct_deploy, direct_alice)
    contract.appeal(entry_id)
    contract.appeal(entry_id)  # finalized: available == MIN_BOND

    direct_vm.sender = direct_owner
    with direct_vm.expect_revert("Amount must be positive"):
        contract.withdraw_slashed(0)
    # Repeated/oversized: more than the single slashed bond is impossible.
    with direct_vm.expect_revert("Exceeds available slashed"):
        contract.withdraw_slashed(MIN_BOND + 1)
    _assert_ledger(contract)


# -----------------------------------------------------------------------------
# Reviewer regression: F2 permanently-PENDING recovery via cancel_pending
# -----------------------------------------------------------------------------
def test_cancel_pending_recovers_bond(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    entry_id = contract.submit("t", "content", RULES_BLOB)
    assert contract.get_stats()["bonded_pending"] == str(MIN_BOND)

    assert contract.cancel_pending(entry_id) == "CANCELLED"
    entry = contract.get_entry(entry_id)
    assert entry["status"] == "CANCELLED"
    assert entry["appeal_deadline"] == "0"
    assert contract.get_stats()["bonded_pending"] == "0"
    _assert_ledger(contract)


def test_cancel_rejected_after_verdict(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    entry_id = contract.submit("t", "content", RULES_BLOB)
    _mock_llm(direct_vm, ["SATISFIED", "SATISFIED"])
    direct_vm.value = 0
    contract.evaluate(entry_id)

    # Cancellation can never bypass a finalized verdict.
    with direct_vm.expect_revert("Entry not pending"):
        contract.cancel_pending(entry_id)


def test_late_evaluate_and_appeal_after_cancel_revert(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    entry_id = contract.submit("t", "content", RULES_BLOB)
    contract.cancel_pending(entry_id)

    # A late evaluation must not settle a cancelled entry (no double refund).
    _mock_llm(direct_vm, ["VIOLATED", "SATISFIED"])
    with direct_vm.expect_revert("Entry not pending"):
        contract.evaluate(entry_id)
    with direct_vm.expect_revert("Only NON_COMPLIANT can be appealed"):
        contract.appeal(entry_id)
    # Repeated cancellation is likewise rejected.
    with direct_vm.expect_revert("Entry not pending"):
        contract.cancel_pending(entry_id)
    assert contract.get_stats()["slashed_total"] == "0"
    _assert_ledger(contract)


def test_cancel_unauthorized(direct_vm, direct_deploy, direct_alice, direct_charlie):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    entry_id = contract.submit("t", "content", RULES_BLOB)

    with direct_vm.prank(direct_charlie):
        with direct_vm.expect_revert("Not authorized to cancel"):
            contract.cancel_pending(entry_id)


# -----------------------------------------------------------------------------
# Reviewer regression: F3 oversized rule sets rejected, never truncated
# -----------------------------------------------------------------------------
def test_rules_at_exact_maximum_accepted(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    blob = "\n".join(f"Rule number {i}" for i in range(30))
    entry_id = contract.submit("t", "content", blob)
    assert len(contract.get_entry(entry_id)["rules"]) == 30

    long_rule = "x" * 300
    direct_vm.value = MIN_BOND
    entry_id2 = contract.submit("t2", "content", long_rule)
    assert contract.get_entry(entry_id2)["rules"] == [long_rule]


def test_rules_above_maximum_rejected(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    blob31 = "\n".join(f"Rule number {i}" for i in range(31))
    with direct_vm.expect_revert("Too many rules"):
        contract.submit("t", "content", blob31)
    with direct_vm.expect_revert("Rule too long"):
        contract.submit("t", "content", "x" * 301)
    # Nothing was stored from the rejected submissions (no silent truncation).
    assert contract.get_stats()["total"] == "0"


def test_title_above_maximum_rejected(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    with direct_vm.expect_revert("Title too long"):
        contract.submit("T" * 201, "content", RULES_BLOB)
    assert contract.get_stats()["total"] == "0"


def test_blank_rule_lines_skipped_and_whitespace_only_rejected(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    entry_id = contract.submit("t", "content", "  \n\n  Rule A  \n\n  Rule B  \n ")
    assert contract.get_entry(entry_id)["rules"] == ["Rule A", "Rule B"]
    direct_vm.value = MIN_BOND
    with direct_vm.expect_revert("No rules provided"):
        contract.submit("t", "content", "   \n  \n")


def test_contradictory_rules_resolve_via_violation(direct_vm, direct_deploy, direct_alice):
    """Contradictory rule sets are admissible (the validator can only mark one
    side VIOLATED); any VIOLATED dominates UNVERIFIABLE in the aggregation."""
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    blob = "Must be entirely in English\nMust not contain any English word"
    entry_id = contract.submit("t", "English content.", blob)

    _mock_llm(direct_vm, ["VIOLATED", "UNVERIFIABLE"])
    direct_vm.value = 0
    assert contract.evaluate(entry_id) == "NON_COMPLIANT"
    _assert_ledger(contract)


def test_withdraw_slashed_owner_only(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    entry_id = contract.submit("t", "content", RULES_BLOB)
    _mock_llm(direct_vm, ["VIOLATED", "SATISFIED"])
    direct_vm.value = 0
    contract.evaluate(entry_id)

    # Non-owner cannot withdraw the treasury. (No `to` parameter anymore:
    # the destination is always the configured treasury - reviewer F5.)
    with direct_vm.prank(direct_bob):
        with direct_vm.expect_revert("Only owner"):
            contract.withdraw_slashed(MIN_BOND)


def test_withdraw_slashed_insufficient_balance(direct_vm, direct_deploy, direct_alice, direct_owner):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    entry_id = contract.submit("t", "content", RULES_BLOB)
    _mock_llm(direct_vm, ["VIOLATED", "SATISFIED"])
    direct_vm.value = 0
    contract.evaluate(entry_id)

    # Exhaust the appeal liability first (two upheld appeals finalize the
    # collateral), then the owner path passes the availability check - but
    # direct mode holds no native balance for the contract, so the transfer
    # guard fires. Reaching that guard at all proves the reservation released.
    contract.appeal(entry_id)
    contract.appeal(entry_id)
    assert contract.get_stats()["reserved_slashed"] == "0"

    direct_vm.sender = direct_owner
    with direct_vm.expect_revert("Insufficient contract balance"):
        contract.withdraw_slashed(MIN_BOND)


def test_list_entries_pagination(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    contract.submit("A", "content a", RULES_BLOB)
    contract.submit("B", "content b", RULES_BLOB)

    page = contract.list_entries(0, 1)
    assert len(page) == 1
    assert page[0]["title"] == "A"
    page2 = contract.list_entries(1, 1)
    assert page2[0]["title"] == "B"
    assert contract.list_entries(5, 5) == []


def test_validator_agrees_when_independent_result_matches(
    direct_vm, direct_deploy, direct_alice
):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    entry_id = contract.submit("t", "content", RULES_BLOB)
    _mock_llm(direct_vm, ["SATISFIED", "SATISFIED"])
    direct_vm.value = 0
    contract.evaluate(entry_id)

    # Validator independently re-derives from the same (stable) mock -> agree.
    assert direct_vm.run_validator() is True


def test_validator_disagrees_when_leader_status_differs(
    direct_vm, direct_deploy, direct_alice
):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    entry_id = contract.submit("t", "content", RULES_BLOB)
    _mock_llm(direct_vm, ["SATISFIED", "SATISFIED"])  # validator will derive COMPLIANT
    direct_vm.value = 0
    contract.evaluate(entry_id)

    # A leader claiming NON_COMPLIANT is rejected: the validator must independently
    # agree on the substantive decision, not just the formatting.
    mismatched = {
        "status": "NON_COMPLIANT",
        "violated_sorted": ["Must be written in English"],
        "checks": [],
        "reason": "leader disagreement fixture",
    }
    assert direct_vm.run_validator(leader_result=mismatched) is False


def test_validator_disagrees_on_llm_error(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    entry_id = contract.submit("t", "content", RULES_BLOB)
    _mock_llm(direct_vm, ["SATISFIED", "SATISFIED"])
    direct_vm.value = 0
    contract.evaluate(entry_id)

    # Leader hit an LLM error -> validators must disagree to force rotation.
    assert direct_vm.run_validator(leader_error=Exception("[LLM_ERROR] bad")) is False
