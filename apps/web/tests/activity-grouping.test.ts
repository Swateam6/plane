import { beforeAll, describe, expect, it } from "vitest";
import type { TIssueActivity, TIssueActivityComment } from "@plane/types";

type Identity = Pick<TIssueActivity, "actor" | "actor_detail">;
type GroupActivityEntries = (
  entries: readonly TIssueActivityComment[],
  getActivityById: (id: string) => Identity | undefined
) => { entry: TIssueActivityComment; isContinuation: boolean }[];

let groupActivityEntries: GroupActivityEntries;

beforeAll(async () => {
  // Dynamic import keeps the test setup type-checkable before the helper exists.
  // A missing helper is deliberately a failure, never a skipped or passing test.
  const helperPath = new URL("../components/issues/issue-detail/issue-activity/activity-grouping.ts", import.meta.url)
    .href;
  const helper = await import(/* @vite-ignore */ helperPath);
  expect(helper.groupActivityEntries).toBeTypeOf("function");
  groupActivityEntries = helper.groupActivityEntries;
});

function identity(id: string, displayName = id): Identity {
  return {
    actor: id,
    actor_detail: {
      id,
      display_name: displayName,
      first_name: displayName,
      last_name: "",
      avatar_url: "",
      is_bot: false,
    },
  };
}

function entry(
  id: string,
  activityType: TIssueActivityComment["activity_type"] = "ACTIVITY",
  createdAt = "2026-10-14T10:00:00Z"
): TIssueActivityComment {
  return { id, activity_type: activityType, created_at: createdAt };
}

const alice = identity("alice");
const bob = identity("bob");
const lookup = (records: Record<string, Identity | undefined>) => (id: string) => records[id];
const flags = (rows: ReturnType<GroupActivityEntries>) => rows.map((row) => row.isContinuation);

describe("groupActivityEntries", () => {
  it("handles an empty timeline", () => {
    expect(groupActivityEntries([], lookup({}))).toEqual([]);
  });

  it("starts a group for a single update", () => {
    const first = entry("a1");
    expect(groupActivityEntries([first], lookup({ a1: alice }))).toEqual([{ entry: first, isContinuation: false }]);
  });

  it("groups consecutive updates by the same contributor", () => {
    expect(
      flags(groupActivityEntries([entry("a1"), entry("a2"), entry("a3")], lookup({ a1: alice, a2: alice, a3: alice })))
    ).toEqual([false, true, true]);
  });

  it("restarts when another contributor interrupts", () => {
    expect(
      flags(groupActivityEntries([entry("a1"), entry("b1"), entry("a2")], lookup({ a1: alice, b1: bob, a2: alice })))
    ).toEqual([false, false, false]);
  });

  it("breaks groups at comments and keeps comments separate", () => {
    const entries = [entry("a1"), entry("c1", "COMMENT"), entry("c2", "COMMENT"), entry("a2")];
    expect(flags(groupActivityEntries(entries, lookup({ a1: alice, a2: alice })))).toEqual([
      false,
      false,
      false,
      false,
    ]);
  });

  it("compares actor IDs rather than display names", () => {
    expect(
      flags(
        groupActivityEntries(
          [entry("a1"), entry("b1")],
          lookup({ a1: identity("alice", "Alex"), b1: identity("bob", "Alex") })
        )
      )
    ).toEqual([false, false]);
  });

  it("allows different update categories in the same group", () => {
    expect(
      flags(
        groupActivityEntries(
          [entry("a1"), entry("a2", "STATE"), entry("a3", "ASSIGNEE")],
          lookup({ a1: alice, a2: alice, a3: alice })
        )
      )
    ).toEqual([false, true, true]);
  });

  it("breaks groups at unresolved activities", () => {
    expect(
      flags(groupActivityEntries([entry("a1"), entry("missing"), entry("a2")], lookup({ a1: alice, a2: alice })))
    ).toEqual([false, false, false]);
  });

  it("does not group unknown contributors", () => {
    expect(
      flags(
        groupActivityEntries(
          [entry("u1"), entry("u2"), entry("a1")],
          lookup({ u1: identity(""), u2: identity(""), a1: alice })
        )
      )
    ).toEqual([false, false, false]);
  });

  it("preserves descending display order and individual timestamps", () => {
    const entries = [
      entry("a2", "ACTIVITY", "2026-10-14T12:00:00Z"),
      entry("a1", "ACTIVITY", "2026-10-14T11:00:00Z"),
      entry("b1", "ACTIVITY", "2026-10-14T10:00:00Z"),
    ];
    const result = groupActivityEntries(entries, lookup({ a1: alice, a2: alice, b1: bob }));
    expect(result.map((row) => row.entry)).toEqual(entries);
    expect(flags(result)).toEqual([false, true, false]);
  });

  it("restarts the first visible entry after filtering", () => {
    const first = entry("a1");
    const second = entry("a2", "STATE");
    const getActivity = lookup({ a1: alice, a2: alice });
    expect(flags(groupActivityEntries([first, second], getActivity))).toEqual([false, true]);
    expect(flags(groupActivityEntries([second], getActivity))).toEqual([false]);
  });

  it("groups entries that become adjacent after filtering", () => {
    const first = entry("a1");
    const second = entry("a2");
    const getActivity = lookup({ a1: alice, a2: alice });
    expect(flags(groupActivityEntries([first, entry("c1", "COMMENT"), second], getActivity))).toEqual([
      false,
      false,
      false,
    ]);
    expect(flags(groupActivityEntries([first, second], getActivity))).toEqual([false, true]);
  });

  it("preserves all entries without mutating frozen input", () => {
    const entries = [entry("a1"), entry("a2"), entry("c1", "COMMENT")];
    const before = structuredClone(entries);
    entries.forEach((item) => Object.freeze(item));
    Object.freeze(entries);
    const result = groupActivityEntries(entries, lookup({ a1: alice, a2: alice }));
    expect(result.map((row) => row.entry)).toEqual(before);
    expect(entries).toEqual(before);
  });
});
