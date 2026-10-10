"""Direct-mode tests for the standalone ScoreRegistry contract.

ScoreRegistry uses a hybrid pipeline: the LLM translates objective rubric lines
into Python expressions, those expressions are evaluated deterministically in a
sandbox (gl.vm.spawn_sandbox), and the LLM then proposes a 0-100 score against
that ground truth. Direct mode executes the leader path only (validators are
captured), so these tests cover: payload/rubric/threshold/bond validation, the
submit -> grade state machine, PASS/FAIL accounting and slashing, the bounded
submitter appeal (flip releases the held bond; uphold slashes the stake), access
control, the consumer gate views, and the comparative validator's three agreement
rules (exact gate, strict-equal deterministic map, score tolerance band).

Native GEN transfers are a no-op in direct mode, so accounting is asserted on
contract state, not recipient wallets.
"""

import json

MIN_BOND = 10 ** 18  # 1 GEN, atto-scale u256
TITLE = "Launch post"
PAYLOAD = "This post mentions GenLayer explicitly and is over ten characters."
RUBRIC = "At least ten characters\nMentions GenLayer"
CHECK_PROMPT = r"Translate every rubric line"
SCORE_PROMPT = r"Score a piece of work"


def _hex(addr) -> str:
    if isinstance(addr, (bytes, bytearray)):
        return "0x" + bytes(addr).hex()
    return str(addr)


def _deploy(direct_deploy):
    return direct_deploy("standalone/score-registry/contract.py", MIN_BOND)


def _mock_grader(direct_vm, score, checks=None):
    """Register the check-generator + scorer mocks for a deterministic grade."""
    if checks is None:
        checks = [
            {"index": 0, "rule": "At least ten characters", "expression": "len(text) >= 10"},
            {"index": 1, "rule": "Mentions GenLayer", "expression": "'GenLayer' in text"},
        ]
    direct_vm.mock_llm(CHECK_PROMPT, json.dumps({"checks": checks}))
    direct_vm.mock_llm(SCORE_PROMPT, json.dumps({"score": score, "analysis": "fixture"}))


def _submit(direct_vm, direct_deploy, direct_alice, threshold=50):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    item_id = contract.submit(TITLE, PAYLOAD, RUBRIC, threshold)
    direct_vm.value = 0
    return contract, item_id


# ------------------------------------------------------------------ deployment
def test_deploy_initial_state(direct_vm, direct_deploy, direct_owner):
    contract = _deploy(direct_deploy)
    stats = contract.get_stats()
    assert int(stats["total"]) == 0
    assert int(stats["min_bond"]) == MIN_BOND
    assert stats["owner"].lower() == _hex(direct_owner).lower()


# -------------------------------------------------------------------- validation
def test_submit_empty_payload_reverts(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    with direct_vm.expect_revert("Empty payload"):
        contract.submit(TITLE, "   ", RUBRIC, 50)


def test_submit_empty_rubric_reverts(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    with direct_vm.expect_revert("Empty rubric"):
        contract.submit(TITLE, PAYLOAD, "   ", 50)


def test_submit_bad_threshold_reverts(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    with direct_vm.expect_revert("Threshold must be 0-100"):
        contract.submit(TITLE, PAYLOAD, RUBRIC, 150)


def test_submit_below_min_bond_reverts(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND - 1
    with direct_vm.expect_revert("Bond below minimum"):
        contract.submit(TITLE, PAYLOAD, RUBRIC, 50)


def test_submit_creates_pending_item(direct_vm, direct_deploy, direct_alice):
    contract, item_id = _submit(direct_vm, direct_deploy, direct_alice)
    item = contract.get_item(item_id)
    assert item["status"] == "PENDING"
    assert item["submitter"].lower() == _hex(direct_alice).lower()
    assert int(item["bond"]) == MIN_BOND
    assert item["rubric"].split("\n") == ["At least ten characters", "Mentions GenLayer"]
    assert contract.get_stats()["total"] == "1"


def test_view_missing_item_returns_empty(direct_vm, direct_deploy):
    contract = _deploy(direct_deploy)
    assert contract.get_item(999) == {}


# ------------------------------------------------------------------------ grade
def test_grade_passed_refunds_and_gates(direct_vm, direct_deploy, direct_alice):
    contract, item_id = _submit(direct_vm, direct_deploy, direct_alice, threshold=50)
    _mock_grader(direct_vm, 85)
    status = contract.grade(item_id)

    assert status == "PASSED"
    assert contract.get_stats()["passing"] == "1"
    assert contract.get_stats()["slashed_total"] == "0"
    assert contract.passes_gate(item_id) is True
    assert contract.get_score(item_id) == "85"

    # The deterministic sub-checks were evaluated in the sandbox and stored.
    checks = contract.get_item(item_id)["checks"]
    assert len(checks) == 2
    assert all(c["status"] == "SATISFIED" for c in checks)


def test_grade_failed_slashes_bond(direct_vm, direct_deploy, direct_alice):
    contract, item_id = _submit(direct_vm, direct_deploy, direct_alice, threshold=90)
    _mock_grader(direct_vm, 85)
    status = contract.grade(item_id)

    assert status == "FAILED"
    assert contract.get_stats()["failing"] == "1"
    assert contract.get_stats()["slashed_total"] == str(MIN_BOND)
    assert contract.passes_gate(item_id) is False


def test_grade_broken_expression_is_dropped(direct_vm, direct_deploy, direct_alice):
    contract, item_id = _submit(direct_vm, direct_deploy, direct_alice, threshold=50)
    # An unsafe/invalid expression must be skipped, not guessed.
    _mock_grader(
        direct_vm,
        85,
        checks=[
            {"index": 0, "rule": "safe", "expression": "__import__('os').getcwd()"},
            {"index": 1, "rule": "len", "expression": "len(text) >= 10"},
        ],
    )
    status = contract.grade(item_id)
    assert status == "PASSED"
    checks = contract.get_item(item_id)["checks"]
    assert len(checks) == 1  # only the deterministic, safe check survived


def test_grade_unauthorized_reverts(direct_vm, direct_deploy, direct_alice, direct_charlie):
    contract, item_id = _submit(direct_vm, direct_deploy, direct_alice)
    _mock_grader(direct_vm, 85)
    with direct_vm.prank(direct_charlie):
        with direct_vm.expect_revert("Not authorized to grade"):
            contract.grade(item_id)


def test_grade_twice_reverts(direct_vm, direct_deploy, direct_alice):
    contract, item_id = _submit(direct_vm, direct_deploy, direct_alice)
    _mock_grader(direct_vm, 85)
    contract.grade(item_id)
    with direct_vm.expect_revert("already settled"):
        contract.grade(item_id)


# ----------------------------------------------------------------------- appeal
def test_appeal_flip_releases_bond(direct_vm, direct_deploy, direct_alice):
    contract, item_id = _submit(direct_vm, direct_deploy, direct_alice, threshold=90)
    _mock_grader(direct_vm, 85)
    contract.grade(item_id)  # FAILED, bond slashed
    assert contract.get_stats()["slashed_total"] == str(MIN_BOND)

    # Appeal re-grades with a higher score -> flips to PASSED.
    direct_vm.clear_mocks()
    _mock_grader(direct_vm, 95)
    direct_vm.value = MIN_BOND
    status = contract.appeal(item_id)

    assert status == "PASSED"
    assert contract.get_stats()["slashed_total"] == "0"
    assert contract.get_stats()["failing"] == "0"
    assert contract.get_stats()["passing"] == "1"
    assert contract.get_item(item_id)["appeal_count"] == "1"


def test_appeal_upheld_slashes_stake(direct_vm, direct_deploy, direct_alice):
    contract, item_id = _submit(direct_vm, direct_deploy, direct_alice, threshold=90)
    _mock_grader(direct_vm, 85)
    contract.grade(item_id)  # FAILED, bond (B) slashed

    # Appeal still FAILED: this round's stake is additionally slashed.
    direct_vm.value = MIN_BOND
    status = contract.appeal(item_id)
    assert status == "FAILED"
    assert contract.get_stats()["slashed_total"] == str(2 * MIN_BOND)  # bond + stake
    assert contract.get_item(item_id)["appeal_count"] == "1"


def test_appeal_only_by_submitter(direct_vm, direct_deploy, direct_alice, direct_charlie):
    contract, item_id = _submit(direct_vm, direct_deploy, direct_alice, threshold=90)
    _mock_grader(direct_vm, 85)
    contract.grade(item_id)
    direct_vm.value = MIN_BOND
    with direct_vm.prank(direct_charlie):
        with direct_vm.expect_revert("Only submitter can appeal"):
            contract.appeal(item_id)


def test_appeal_requires_failed(direct_vm, direct_deploy, direct_alice):
    contract, item_id = _submit(direct_vm, direct_deploy, direct_alice, threshold=50)
    _mock_grader(direct_vm, 85)
    contract.grade(item_id)  # PASSED -> not appealable
    direct_vm.value = MIN_BOND
    with direct_vm.expect_revert("Only FAILED items can be appealed"):
        contract.appeal(item_id)


def test_appeal_below_stake_minimum_reverts(direct_vm, direct_deploy, direct_alice):
    contract, item_id = _submit(direct_vm, direct_deploy, direct_alice, threshold=90)
    _mock_grader(direct_vm, 85)
    contract.grade(item_id)
    direct_vm.value = MIN_BOND - 1
    with direct_vm.expect_revert("Appeal stake below minimum"):
        contract.appeal(item_id)


def test_appeal_limit(direct_vm, direct_deploy, direct_alice):
    contract, item_id = _submit(direct_vm, direct_deploy, direct_alice, threshold=90)
    _mock_grader(direct_vm, 85)
    contract.grade(item_id)
    direct_vm.value = MIN_BOND
    contract.appeal(item_id)  # 1
    contract.appeal(item_id)  # 2
    with direct_vm.expect_revert("Appeal limit reached"):
        contract.appeal(item_id)  # 3 -> capped at MAX_APPEALS(2)


# ----------------------------------------------------------------------- admin
def test_withdraw_slashed_owner_only(direct_vm, direct_deploy, direct_alice, direct_charlie):
    contract, item_id = _submit(direct_vm, direct_deploy, direct_alice, threshold=90)
    _mock_grader(direct_vm, 85)
    contract.grade(item_id)
    with direct_vm.prank(direct_charlie):
        with direct_vm.expect_revert("Only owner"):
            contract.withdraw_slashed(_hex(direct_charlie), MIN_BOND)


def test_withdraw_slashed_insufficient_balance(direct_vm, direct_deploy, direct_alice, direct_owner, direct_charlie):
    contract, item_id = _submit(direct_vm, direct_deploy, direct_alice, threshold=90)
    _mock_grader(direct_vm, 85)
    contract.grade(item_id)
    direct_vm.sender = direct_owner
    with direct_vm.expect_revert("Insufficient contract balance"):
        contract.withdraw_slashed(_hex(direct_charlie), MIN_BOND)


# ----------------------------------------------------------------------- views
def test_list_items_pagination(direct_vm, direct_deploy, direct_alice):
    contract = _deploy(direct_deploy)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_BOND
    contract.submit("A", PAYLOAD, RUBRIC, 50)
    contract.submit("B", PAYLOAD, RUBRIC, 50)
    page = contract.list_items(0, 1)
    assert len(page) == 1
    assert page[0]["title"] == "A"
    assert contract.list_items(5, 5) == []


# ------------------------------------------------------------------- validator
def test_validator_agrees_on_independent_match(direct_vm, direct_deploy, direct_alice):
    contract, item_id = _submit(direct_vm, direct_deploy, direct_alice, threshold=50)
    _mock_grader(direct_vm, 85)
    contract.grade(item_id)
    # Validator re-runs the whole pipeline against stable mocks -> agrees.
    assert direct_vm.run_validator() is True


def test_validator_disagrees_on_gate_mismatch(direct_vm, direct_deploy, direct_alice):
    contract, item_id = _submit(direct_vm, direct_deploy, direct_alice, threshold=50)
    _mock_grader(direct_vm, 85)  # validator derives PASSED (gate 1)
    contract.grade(item_id)

    # A leader claiming the opposite settlement gate must be rejected.
    leader = {"status": "FAILED", "score": 30, "gate": 0, "checks": [], "deterministic": {}, "reason": "x"}
    assert direct_vm.run_validator(leader_result=leader) is False


def test_validator_disagrees_on_llm_error(direct_vm, direct_deploy, direct_alice):
    contract, item_id = _submit(direct_vm, direct_deploy, direct_alice, threshold=50)
    _mock_grader(direct_vm, 85)
    contract.grade(item_id)
    assert direct_vm.run_validator(leader_error=Exception("[LLM_ERROR] bad")) is False
