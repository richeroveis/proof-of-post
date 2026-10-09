"""Direct-mode tests for the ProofOfPost RuleRegistry contract.

Direct mode executes only the leader function of run_nondet (validators are
captured, not run), so these tests cover: bond gate, input validation, access
control, entry state machine (PENDING -> COMPLIANT / NON_COMPLIANT /
INCONCLUSIVE), slashing/refund accounting, appeals, views, and the comparative
validator logic (via direct_vm.run_validator).

Native GEN refunds (emit_transfer) are a no-op in direct mode, so we assert the
contract's internal accounting rather than recipient wallet balances.
"""

import json

import pytest

MIN_BOND = 10 ** 18  # 1 GEN, atto-scale u256
RULES_BLOB = "Must be written in English\nMust be under 100 words"


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
    entry = contract.get_entry(entry_id)
    assert entry["checks"][0]["status"] == "VIOLATED"


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
    assert contract.get_stats()["verified"] == "1"
    assert contract.get_entry(entry_id)["appeal_count"] == "1"


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


def test_withdraw_slashed_owner_only(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    entry_id = contract.submit("t", "content", RULES_BLOB)
    _mock_llm(direct_vm, ["VIOLATED", "SATISFIED"])
    direct_vm.value = 0
    contract.evaluate(entry_id)

    # Non-owner cannot withdraw the treasury.
    with direct_vm.prank(direct_bob):
        with direct_vm.expect_revert("Only owner"):
            contract.withdraw_slashed(_hex(direct_bob), MIN_BOND)


def test_withdraw_slashed_insufficient_balance(direct_vm, direct_deploy, direct_alice, direct_owner, direct_bob):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    entry_id = contract.submit("t", "content", RULES_BLOB)
    _mock_llm(direct_vm, ["VIOLATED", "SATISFIED"])
    direct_vm.value = 0
    contract.evaluate(entry_id)

    # Owner path passes the slashed-availability check, but direct mode holds no
    # native balance for the contract, so the transfer guard fires.
    direct_vm.sender = direct_owner
    with direct_vm.expect_revert("Insufficient contract balance"):
        contract.withdraw_slashed(_hex(direct_bob), MIN_BOND)


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
