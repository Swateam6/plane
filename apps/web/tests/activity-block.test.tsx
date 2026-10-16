import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { IssueActivityBlockComponent } from "@/components/issues/issue-detail/issue-activity/activity/actions/helpers/activity-block";

const store = vi.hoisted(() => ({ getActivityById: vi.fn(), isMobile: false }));
vi.mock("@/hooks/store/use-issue-detail", () => ({ useIssueDetail: () => ({ activity: store }) }));
vi.mock("@/hooks/use-platform-os", () => ({ usePlatformOS: () => ({ isMobile: store.isMobile }) }));
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => <a href={href}>{children}</a>,
}));
vi.mock("@makeplane/propel/icons", () => ({ HierarchyOutline: () => null }));
vi.mock("@makeplane/propel/components/tooltip", () => ({
  Tooltip: ({ children, label, disabled }: { children: ReactNode; label: string; disabled?: boolean }) => (
    <span title={disabled ? undefined : label}>{children}</span>
  ),
}));
vi.mock("@plane/utils", () => ({
  renderFormattedDate: (value: string) => value.slice(0, 10),
  renderFormattedTime: (value: string) => value.slice(11, 19),
  calculateTimeAgo: (value: string) => `time:${value}`,
}));
vi.mock(
  "@/components/issues/issue-detail/issue-activity/activity/actions",
  async () => import("@/components/issues/issue-detail/issue-activity/activity/actions/helpers/issue-user")
);

const activity = {
  id: "a1",
  actor: "alice",
  actor_detail: { id: "alice", display_name: "Alice" },
  workspace_detail: { slug: "workspace" },
  field: "description",
  verb: "updated",
  created_at: "2026-10-14T10:02:00Z",
};

beforeEach(() => {
  store.isMobile = false;
  store.getActivityById.mockReset();
  store.getActivityById.mockReturnValue(activity);
});

describe("IssueActivityBlockComponent regression", () => {
  it("preserves the contributor link and action in a standalone row", () => {
    render(
      <IssueActivityBlockComponent activityId="a1" ends={undefined}>
        updated the description
      </IssueActivityBlockComponent>
    );
    expect(screen.getByRole("link", { name: "Alice" }).getAttribute("href")).toBe("/workspace/profile/alice");
    expect(screen.getByText(/updated the description/)).toBeTruthy();
  });

  it("retains each row's timestamp and full-date tooltip", () => {
    store.getActivityById.mockImplementation((id: string) => ({
      ...activity,
      id,
      created_at: id === "a1" ? activity.created_at : "2026-10-14T10:05:00Z",
    }));
    render(
      <>
        <IssueActivityBlockComponent activityId="a1" ends="top">
          first action
        </IssueActivityBlockComponent>
        <IssueActivityBlockComponent activityId="a2" ends="bottom">
          second action
        </IssueActivityBlockComponent>
      </>
    );
    expect(screen.getByText("time:2026-10-14T10:02:00Z")).toBeTruthy();
    expect(screen.getByText("time:2026-10-14T10:05:00Z")).toBeTruthy();
    expect(screen.getByTitle("2026-10-14, 10:02:00")).toBeTruthy();
    expect(screen.getByTitle("2026-10-14, 10:05:00")).toBeTruthy();
  });

  it("retains custom contributor names", () => {
    render(
      <IssueActivityBlockComponent activityId="a1" ends={undefined} customUserName="Integration Bot">
        updated the description
      </IssueActivityBlockComponent>
    );
    expect(screen.getByText("Integration Bot")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Alice" })).toBeNull();
  });

  it("preserves contributor attribution for work item creation", () => {
    store.getActivityById.mockReturnValue({ ...activity, field: null, verb: "created" });
    render(
      <IssueActivityBlockComponent activityId="a1" ends="top">
        created the work item
      </IssueActivityBlockComponent>
    );
    expect(screen.getByRole("link", { name: "Alice" })).toBeTruthy();
    expect(screen.getByText(/created the work item/)).toBeTruthy();
  });

  it("keeps timestamps on mobile while disabling the hover tooltip", () => {
    store.isMobile = true;
    render(
      <IssueActivityBlockComponent activityId="a1" ends={undefined}>
        updated the description
      </IssueActivityBlockComponent>
    );
    expect(screen.getByText(`time:${activity.created_at}`)).toBeTruthy();
    expect(screen.queryByTitle("2026-10-14, 10:02:00")).toBeNull();
  });

  it("renders nothing when the activity no longer exists", () => {
    store.getActivityById.mockReturnValue(undefined);
    const { container } = render(
      <IssueActivityBlockComponent activityId="missing" ends={undefined}>
        missing action
      </IssueActivityBlockComponent>
    );
    expect(container.childElementCount).toBe(0);
  });
});
