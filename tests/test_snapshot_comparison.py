
from src.transformation.snapshot_comparison import compare_snapshots


def observation(value, accession="0000789019-26-000001"):
    return {
        "cik": 789019,
        "taxonomy": "us-gaap",
        "concept": "Revenues",
        "unit": "USD",
        "start_date": "2025-07-01",
        "end_date": "2026-06-30",
        "accession": accession,
        "filed_date": "2026-07-30",
        "form": "10-K",
        "fiscal_year": 2026,
        "fiscal_period": "FY",
        "frame": "CY2025",
        "value": value,
    }


def test_identical_snapshots_have_no_changes():
    before = [observation(100_000_000)]
    after = [observation(100_000_000)]

    result = compare_snapshots(before, after)

    assert result["added"] == []
    assert result["removed"] == []
    assert result["changed"] == []
    assert result["ambiguous"] == []


def test_new_observation_is_added():
    before = [observation(100_000_000)]
    new = observation(
        200_000_000,
        accession="0000789019-26-000002",
    )
    after = [observation(100_000_000), new]

    result = compare_snapshots(before, after)

    assert result["added"] == [new]
    assert result["removed"] == []
    assert result["changed"] == []
    assert result["ambiguous"] == []


def test_same_identity_with_new_value_is_changed():
    before = [observation(100_000_000)]
    after = [observation(105_000_000)]

    result = compare_snapshots(before, after)

    assert result["added"] == []
    assert result["removed"] == []
    assert result["changed"] == [
        {
            "before": observation(100_000_000),
            "after": observation(105_000_000),
        }
    ]
    assert result["ambiguous"] == []


def test_removed_observation():
    old = observation(100_000_000)

    result = compare_snapshots([old], [])

    assert result["removed"] == [old]
    assert result["added"] == []
    assert result["changed"] == []
    assert result["ambiguous"] == []


def test_reordered_observations_produce_no_changes():
    first = observation(100_000_000)
    second = observation(
        200_000_000,
        accession="0000789019-26-000002",
    )

    result = compare_snapshots(
        [first, second],
        [second, first],
    )

    assert all(not entries for entries in result.values())


def test_identical_duplicates_do_not_create_changes():
    row = observation(100_000_000)

    result = compare_snapshots(
        [row],
        [row, row],
    )

    assert all(not entries for entries in result.values())


def test_conflicting_values_are_ambiguous():
    first = observation(100_000_000)
    conflicting = observation(105_000_000)

    result = compare_snapshots(
        [first],
        [first, conflicting],
    )

    assert result["added"] == []
    assert result["removed"] == []
    assert result["changed"] == []

    assert len(result["ambiguous"]) == 1
    assert result["ambiguous"][0]["before"] == [first]
    assert result["ambiguous"][0]["after"] == [
        first,
        conflicting,
    ]


def test_result_order_is_deterministic():
    first = observation(
        100_000_000,
        accession="0000789019-26-000001",
    )
    second = observation(
        200_000_000,
        accession="0000789019-26-000002",
    )

    result_a = compare_snapshots([], [first, second])
    result_b = compare_snapshots([], [second, first])

    assert result_a == result_b
    assert result_a["added"] == [first, second]


def test_ambiguous_result_is_independent_of_input_order():
    first = observation(100_000_000)
    conflicting = observation(105_000_000)

    result_a = compare_snapshots(
        [first],
        [first, conflicting],
    )

    result_b = compare_snapshots(
        [first],
        [conflicting, first],
    )

    assert result_a == result_b
    assert len(result_a["ambiguous"]) == 1


def test_none_value_changed_to_number():
    before = [observation(None)]
    after = [observation(100_000_000)]

    result = compare_snapshots(before, after)

    assert result["changed"] == [
        {
            "before": observation(None),
            "after": observation(100_000_000),
        }
    ]
    assert result["ambiguous"] == []


def test_duplicate_observations_do_not_create_false_changes():
    first = observation(100_000_000)
    second = observation(
        200_000_000,
        accession="0000789019-26-000002",
    )

    result = compare_snapshots(
        [first, first, second],
        [second, first, first, first],
    )

    assert all(not entries for entries in result.values())
