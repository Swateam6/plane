# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only

from copy import deepcopy

import pytest

from plane.utils.filters.converters import LegacyToRichFiltersConverter


@pytest.fixture
def converter():
    return LegacyToRichFiltersConverter()


@pytest.mark.unit
class TestLegacyDateRanges:
    @pytest.mark.parametrize("field", ["start_date", "target_date"])
    @pytest.mark.parametrize(
        ("values", "expected"),
        [
            pytest.param(
                ["9/1/2023;after", "10/1/2023;before"],
                "2023-09-01,2023-10-01",
                id="reported-slash-dates",
            ),
            pytest.param(
                ["10/1/2023;before", "9/1/2023;after"],
                "2023-09-01,2023-10-01",
                id="reversed-input-list",
            ),
            pytest.param(
                ["2023-9-1;after", "2023-10-1;before"],
                "2023-09-01,2023-10-01",
                id="unpadded-dates",
            ),
            pytest.param(
                ["Sep 1 2023;after", "Oct 1 2023;before"],
                "2023-09-01,2023-10-01",
                id="month-names",
            ),
            pytest.param(
                ["September 1, 2023;after", "October 1, 2023;before"],
                "2023-09-01,2023-10-01",
                id="dates-containing-csv-delimiter",
            ),
            pytest.param(
                ["2023-09-01;after", "10/1/2023;before"],
                "2023-09-01,2023-10-01",
                id="mixed-formats",
            ),
            pytest.param(
                ["12/15/2023;after", "1/15/2024;before"],
                "2023-12-15,2024-01-15",
                id="year-boundary",
            ),
            pytest.param(
                ["9/1/2023;after", "9/1/2023;before"],
                "2023-09-01,2023-09-01",
                id="equal-bounds",
            ),
            pytest.param(
                ["2/29/2024;after", "3/1/2024;before"],
                "2024-02-29,2024-03-01",
                id="leap-day",
            ),
            pytest.param(
                ["2023-09-01;after", "2023-10-01;before"],
                "2023-09-01,2023-10-01",
                id="existing-iso-range",
            ),
            pytest.param(
                ["2023-10-01;after", "2023-09-01;before"],
                "2023-09-01,2023-10-01",
                id="existing-bound-swapping",
            ),
        ],
    )
    def test_range_conversion(self, converter, field, values, expected):
        # Both date fields must emit chronological ISO bounds for every supported range format.
        assert converter.convert({field: values}) == {
            f"{field}__range": expected
        }

    def test_does_not_mutate_input(self, converter):
        # Converting a range must leave the caller's legacy filter dictionary and list unchanged.
        legacy = {
            "target_date": ["9/1/2023;after", "10/1/2023;before"]
        }
        original = deepcopy(legacy)

        converter.convert(legacy)

        assert legacy == original


@pytest.mark.unit
class TestLegacyConverterRegressions:
    @pytest.mark.parametrize(
        "value",
        ["2023-09-01", ["2023-09-01"]],
    )
    def test_single_exact_date_is_preserved(self, converter, value):
        # Scalar and single-item list dates must retain the existing exact-date lookup.
        assert converter.convert({"target_date": value}) == {
            "target_date__exact": "2023-09-01"
        }

    def test_invalid_date_is_skipped_in_non_strict_mode(self, converter):
        # An invalid bound must skip the incomplete range without raising in non-strict mode.
        assert converter.convert({
            "target_date": ["not-a-date;after", "2023-10-01;before"]
        }) == {}

    def test_invalid_date_raises_in_strict_mode(self, converter):
        # Strict mode must report an invalid date instead of silently discarding the range.
        with pytest.raises(ValueError, match="Invalid date format"):
            converter.convert(
                {
                    "target_date": [
                        "not-a-date;after",
                        "2023-10-01;before",
                    ]
                },
                strict=True,
            )

    @pytest.mark.parametrize(
        "values",
        [
            ["1_weeks;after;fromnow"],
            ["2023-09-01;after"],
            ["2023-09-01;unsupported"],
            [
                "2023-09-01;after",
                "2023-10-01;before",
                "2023-11-01;before",
            ],
        ],
    )
    def test_unsupported_patterns_remain_skipped(self, converter, values):
        # Relative dates, incomplete ranges, unsupported directions, and extra bounds remain skipped.
        assert converter.convert({"target_date": values}) == {}

    def test_unrelated_filters_are_preserved(self, converter):
        # Date conversion changes must preserve UUID mappings, priority lookups, and AND grouping.
        state_id = "11111111-1111-4111-8111-111111111111"

        assert converter.convert({
            "state": [state_id],
            "priority": ["high"],
        }) == {
            "and": [
                {"state_id__in": state_id},
                {"priority__in": "high"},
            ]
        }

    def test_date_combines_with_other_filters(self, converter):
        # A normalized date range must remain AND-combined with the existing priority filter.
        assert converter.convert({
            "target_date": ["9/1/2023;after", "10/1/2023;before"],
            "priority": ["high"],
        }) == {
            "and": [
                {"target_date__range": "2023-09-01,2023-10-01"},
                {"priority__in": "high"},
            ]
        }
