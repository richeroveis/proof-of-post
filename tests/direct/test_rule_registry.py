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
    I2 reserved_slashed == sum of bonds whose liability is still reserved
       (appeal_deadline > 0)
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

    # Window elapsed: the reservation is sweepable. We deliberately do NOT
    # appeal here (the entry is still appealable under the reserved-liability
    # gate - proven in test_spam_cannot_deny_legitimate_appeal) so this test
    # can exercise the treasury-side sweep path on an untouched reservation:
    # the sweep inside the withdraw finalizes it, then the owner reaches the
    # native-balance guard (direct mode holds none), proving the availability
    # check passed.
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


def test_spam_cannot_deny_legitimate_appeal(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_owner
):
    """AUDIT REGRESSION (tick-window shortening attack, reproduced pre-fix in
    commit history as test_repro_third_party_write_spam_denies_legitimate_appeal
    against the old counter-gated appeal).

    Four cheap state-transition writes from an unrelated account - submit +
    cancel cycles whose bonds come straight back - burn the entire nominal
    APPEAL_WINDOW_TICKS window. Under the reserved-liability gate the victim
    must STILL be able to appeal, because the slashed bond is still fully
    reserved and a reversal remains fundable. The attacker's only remaining
    path to deny an appeal is to make the liability irreversible, which
    requires the owner to execute a completed withdrawal (see the paired
    test below) - a privileged, visible economic act, not free spam.
    """
    contract, entry_id = _slash_one(direct_vm, direct_deploy, direct_alice)
    settle_tick = int(contract.get_stats()["tick"])
    deadline = int(contract.get_entry(entry_id)["appeal_deadline"])
    assert deadline - settle_tick == 4  # APPEAL_WINDOW_TICKS by design

    # Attacker burns the whole nominal window with self-canceling writes.
    direct_vm.sender = direct_bob
    for i in range(2):
        direct_vm.value = MIN_BOND
        sid = contract.submit("spam", f"spam post {i}", RULES_BLOB)
        direct_vm.value = 0
        contract.cancel_pending(sid)
    assert int(contract.get_stats()["tick"]) >= deadline

    # Bond still reserved, no double accounting...
    assert int(contract.get_stats()["reserved_slashed"]) == MIN_BOND

    # ...and the victim's appeal SUCCEEDS despite the burned counter window.
    direct_vm.sender = direct_alice
    direct_vm.clear_mocks()
    _mock_llm(direct_vm, ["SATISFIED", "SATISFIED"])
    assert contract.appeal(entry_id) == "COMPLIANT"

    stats = contract.get_stats()
    assert stats["slashed_total"] == "0"
    assert stats["reserved_slashed"] == "0"
    assert stats["withdrawn_slashed"] == "0"
    assert stats["verified"] == "1"
    assert contract.get_entry(entry_id)["appeal_deadline"] == "0"
    _assert_ledger(contract)

    # The burned bond went back to the appellant: nothing is withdrawable.
    direct_vm.sender = direct_owner
    with direct_vm.expect_revert("Exceeds available slashed"):
        contract.withdraw_slashed(MIN_BOND)


def test_appeal_refused_after_withdraw_sweeps_reservation(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_owner
):
    """SAFETY of the reserved-liability gate: once the liability has actually
    been finalized by the sweep - the only path that releases reserved collateral
    toward the treasury - the appeal right is refused, so a reversal can never
    double-pay against money the treasury already received.

    Mirrors the direct-mode-vs-on-chain caveat documented in
    test_appeal_window_expiry_releases_reservation: here the withdraw reverts
    at the native-balance guard yet the harness persists the mid-write sweep;
    on-chain the same deadline==0 state is only observable after a FULLY
    SUCCESSFUL paying withdrawal, which is exactly when denial is correct.
    """
    contract, entry_id = _slash_one(direct_vm, direct_deploy, direct_alice)
    deadline = int(contract.get_entry(entry_id)["appeal_deadline"])

    # Burn past the nominal window (no appeal attempted, so the reservation
    # stays untouched for the sweep to consume).
    direct_vm.sender = direct_bob
    for i in range(2):
        direct_vm.value = MIN_BOND
        sid = contract.submit("spam", f"spam post {i}", RULES_BLOB)
        direct_vm.value = 0
        contract.cancel_pending(sid)
    assert int(contract.get_stats()["tick"]) >= deadline

    # Owner's withdraw sweeps the expired reservation (reverts at the balance
    # guard in direct mode; the sweep effects persist - see docstring).
    direct_vm.sender = direct_owner
    with direct_vm.expect_revert("Insufficient contract balance"):
        contract.withdraw_slashed(MIN_BOND)
    assert contract.get_entry(entry_id)["appeal_deadline"] == "0"
    assert contract.get_stats()["reserved_slashed"] == "0"

    # Liability finalized -> the submitter can no longer reverse it.
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Appeal liability finalized"):
        contract.appeal(entry_id)
    _assert_ledger(contract)
    # The bond is now treasury-side, not lost: it equals slashed - reserved.
    stats = contract.get_stats()
    assert int(stats["available_slashed"]) == MIN_BOND


def test_post_deadline_upheld_appeals_exhaust_and_release_once(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_owner
):
    """ADVERSARIAL (second-pass review, gap 1): upheld appeals AFTER the nominal
    deadline. The new gate lets these appeals through (reservation intact), so
    the exhaustion release at L430-431 must still fire exactly once and must not
    double-release against the sweep path. Ends with a REAL paying withdrawal
    (contract funded via deal()) to prove the exhausted share is withdrawable
    and no longer appealable.
    """
    contract, entry_id = _slash_one(direct_vm, direct_deploy, direct_alice)
    deadline = int(contract.get_entry(entry_id)["appeal_deadline"])

    # Burn past the nominal window without any withdrawal.
    direct_vm.sender = direct_bob
    for i in range(2):
        direct_vm.value = MIN_BOND
        sid = contract.submit("spam", f"spam post {i}", RULES_BLOB)
        direct_vm.value = 0
        contract.cancel_pending(sid)
    assert int(contract.get_stats()["tick"]) >= deadline
    assert int(contract.get_stats()["reserved_slashed"]) == MIN_BOND

    # Upheld appeal #1 after the deadline: passes the reserved gate, verdict
    # stands, reservation and deadline untouched, nothing released.
    direct_vm.sender = direct_alice
    direct_vm.clear_mocks()
    _mock_llm(direct_vm, ["VIOLATED", "SATISFIED"])
    assert contract.appeal(entry_id) == "NON_COMPLIANT"
    stats = contract.get_stats()
    assert stats["reserved_slashed"] == str(MIN_BOND)
    assert stats["slashed_total"] == str(MIN_BOND)
    assert stats["withdrawn_slashed"] == "0"
    entry = contract.get_entry(entry_id)
    assert entry["appeal_count"] == "1"
    assert int(entry["appeal_deadline"]) == deadline  # upheld: unchanged, >0
    _assert_ledger(contract)

    # Upheld appeal #2: budget exhausted -> releases the reservation exactly
    # once; slashed stays, available becomes the bond, deadline zeroes.
    direct_vm.clear_mocks()
    _mock_llm(direct_vm, ["VIOLATED", "SATISFIED"])
    assert contract.appeal(entry_id) == "NON_COMPLIANT"
    stats = contract.get_stats()
    assert stats["reserved_slashed"] == "0"
    assert stats["slashed_total"] == str(MIN_BOND)
    assert stats["available_slashed"] == str(MIN_BOND)
    assert stats["withdrawn_slashed"] == "0"
    entry = contract.get_entry(entry_id)
    assert entry["appeal_count"] == "2"
    assert entry["appeal_deadline"] == "0"
    _assert_ledger(contract)

    # Further appeals refused by the count gate; a real paying withdrawal now
    # succeeds (funded so the native-balance guard passes like on-chain).
    with direct_vm.expect_revert("Appeal limit reached"):
        contract.appeal(entry_id)
    direct_vm.sender = direct_owner
    direct_vm.deal(direct_vm._contract_address, MIN_BOND)
    contract.withdraw_slashed(MIN_BOND)  # must fully succeed, no revert
    stats = contract.get_stats()
    assert stats["withdrawn_slashed"] == str(MIN_BOND)
    assert stats["available_slashed"] == "0"
    _assert_ledger(contract)


def test_post_deadline_appeal_inconclusive_refunds_without_verify(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """ADVERSARIAL (second-pass review, gap 2): an appeal past the nominal
    deadline resolving to INCONCLUSIVE. Encodes the implementation's intended
    behavior (contracts/rule_registry.py L417-427): the flip branch fires for
    any status != NON_COMPLIANT - release the reservation, un-slash, refund the
    bond, verified_count credited ONLY for COMPLIANT, deadline zeroed. Nothing
    may remain reserved or slashed afterwards.
    """
    contract, entry_id = _slash_one(direct_vm, direct_deploy, direct_alice)
    deadline = int(contract.get_entry(entry_id)["appeal_deadline"])

    direct_vm.sender = direct_bob
    for i in range(2):
        direct_vm.value = MIN_BOND
        sid = contract.submit("spam", f"spam post {i}", RULES_BLOB)
        direct_vm.value = 0
        contract.cancel_pending(sid)
    assert int(contract.get_stats()["tick"]) >= deadline

    direct_vm.sender = direct_alice
    direct_vm.clear_mocks()
    _mock_llm(direct_vm, ["UNVERIFIABLE", "SATISFIED"])
    assert contract.appeal(entry_id) == "INCONCLUSIVE"

    entry = contract.get_entry(entry_id)
    assert entry["status"] == "INCONCLUSIVE"
    assert entry["appeal_count"] == "1"
    assert entry["appeal_deadline"] == "0"
    stats = contract.get_stats()
    assert stats["reserved_slashed"] == "0"      # released exactly once
    assert stats["slashed_total"] == "0"          # un-slash
    assert stats["withdrawn_slashed"] == "0"      # never touched the treasury
    assert stats["available_slashed"] == "0"
    assert stats["verified"] == "0"               # INCONCLUSIVE earns no credit
    _assert_ledger(contract)

    # A second appeal is refused by the status gate (not NON_COMPLIANT), and
    # the treasury has nothing to withdraw (slashed_total is 0).
    with direct_vm.expect_revert("Only NON_COMPLIANT can be appealed"):
        contract.appeal(entry_id)


def test_mixed_window_sweep_finalizes_only_elapsed_reservations(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_owner
):
    """ADVERSARIAL (second-pass review, gap 3): sweep selectivity with two open
    reservations at DIFFERENT deadlines and a genuinely successful paying
    withdrawal. The sweep must finalize only the elapsed entry - the younger
    reservation stays reserved AND appealable - and the treasury may receive
    only the eligible share.
    """
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice

    # A: submit -> evaluate (settle tick 2, deadline 6).
    direct_vm.value = MIN_BOND
    a = contract.submit("older", "content a", RULES_BLOB)
    _mock_llm(direct_vm, ["VIOLATED", "SATISFIED"])
    direct_vm.value = 0
    contract.evaluate(a)
    dl_a = int(contract.get_entry(a)["appeal_deadline"])

    # B: settle two writes later (deadline 8) -> strictly younger.
    direct_vm.value = MIN_BOND
    b = contract.submit("younger", "content b", RULES_BLOB)
    direct_vm.value = 0
    contract.evaluate(b)
    dl_b = int(contract.get_entry(b)["appeal_deadline"])
    assert dl_a < dl_b
    stats = contract.get_stats()
    assert stats["reserved_slashed"] == str(2 * MIN_BOND)
    assert stats["available_slashed"] == "0"
    _assert_ledger(contract)

    # Advance so tick reaches dl_a but stays BELOW dl_b.
    direct_vm.sender = direct_bob
    direct_vm.value = MIN_BOND
    while int(contract.get_stats()["tick"]) < dl_a:
        contract.submit("filler", "filler content", RULES_BLOB)
    direct_vm.value = 0
    tick_now = int(contract.get_stats()["tick"])
    assert dl_a <= tick_now < dl_b

    # Owner funds-and-withdraws the single eligible bond: the withdraw's own
    # tick++ lands before dl_b still, so only A is swept, then paid out.
    direct_vm.sender = direct_owner
    direct_vm.deal(direct_vm._contract_address, MIN_BOND)
    contract.withdraw_slashed(MIN_BOND)  # must fully succeed, no revert

    stats = contract.get_stats()
    assert stats["withdrawn_slashed"] == str(MIN_BOND)      # treasury got A only
    assert stats["reserved_slashed"] == str(MIN_BOND)       # B still reserved
    assert stats["slashed_total"] == str(2 * MIN_BOND)
    assert stats["available_slashed"] == "0"                # 2 - 1 - 1
    assert contract.get_entry(a)["appeal_deadline"] == "0"
    assert int(contract.get_entry(b)["appeal_deadline"]) == dl_b
    _assert_ledger(contract)

    # A: finalized by the paid sweep -> appeal refused.
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Appeal liability finalized"):
        contract.appeal(a)

    # B: untouched reservation -> appeal STILL possible and reverses; the
    # refund comes from B's own retained collateral, never from A's paid bond.
    direct_vm.clear_mocks()
    _mock_llm(direct_vm, ["SATISFIED", "SATISFIED"])
    assert contract.appeal(b) == "COMPLIANT"
    stats = contract.get_stats()
    assert stats["reserved_slashed"] == "0"
    assert stats["slashed_total"] == str(MIN_BOND)   # only A remains slashed
    assert stats["withdrawn_slashed"] == str(MIN_BOND)
    assert stats["available_slashed"] == "0"          # 1 - 1 - 0
    assert stats["verified"] == "1"
    _assert_ledger(contract)


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


def test_second_withdrawal_after_successful_withdrawal_reverts_without_double_payout(
    direct_vm, direct_deploy, direct_alice, direct_owner
):
    """REJECTION GAP 2: a second withdraw_slashed after a SUCCESSFUL withdrawal
    must revert and must not pay out twice or release further collateral.

    Full legitimate flow: slash a real bond, finalize its withdrawal eligibility
    through the appeal-count exhaustion path (two upheld appeals), fund the
    contract's native balance so the FIRST withdrawal is a genuinely paying
    success (not the balance-guard revert used elsewhere), withdraw once, verify
    the ledger, then withdraw the exact same amount again and pin the revert
    with the availability error. Per the documented direct-harness behavior a
    reverted write keeps its tick increment (on-chain it rolls back atomically,
    proven live), so only the monetary fields are asserted after the second
    attempt.
    """
    contract, entry_id = _slash_one(direct_vm, direct_deploy, direct_alice)

    # Legitimate finalization: two upheld appeals exhaust the appeal budget.
    contract.appeal(entry_id)
    contract.appeal(entry_id)
    stats = contract.get_stats()
    assert stats["reserved_slashed"] == "0"
    assert stats["available_slashed"] == str(MIN_BOND)

    # First withdrawal: fully paying success.
    direct_vm.sender = direct_owner
    direct_vm.deal(direct_vm._contract_address, MIN_BOND)
    contract.withdraw_slashed(MIN_BOND)  # must NOT revert
    stats = contract.get_stats()
    assert stats["withdrawn_slashed"] == str(MIN_BOND)
    assert stats["available_slashed"] == "0"
    assert stats["reserved_slashed"] == "0"
    assert stats["slashed_total"] == str(MIN_BOND)
    _assert_ledger(contract)

    # Second withdrawal of the same amount: rejected by the availability cap,
    # reserved is 0 so the message is the exact "Exceeds available slashed".
    with direct_vm.expect_revert("Exceeds available slashed"):
        contract.withdraw_slashed(MIN_BOND)

    # No double payout: nothing moved by the rejected attempt.
    stats = contract.get_stats()
    assert stats["withdrawn_slashed"] == str(MIN_BOND)   # unchanged
    assert stats["reserved_slashed"] == "0"              # no further release
    assert stats["available_slashed"] == "0"
    assert stats["slashed_total"] == str(MIN_BOND)
    _assert_ledger(contract)


def test_second_withdrawal_of_remaining_available_succeeds_and_third_reverts(
    direct_vm, direct_deploy, direct_alice, direct_owner
):
    """REJECTION GAP 2 (case 2 and 6): split the finalized collateral into two
    legitimate withdrawals. The first takes half the available amount, the
    second takes exactly the remaining available and MUST succeed, and a third
    beyond what is available MUST revert. The treasury-receipt ledger (the
    direct-mode proxy for the treasury balance, since native transfers are a
    no-op here) equals exactly the sum of the two payouts afterwards, never more.
    """
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    e1 = contract.submit("a", "content a", RULES_BLOB)
    direct_vm.value = MIN_BOND
    e2 = contract.submit("b", "content b", RULES_BLOB)
    _mock_llm(direct_vm, ["VIOLATED", "SATISFIED"])
    direct_vm.value = 0
    contract.evaluate(e1)
    contract.evaluate(e2)

    # Two upheld appeals per entry finalize both liabilities (reserved -> 0).
    contract.appeal(e1)
    contract.appeal(e1)
    contract.appeal(e2)
    contract.appeal(e2)
    stats = contract.get_stats()
    assert stats["reserved_slashed"] == "0"
    assert stats["slashed_total"] == str(2 * MIN_BOND)
    assert stats["available_slashed"] == str(2 * MIN_BOND)
    _assert_ledger(contract)

    direct_vm.sender = direct_owner
    direct_vm.deal(direct_vm._contract_address, 2 * MIN_BOND)

    # First withdrawal: half the finalized amount.
    contract.withdraw_slashed(MIN_BOND)  # must NOT revert
    stats = contract.get_stats()
    assert stats["withdrawn_slashed"] == str(MIN_BOND)
    assert stats["available_slashed"] == str(MIN_BOND)
    _assert_ledger(contract)

    # Second withdrawal: the remaining available succeeds.
    contract.withdraw_slashed(MIN_BOND)  # must NOT revert
    stats = contract.get_stats()
    # Sum of the two payouts, exactly once each (treasury-receipt proxy).
    assert stats["withdrawn_slashed"] == str(2 * MIN_BOND)
    assert stats["available_slashed"] == "0"
    _assert_ledger(contract)

    # Third withdrawal beyond what is available reverts and pays nothing.
    with direct_vm.expect_revert("Exceeds available slashed"):
        contract.withdraw_slashed(MIN_BOND)
    stats = contract.get_stats()
    assert stats["withdrawn_slashed"] == str(2 * MIN_BOND)  # unchanged
    assert stats["available_slashed"] == "0"
    _assert_ledger(contract)


def test_withdraw_is_capped_by_native_balance_then_by_availability(
    direct_vm, direct_deploy, direct_alice, direct_owner
):
    """REJECTION GAP 2 (case 3): a withdrawal is bounded by TWO independent
    ceilings, the availability figure and the contract's native balance. Finalize
    one bond, then prove the native-balance guard is a real separate cap: with
    zero funded balance the availability check passes but the payout reverts at
    `Insufficient contract balance`, leaving the ledger untouched. Fund exactly
    the bond, pay it, and show a second withdrawal right after (no new slashed
    funds) is then stopped by the availability cap even though the direct-mode
    native balance does not decrease after a no-op payout.
    """
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    e1 = contract.submit("a", "content a", RULES_BLOB)
    _mock_llm(direct_vm, ["VIOLATED", "SATISFIED"])
    direct_vm.value = 0
    contract.evaluate(e1)
    contract.appeal(e1)
    contract.appeal(e1)  # finalize: available == MIN_BOND, reserved 0
    stats = contract.get_stats()
    assert stats["reserved_slashed"] == "0"
    assert stats["available_slashed"] == str(MIN_BOND)

    # Native-balance ceiling: funded balance is zero, so the availability check
    # passes and the distinct balance guard fires. Reaching it proves balance is
    # its own cap, not just a restatement of the availability figure.
    direct_vm.sender = direct_owner
    with direct_vm.expect_revert("Insufficient contract balance"):
        contract.withdraw_slashed(MIN_BOND)
    assert contract.get_stats()["withdrawn_slashed"] == "0"
    _assert_ledger(contract)

    # Fund the exact finalized bond and withdraw it: genuine paying success.
    direct_vm.deal(direct_vm._contract_address, MIN_BOND)
    contract.withdraw_slashed(MIN_BOND)  # must NOT revert
    stats = contract.get_stats()
    assert stats["withdrawn_slashed"] == str(MIN_BOND)
    assert stats["available_slashed"] == "0"
    _assert_ledger(contract)

    # Second withdrawal right after, no new slashed funds: the availability cap
    # stops it (in direct mode the balance stays funded because emit_transfer is
    # a no-op, so only the ledger cap can, and does, block the repeat).
    with direct_vm.expect_revert("Exceeds available slashed"):
        contract.withdraw_slashed(MIN_BOND)
    assert contract.get_stats()["withdrawn_slashed"] == str(MIN_BOND)
    _assert_ledger(contract)


def test_second_withdrawal_does_not_ressweep_or_double_count_a_finalized_entry(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_owner
):
    """REJECTION GAP 2 (case 5): a reservation swept and paid by the FIRST
    withdrawal is finalized, becomes non-appealable, and must NOT be swept or
    counted again by a SECOND withdrawal. Two entries settle at different
    deadlines; the first withdrawal sweeps only the elapsed one and pays it, the
    second (after the younger one also elapses) sweeps that one and pays it, and
    the treasury-receipt ledger is exactly the sum of the two payouts, never
    double-counting the first entry.
    """
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice

    direct_vm.value = MIN_BOND
    a = contract.submit("a", "content a", RULES_BLOB)
    _mock_llm(direct_vm, ["VIOLATED", "SATISFIED"])
    direct_vm.value = 0
    contract.evaluate(a)
    dl_a = int(contract.get_entry(a)["appeal_deadline"])

    direct_vm.value = MIN_BOND
    b = contract.submit("b", "content b", RULES_BLOB)
    direct_vm.value = 0
    contract.evaluate(b)
    dl_b = int(contract.get_entry(b)["appeal_deadline"])
    assert dl_a < dl_b
    assert contract.get_stats()["reserved_slashed"] == str(2 * MIN_BOND)

    # Advance into A's expiry but stay below B's.
    direct_vm.sender = direct_bob
    direct_vm.value = MIN_BOND
    while int(contract.get_stats()["tick"]) < dl_a:
        contract.submit("filler", "filler content", RULES_BLOB)
    direct_vm.value = 0
    assert dl_a <= int(contract.get_stats()["tick"]) < dl_b

    # First withdrawal sweeps and pays ONLY A; B stays reserved and appealable.
    direct_vm.sender = direct_owner
    direct_vm.deal(direct_vm._contract_address, 2 * MIN_BOND)
    contract.withdraw_slashed(MIN_BOND)  # must NOT revert
    stats = contract.get_stats()
    assert stats["withdrawn_slashed"] == str(MIN_BOND)       # A paid only
    assert stats["reserved_slashed"] == str(MIN_BOND)        # B still reserved
    assert contract.get_entry(a)["appeal_deadline"] == "0"   # A finalized
    assert int(contract.get_entry(b)["appeal_deadline"]) == dl_b
    _assert_ledger(contract)

    # A is no longer appealable after the completed paying withdrawal swept it.
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Appeal liability finalized"):
        contract.appeal(a)

    # Advance past B's window; the second withdrawal sweeps B and pays it. A's
    # deadline is already 0 so the sweep skips it: withdrawn grows by exactly
    # B's bond (sum of the two payouts), and A stays finalized/non-appealable.
    direct_vm.sender = direct_bob
    direct_vm.value = MIN_BOND
    while int(contract.get_stats()["tick"]) < dl_b:
        contract.submit("filler2", "filler content", RULES_BLOB)
    direct_vm.value = 0
    direct_vm.sender = direct_owner
    contract.withdraw_slashed(MIN_BOND)  # must NOT revert
    stats = contract.get_stats()
    assert stats["withdrawn_slashed"] == str(2 * MIN_BOND)   # A + B, no double count
    assert stats["reserved_slashed"] == "0"
    assert stats["slashed_total"] == str(2 * MIN_BOND)
    assert stats["available_slashed"] == "0"
    assert contract.get_entry(a)["appeal_deadline"] == "0"
    assert contract.get_entry(b)["appeal_deadline"] == "0"
    _assert_ledger(contract)

    # The second withdrawal did not reopen A: still non-appealable.
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Appeal liability finalized"):
        contract.appeal(a)


def test_withdraw_negative_amount_rejected_cleanly(direct_vm, direct_deploy, direct_alice, direct_owner):
    """AUDIT boundary: a negative amount must fail with the same deterministic
    [EXPECTED] error as zero, not an opaque unsigned-cast failure, and must not
    mutate the ledger. Exercises the raw-int sign check added before the u256
    cast in withdraw_slashed."""
    contract, entry_id = _slash_one(direct_vm, direct_deploy, direct_alice)
    contract.appeal(entry_id)
    contract.appeal(entry_id)  # finalize: available == MIN_BOND, reserved 0
    before = dict(contract.get_stats())

    direct_vm.sender = direct_owner
    with direct_vm.expect_revert("Amount must be positive"):
        contract.withdraw_slashed(-1)
    after = contract.get_stats()
    # Nothing was released or paid out by the rejected call.
    assert after["withdrawn_slashed"] == before["withdrawn_slashed"]
    assert after["reserved_slashed"] == "0"
    assert after["available_slashed"] == str(MIN_BOND)
    _assert_ledger(contract)


def test_bond_above_minimum_is_slashed_reserved_and_withdrawn_exactly(
    direct_vm, direct_deploy, direct_alice, direct_owner
):
    """AUDIT: accounting must scale with the ACTUAL posted bond, never assume it
    equals min_bond. A 2x bond slashes, reserves, exhausts, and withdraws at the
    exact 2x amount with every ledger invariant intact."""
    contract = _deploy(direct_deploy)
    big = 2 * MIN_BOND
    direct_vm.sender = direct_alice
    direct_vm.value = big
    entry_id = contract.submit("t", "content", RULES_BLOB)
    assert contract.get_stats()["bonded_pending"] == str(big)

    _mock_llm(direct_vm, ["VIOLATED", "SATISFIED"])
    direct_vm.value = 0
    assert contract.evaluate(entry_id) == "NON_COMPLIANT"
    stats = contract.get_stats()
    assert stats["slashed_total"] == str(big)      # slashed the FULL bond
    assert stats["reserved_slashed"] == str(big)   # reserved the FULL bond
    _assert_ledger(contract)

    # Two upheld appeals finalize the liability at the full amount.
    contract.appeal(entry_id)
    contract.appeal(entry_id)
    stats = contract.get_stats()
    assert stats["reserved_slashed"] == "0"
    assert stats["available_slashed"] == str(big)
    _assert_ledger(contract)

    # Treasury pulls the exact finalized 2x bond (funded so the balance guard
    # passes as it would on-chain).
    direct_vm.sender = direct_owner
    direct_vm.deal(direct_vm._contract_address, big)
    contract.withdraw_slashed(big)
    stats = contract.get_stats()
    assert stats["withdrawn_slashed"] == str(big)
    assert stats["available_slashed"] == "0"
    _assert_ledger(contract)


def test_withdraw_sweep_finalizes_all_elapsed_reservations(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_owner
):
    """AUDIT: the sweep inside one withdrawal finalizes EVERY reservation whose
    nominal window has elapsed - including an entry whose submitter still has
    appeal budget but never used it before the window closed. This is the
    documented trade-off (the tick window is the appeal deadline; only the
    owner executing a withdrawal after the window can finalize an un-exhausted
    reservation). Pinned so the behavior is intentional, not accidental, and the
    ledger invariants still hold across the mixed finalization."""
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    a = contract.submit("a", "content a", RULES_BLOB)
    direct_vm.value = MIN_BOND
    b = contract.submit("b", "content b", RULES_BLOB)
    _mock_llm(direct_vm, ["VIOLATED", "SATISFIED"])
    direct_vm.value = 0
    contract.evaluate(a)
    contract.evaluate(b)
    dl_a = int(contract.get_entry(a)["appeal_deadline"])
    dl_b = int(contract.get_entry(b)["appeal_deadline"])
    assert contract.get_stats()["reserved_slashed"] == str(2 * MIN_BOND)

    # Burn past BOTH windows (no appeal used by the submitters).
    direct_vm.sender = direct_bob
    direct_vm.value = MIN_BOND
    while int(contract.get_stats()["tick"]) < max(dl_a, dl_b):
        contract.submit("filler", "filler content", RULES_BLOB)
    direct_vm.value = 0

    # One owner withdrawal both sweeps the elapsed reservations AND pays out:
    # neither entry stays appealable, and both bonds become the treasury's.
    direct_vm.sender = direct_owner
    direct_vm.deal(direct_vm._contract_address, 2 * MIN_BOND)
    contract.withdraw_slashed(2 * MIN_BOND)
    stats = contract.get_stats()
    assert stats["reserved_slashed"] == "0"
    assert stats["withdrawn_slashed"] == str(2 * MIN_BOND)
    assert stats["available_slashed"] == "0"
    assert contract.get_entry(a)["appeal_deadline"] == "0"
    assert contract.get_entry(b)["appeal_deadline"] == "0"
    _assert_ledger(contract)

    # Finalized liability -> the submitter's appeal is refused, not double-paid.
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Appeal liability finalized"):
        contract.appeal(a)
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
