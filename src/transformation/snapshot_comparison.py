
import json
from collections import defaultdict


IDENTITY_FIELDS = (
    "cik",
    "taxonomy",
    "concept",
    "unit",
    "start_date",
    "end_date",
    "accession",
    "filed_date",
    "form",
    "fiscal_year",
    "fiscal_period",
    "frame",
)


def observation_identity(observation):
    return tuple(
        observation.get(field)
        for field in IDENTITY_FIELDS
    )


def sort_observations(observations):
    return sorted(
        observations,
        key=lambda row: json.dumps(
            row,
            sort_keys=True,
            default=str,
        ),
    )


def group_observations(observations):
    grouped = defaultdict(list)

    for observation in observations:
        identity = observation_identity(observation)
        grouped[identity].append(observation)

    return grouped


def compare_snapshots(before, after):
    before_grouped = group_observations(before)
    after_grouped = group_observations(after)

    result = {
        "added": [],
        "removed": [],
        "changed": [],
        "ambiguous": [],
    }

    all_identities = sorted(
        before_grouped.keys() | after_grouped.keys(),
        key=lambda identity: tuple(
            "" if value is None else str(value)
            for value in identity
        ),
    )

    for identity in all_identities:
        old_rows = before_grouped.get(identity, [])
        new_rows = after_grouped.get(identity, [])

        old_values = {row["value"] for row in old_rows}
        new_values = {row["value"] for row in new_rows}

        if len(old_values) > 1 or len(new_values) > 1:
            result["ambiguous"].append({
                "identity": identity,
                "before": sort_observations(old_rows),
                "after": sort_observations(new_rows),
            })
            continue

        if not old_rows:
            result["added"].append(new_rows[0])
            continue

        if not new_rows:
            result["removed"].append(old_rows[0])
            continue

        if old_values != new_values:
            result["changed"].append({
                "before": old_rows[0],
                "after": new_rows[0],
            })

    return result
