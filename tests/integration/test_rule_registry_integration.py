"""Integration tests for ProofOfPost RuleRegistry against a real GenLayer network.

These run under full leader+validator consensus and therefore validate what
direct mode cannot: that the contract deploys and its deterministic state
machine (bond gate, access control, entry transitions, views) agrees across
validators on the actual GenVM.

Why not GLSim: on Windows the shipped GLSim simulator is incompatible with this
pinned GenVM runner (the harness reverts on cached-root `@allow_storage`, view
calls raise "No VM context active", and the returned schema omits methods), so
consensus is exercised against the deployed Studio dev network instead. That is
the authoritative environment and the same one the project ships on.

The nondeterministic `evaluate` LLM adjudication is covered by the direct-mode
suite (leader + comparative validator). Here we assert only deterministic
transitions; a real LLM verdict is non-reproducible and must not be pinned to an
exact status.

Run explicitly against a reachable network, e.g.:
    $env:RUN_INTEGRATION='1'
    gltest tests/integration/ -v -s --network studio-dev
"""

import os

import pytest
from gltest import get_contract_factory
from gltest.assertions import tx_execution_succeeded

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason="Set RUN_INTEGRATION=1 and target a real network to run integration tests",
)

MIN_BOND = 10 ** 18
RULES_BLOB = "Must be written in English\nMust be under 100 words"
TERMINAL = {"COMPLIANT", "NON_COMPLIANT", "INCONCLUSIVE"}


def _deploy():
    factory = get_contract_factory(contract_file_path="rule_registry.py")
    return factory.deploy(args=[MIN_BOND])


def test_deploy_and_read_state():
    contract = _deploy()
    stats = contract.get_stats(args=[]).call()
    assert int(stats["total"]) == 0
    assert int(stats["min_bond"]) == MIN_BOND


def test_submit_records_pending_entry():
    contract = _deploy()
    tx = contract.submit(
        args=["My Post", "A short english post.", RULES_BLOB], value=MIN_BOND
    ).transact()
    assert tx_execution_succeeded(tx)

    stats = contract.get_stats(args=[]).call()
    assert int(stats["total"]) == 1
    # Entry ids are 0-based (next_id starts at 0).
    entry = contract.get_entry(args=[0]).call()
    assert entry["status"] == "PENDING"


def test_submit_below_bond_reverts():
    contract = _deploy()
    tx = contract.submit(args=["t", "content", RULES_BLOB], value=MIN_BOND - 1).transact()
    assert not tx_execution_succeeded(tx)
    assert int(contract.get_stats(args=[]).call()["total"]) == 0


def test_evaluate_twice_reverts():
    """Second evaluate on a resolved entry is a deterministic revert that all
    validators must agree on, regardless of the LLM's first verdict."""
    contract = _deploy()
    tx = contract.submit(args=["t", "Some english content.", RULES_BLOB], value=MIN_BOND).transact()
    assert tx_execution_succeeded(tx)

    first = contract.evaluate(args=[0]).transact()
    assert tx_execution_succeeded(first)
    status = contract.get_entry(args=[0]).call()["status"]
    assert status in TERMINAL

    second = contract.evaluate(args=[0]).transact()
    assert not tx_execution_succeeded(second)


def test_cancel_pending_then_late_evaluate_reverts():
    """Reviewer F2 recovery path: a PENDING bond can be cancelled (deterministic,
    no LLM), and the cancelled entry can then never be evaluated - the bond is
    settled exactly once."""
    contract = _deploy()
    tx = contract.submit(args=["t", "content", RULES_BLOB], value=MIN_BOND).transact()
    assert tx_execution_succeeded(tx)

    cancel = contract.cancel_pending(args=[0]).transact()
    assert tx_execution_succeeded(cancel)
    assert contract.get_entry(args=[0]).call()["status"] == "CANCELLED"

    late = contract.evaluate(args=[0]).transact()
    assert not tx_execution_succeeded(late)


def test_oversized_rules_revert():
    """Reviewer F3: oversized rule sets revert deterministically; nothing is
    stored and nothing is silently truncated."""
    contract = _deploy()
    blob31 = "\n".join(f"Rule number {i}" for i in range(31))
    tx = contract.submit(args=["t", "content", blob31], value=MIN_BOND).transact()
    assert not tx_execution_succeeded(tx)
    assert int(contract.get_stats(args=[]).call()["total"]) == 0


def test_appeal_only_by_non_submitter_reverts():
    contract = _deploy()
    tx = contract.submit(args=["t", "content", RULES_BLOB], value=MIN_BOND).transact()
    assert tx_execution_succeeded(tx)
    # A fresh random account (default deployer == submitter here) cannot appeal an
    # entry that is still PENDING; appeal requires NON_COMPLIANT and the submitter.
    pending = contract.appeal(args=[0]).transact()
    assert not tx_execution_succeeded(pending)
