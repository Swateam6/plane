import type { TIssueActivity, TIssueActivityComment } from "@plane/types";

// Grabs only contributor info.
type ActivityIdentity = Pick<TIssueActivity, "actor" | "actor_detail">;

// Checks if entry is continued from the prior one
type GroupedActivityEntry = {
  entry: TIssueActivityComment;
  isContinuation: boolean;
};

const groupableTypes = new Set<string>(["ACTIVITY", "STATE", "ASSIGNEE", "DEFAULT"]);

export function groupActivityEntries(
  entries: readonly TIssueActivityComment[],
  getActivityById: {
    (id: string): ActivityIdentity | undefined;
  }
): GroupedActivityEntry[] {
  let previousActorId: string | undefined;
  // Builds new ordered array.
  return entries.map(function (entry) {
    if (!groupableTypes.has(entry.activity_type)) {
      previousActorId = undefined;
      return { entry, isContinuation: false };
    }

    const actorId = getActivityById(entry.id)?.actor || undefined;

    const isContinuation = actorId !== undefined && actorId === previousActorId;

    previousActorId = actorId;

    return { entry, isContinuation };
  });
}

export type ActivityGroup = {
  entries: TIssueActivityComment[];
};

export function groupActivityRuns(
  entries: readonly TIssueActivityComment[],
  getActivityById: {
    (id: string): ActivityIdentity | undefined;
  }
): ActivityGroup[] {
  const annotatedEntries = groupActivityEntries(entries, getActivityById);
  const groups: ActivityGroup[] = [];

  for (const item of annotatedEntries) {
    const previousGroup = groups[groups.length - 1];

    if (item.isContinuation && previousGroup) {
      previousGroup.entries.push(item.entry);
    } else {
      groups.push({ entries: [item.entry] });
    }
  }

  return groups;
}
