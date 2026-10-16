import type { ComponentProps, ReactNode } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { observable, runInAction } from "mobx";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defaultActivityFilters, EActivityFilterType, E_SORT_ORDER } from "@plane/constants";
import type { TIssueActivityComment } from "@plane/types";
import { IssueActivityCommentRoot } from "@/components/issues/issue-detail/issue-activity/activity-comment-root";
import { IssueActivityBlockComponent } from "@/components/issues/issue-detail/issue-activity/activity/actions/helpers/activity-block";

type ActivityFixture = {
  id: string;
  actor: string;
  actor_detail: { id: string; display_name: string };
  workspace_detail: { slug: string };
  field: string;
  verb: string;
  new_value: string;
  created_at: string;
};
const store = vi.hoisted(() => ({
  getActivityAndCommentsByIssueId: vi.fn(),
  getActivityById: vi.fn(),
  getCommentById: vi.fn(),
}));
vi.mock("@plane/i18n", () => ({
  useTranslation: () => ({
    t: (_key: string, params: { name: string; count: number }) => `${params.name} made ${params.count} changes`,
  }),
}));
vi.mock("@/hooks/store/use-issue-detail", () => ({
  useIssueDetail: () => ({ activity: store, comment: { getCommentById: store.getCommentById } }),
}));
vi.mock("@/hooks/use-platform-os", () => ({ usePlatformOS: () => ({ isMobile: false }) }));
vi.mock("@/components/relations", () => ({ useTimeLineRelationOptions: () => ({}) }));
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => <a href={href}>{children}</a>,
}));
vi.mock("@makeplane/propel/icons", () => ({
  HierarchyOutline: () => null,
  TextOutline: () => null,
  AlignLeftOutline: () => null,
}));
vi.mock("@makeplane/propel/components/tooltip", () => ({
  Tooltip: ({ children, label }: { children: ReactNode; label: string }) => <span title={label}>{children}</span>,
}));
vi.mock("@plane/utils", () => ({
  getValidKeysFromObject: (value: object) => Object.keys(value),
  renderFormattedDate: (value: string) => value.slice(0, 10),
  renderFormattedTime: (value: string) => value.slice(11, 19),
  calculateTimeAgo: (value: string) => `time:${value}`,
}));
vi.mock("@/components/issues/issue-detail/issue-activity/loader", () => ({
  IssueActivityLoader: () => <div role="status">Loading activity</div>,
}));
vi.mock("@/components/comments/card/root", () => ({
  CommentCard: ({
    comment,
    disabled,
    showCopyLinkOption,
    enableReplies,
  }: {
    comment: { id: string };
    disabled?: boolean;
    showCopyLinkOption: boolean;
    enableReplies: boolean;
  }) => (
    <article
      aria-label={`Comment ${comment.id}`}
      data-disabled={disabled}
      data-copy-link={showCopyLinkOption}
      data-replies={enableReplies}
    >
      Comment body
    </article>
  ),
}));
// Exercise the real timeline, dispatcher, and shared block. Simplified action
// bodies isolate grouping from unrelated action-specific dependencies.
vi.mock("@/components/issues/issue-detail/issue-activity/activity/actions", async () => {
  const user = await import("@/components/issues/issue-detail/issue-activity/activity/actions/helpers/issue-user");
  type ActionProps = { activityId: string; ends: "top" | "bottom" | undefined };
  return {
    ...user,
    IssueDescriptionActivity: ({ activityId, ends }: ActionProps) => (
      <IssueActivityBlockComponent activityId={activityId} ends={ends}>
        updated the description
      </IssueActivityBlockComponent>
    ),
    IssueNameActivity: ({ activityId, ends }: ActionProps) => (
      <IssueActivityBlockComponent activityId={activityId} ends={ends}>
        set the name to {activityId}
      </IssueActivityBlockComponent>
    ),
  };
});

const activities: Record<string, ActivityFixture> = {};
const timeline = observable.box<TIssueActivityComment[] | undefined>([], { deep: false });
const props: ComponentProps<typeof IssueActivityCommentRoot> = {
  workspaceSlug: "workspace",
  projectId: "project",
  issueId: "issue",
  isIntakeIssue: false,
  selectedFilters: defaultActivityFilters,
  sortOrder: E_SORT_ORDER.ASC,
  // CommentCard is stubbed: this suite checks rendering/permissions, not operations.
  activityOperations: {} as ComponentProps<typeof IssueActivityCommentRoot>["activityOperations"],
};
function update(
  id: string,
  actor = "Alice",
  field = "description",
  activityType: TIssueActivityComment["activity_type"] = "ACTIVITY"
): TIssueActivityComment {
  const createdAt = `2026-10-14T10:${String(Object.keys(activities).length).padStart(2, "0")}:00Z`;
  activities[id] = {
    id,
    actor,
    actor_detail: { id: actor, display_name: actor },
    workspace_detail: { slug: "workspace" },
    field,
    verb: "updated",
    new_value: id,
    created_at: createdAt,
  };
  return { id, activity_type: activityType, created_at: createdAt };
}
function setTimeline(entries: TIssueActivityComment[] | undefined) {
  runInAction(() => timeline.set(entries));
}
function visibleContributorCount(name: string) {
  // Permit screen-reader-only attribution on continuation rows.
  return screen
    .queryAllByText(name, { exact: true })
    .filter((node) => !node.closest(".sr-only, [hidden], [aria-hidden='true']")).length;
}

beforeEach(() => {
  vi.clearAllMocks();
  for (const key of Object.keys(activities)) delete activities[key];
  setTimeline([]);
  store.getActivityById.mockImplementation((id: string) => activities[id]);
  store.getCommentById.mockImplementation((id: string) => ({ id }));
  store.getActivityAndCommentsByIssueId.mockImplementation((_id: string, order: E_SORT_ORDER) => {
    const entries = timeline.get();
    // The project's TypeScript library predates toReversed; reverse only a copy.
    // oxlint-disable-next-line unicorn/no-array-reverse
    return order === E_SORT_ORDER.DESC ? entries?.slice().reverse() : entries;
  });
});

describe("IssueActivityCommentRoot", () => {
  it("renders a loading state before entries arrive", () => {
    setTimeline(undefined);
    render(<IssueActivityCommentRoot {...props} />);
    expect(screen.getByRole("status").textContent).toBe("Loading activity");
  });

  it("renders no rows for an empty timeline", () => {
    const { container } = render(<IssueActivityCommentRoot {...props} />);
    expect(container.childElementCount).toBe(0);
  });

  it("starts groups collapsed and expands every original action and timestamp", async () => {
    setTimeline([update("a1"), update("a2", "Alice", "name"), update("a3")]);
    render(<IssueActivityCommentRoot {...props} />);
    const trigger = screen.getByRole("button", { name: /Alice made 3 changes/ });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText(/updated the description/)).toBeNull();
    expect(screen.queryByText(/set the name to a2/)).toBeNull();
    expect(within(trigger).getByText(`time:${activities.a3.created_at}`)).toBeTruthy();

    fireEvent.click(trigger);
    const details = await screen.findByRole("region", { name: "Alice made 3 changes" });
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(within(details).queryByRole("link", { name: "Alice" })).toBeNull();
    const contributorNames = within(details).getAllByText("Alice", { exact: true });
    expect(contributorNames).toHaveLength(3);
    for (const name of contributorNames) {
      expect(name.closest(".sr-only")).not.toBeNull();
    }
    for (const activity of Object.values(activities)) {
      expect(within(details).getByText(`time:${activity.created_at}`)).toBeTruthy();
    }
    expect(within(details).getAllByText(/updated the description/)).toHaveLength(2);
    expect(within(details).getByText(/set the name to a2/)).toBeTruthy();

    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    await waitFor(() => expect(screen.queryByRole("region", { name: "Alice made 3 changes" })).toBeNull());
  });

  it("repeats the contributor after a different user's update", () => {
    setTimeline([update("a1"), update("b1", "Bob"), update("a2")]);
    render(<IssueActivityCommentRoot {...props} />);
    expect(visibleContributorCount("Alice")).toBe(2);
    expect(visibleContributorCount("Bob")).toBe(1);
  });

  it("keeps comments separate and preserves intake/disabled flags", () => {
    setTimeline([update("a1"), { id: "c1", activity_type: "COMMENT" }, update("a2")]);
    render(<IssueActivityCommentRoot {...props} disabled isIntakeIssue />);
    expect(visibleContributorCount("Alice")).toBe(2);
    const card = screen.getByRole("article", { name: "Comment c1" });
    expect(card.getAttribute("data-disabled")).toBe("true");
    expect(card.getAttribute("data-copy-link")).toBe("false");
    expect(card.getAttribute("data-replies")).toBe("true");
  });

  it("recalculates grouping when a comment is filtered out", () => {
    setTimeline([update("a1"), { id: "c1", activity_type: "COMMENT" }, update("a2")]);
    const { rerender } = render(<IssueActivityCommentRoot {...props} />);
    expect(visibleContributorCount("Alice")).toBe(2);
    rerender(<IssueActivityCommentRoot {...props} selectedFilters={[EActivityFilterType.ACTIVITY]} />);
    expect(screen.queryByRole("article")).toBeNull();
    const trigger = screen.getByRole("button", { name: /Alice made 2 changes/ });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText(/updated the description/)).toBeNull();
  });

  it("retains the first visible contributor after filtering updates", () => {
    setTimeline([update("a1"), update("a2", "Alice", "name", "STATE")]);
    render(<IssueActivityCommentRoot {...props} selectedFilters={[EActivityFilterType.STATE]} />);
    expect(visibleContributorCount("Alice")).toBe(1);
    expect(screen.queryByText(/updated the description/)).toBeNull();
    expect(screen.getByText(/set the name to a2/)).toBeTruthy();
  });

  it("keeps descending order and the newest summary timestamp after sorting", async () => {
    setTimeline([update("b1", "Bob"), update("a1"), update("a2")]);
    const { rerender } = render(<IssueActivityCommentRoot {...props} />);
    rerender(<IssueActivityCommentRoot {...props} sortOrder={E_SORT_ORDER.DESC} />);
    const trigger = screen.getByRole("button", { name: /Alice made 2 changes/ });
    expect(within(trigger).getByText(`time:${activities.a2.created_at}`)).toBeTruthy();
    fireEvent.click(trigger);
    const details = await screen.findByRole("region", { name: "Alice made 2 changes" });
    expect(
      within(details)
        .getAllByText(/^time:/)
        .map((node) => node.textContent?.trim())
    ).toEqual(["a2", "a1"].map((id) => `time:${activities[id].created_at}`));
    expect(visibleContributorCount("Bob")).toBe(1);
    expect(screen.getByText(`time:${activities.b1.created_at}`)).toBeTruthy();
  });

  it("turns a single row into a collapsed group when observable updates arrive", async () => {
    setTimeline([update("a1")]);
    render(<IssueActivityCommentRoot {...props} />);
    expect(visibleContributorCount("Alice")).toBe(1);
    expect(screen.queryByRole("button", { name: /made .* changes/ })).toBeNull();
    act(() => setTimeline([timeline.get()![0], update("a2")]));
    const trigger = screen.getByRole("button", { name: /Alice made 2 changes/ });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText(/updated the description/)).toBeNull();
    fireEvent.click(trigger);
    const details = await screen.findByRole("region", { name: "Alice made 2 changes" });
    expect(within(details).getAllByText(/^time:/)).toHaveLength(2);
  });

  it("keeps groups on either side of a comment independently expandable", async () => {
    setTimeline([
      update("a1"),
      update("a2"),
      { id: "c1", activity_type: "COMMENT" },
      update("b1", "Bob"),
      update("b2", "Bob"),
    ]);
    render(<IssueActivityCommentRoot {...props} />);
    const aliceTrigger = screen.getByRole("button", { name: /Alice made 2 changes/ });
    const bobTrigger = screen.getByRole("button", { name: /Bob made 2 changes/ });
    fireEvent.click(aliceTrigger);
    expect(await screen.findByRole("region", { name: "Alice made 2 changes" })).toBeTruthy();
    expect(bobTrigger.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("region", { name: "Bob made 2 changes" })).toBeNull();
    expect(screen.getByRole("article", { name: "Comment c1" })).toBeTruthy();
  });
});
