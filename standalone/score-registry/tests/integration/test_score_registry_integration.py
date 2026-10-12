"""Integration tests for the standalone ScoreRegistry against a real network.

Under full leader+validator consensus these verify the deterministic surface that
direct mode cannot: deployment on the actual GenVM, payload/rubric/threshold
validation, the bond gate, submit -> PENDING registration, the appeal precondition
(only a settled FAILED item is appealable), and the views.

The `grade` score itself comes from an LLM and is intentionally not pinned to an
exact number here - a real score is not reproducible. The hybrid pipeline
(LLM-generated checks -> deterministic eval -> scored verdict) and the tolerance
band are exercised in the direct-mode suite.

Run explicitly against a reachable, funded network, e.g.:
    $env:RUN_INTEGRATION='1'
    gltest standalone/score-registry/tests/integration/ -v -s --network studio-dev
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
TITLE = "Launch post"
PAYLOAD = "This post mentions GenLayer explicitly and is over ten characters."
RUBRIC = "At least ten characters\nMentions GenLayer"


def _deploy():
    factory = get_contract_factory(contract_file_path="standalone/score-registry/contract.py")
    return factory.deploy(args=[MIN_BOND])


def test_deploy_and_read_state():
    contract = _deploy()
    stats = contract.get_stats(args=[]).call()
    assert int(stats["total"]) == 0
    assert int(stats["min_bond"]) == MIN_BOND


def test_submit_records_pending_item():
    contract = _deploy()
    tx = contract.submit(args=[TITLE, PAYLOAD, RUBRIC, 50], value=MIN_BOND).transact()
    assert tx_execution_succeeded(tx)
    assert int(contract.get_stats(args=[]).call()["total"]) == 1
    item = contract.get_item(args=[0]).call()
    assert item["status"] == "PENDING"


def test_submit_below_bond_reverts():
    contract = _deploy()
    tx = contract.submit(args=[TITLE, PAYLOAD, RUBRIC, 50], value=MIN_BOND - 1).transact()
    assert not tx_execution_succeeded(tx)
    assert int(contract.get_stats(args=[]).call()["total"]) == 0


def test_submit_bad_threshold_reverts():
    contract = _deploy()
    tx = contract.submit(args=[TITLE, PAYLOAD, RUBRIC, 150], value=MIN_BOND).transact()
    assert not tx_execution_succeeded(tx)


def test_submit_empty_rubric_reverts():
    contract = _deploy()
    tx = contract.submit(args=[TITLE, PAYLOAD, "   ", 50], value=MIN_BOND).transact()
    assert not tx_execution_succeeded(tx)


def test_appeal_pending_item_reverts():
    """Appealing a PENDING item is a deterministic revert (only FAILED items are
    appealable), reached identically by every validator before any LLM call."""
    contract = _deploy()
    sub = contract.submit(args=[TITLE, PAYLOAD, RUBRIC, 50], value=MIN_BOND).transact()
    assert tx_execution_succeeded(sub)
    bad = contract.appeal(args=[0], value=MIN_BOND).transact()
    assert not tx_execution_succeeded(bad)
