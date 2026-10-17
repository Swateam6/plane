# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only

from datetime import date
from types import SimpleNamespace

import pytest

from plane.db.models import Issue, Project
from plane.utils.filters.converters import LegacyToRichFiltersConverter
from plane.utils.filters.filter_backend import ComplexFilterBackend
from plane.utils.filters.filterset import IssueFilterSet


@pytest.fixture
def filter_project(workspace, create_user):
    return Project.objects.create(
        name="Date Filter Regression",
        identifier="DFR",
        workspace=workspace,
        created_by=create_user,
    )


@pytest.mark.contract
@pytest.mark.django_db
@pytest.mark.parametrize("field", ["start_date", "target_date"])
@pytest.mark.parametrize("high_only", [False, True])
def test_converted_range_filters_real_work_items(
    filter_project,
    create_user,
    field,
    high_only,
):
    # Converted ranges must include both boundary days and honor an optional priority filter.
    rows = [
        ("before", date(2023, 8, 31), "high"),
        ("lower-bound", date(2023, 9, 1), "high"),
        ("inside", date(2023, 9, 15), "high"),
        ("upper-bound", date(2023, 10, 1), "high"),
        ("after", date(2023, 10, 2), "high"),
        ("inside-low", date(2023, 9, 20), "low"),
    ]

    for name, value, priority in rows:
        Issue.objects.create(
            name=name,
            project=filter_project,
            workspace=filter_project.workspace,
            created_by=create_user,
            priority=priority,
            **{field: value},
        )

    legacy = {
        field: ["9/1/2023;after", "10/1/2023;before"]
    }
    if high_only:
        legacy["priority"] = ["high"]

    converted = LegacyToRichFiltersConverter().convert(legacy)

    # Minimal adapters: parsing and queryset filtering use real code.
    request = SimpleNamespace(query_params={})
    view = SimpleNamespace(filterset_class=IssueFilterSet)

    result = ComplexFilterBackend().filter_queryset(
        request=request,
        queryset=Issue.objects.filter(project=filter_project),
        view=view,
        filter_data=converted,
    )

    expected = {"lower-bound", "inside", "upper-bound"}
    if not high_only:
        expected.add("inside-low")

    assert set(result.values_list("name", flat=True)) == expected
