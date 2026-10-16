/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane imports
import type { TActivityFilters, EActivityFilterType } from "@plane/constants";
import { BASE_ACTIVITY_FILTER_TYPES, E_SORT_ORDER, filterActivityOnSelectedFilters } from "@plane/constants";
import type { TCommentsOperations } from "@plane/types";
import { useTranslation } from "@plane/i18n";
// components
import { CommentCard } from "@/components/comments/card/root";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
// local imports
import { IssueActivityItem } from "./activity/activity-list";
import { IssueActivityLoader } from "./loader";
import { groupActivityRuns } from "./activity-grouping";
import { ActivityGroupSummary } from "./activity-group-summary";
import { ActivityGroupingContext } from "./activity-grouping-context";

type TIssueActivityCommentRoot = {
  workspaceSlug: string;
  projectId: string;
  isIntakeIssue: boolean;
  issueId: string;
  selectedFilters: TActivityFilters[];
  activityOperations: TCommentsOperations;
  showAccessSpecifier?: boolean;
  disabled?: boolean;
  sortOrder: E_SORT_ORDER;
};

export const IssueActivityCommentRoot = observer(function IssueActivityCommentRoot(props: TIssueActivityCommentRoot) {
  const {
    workspaceSlug,
    isIntakeIssue,
    issueId,
    selectedFilters,
    activityOperations,
    showAccessSpecifier,
    projectId,
    disabled,
    sortOrder,
  } = props;
  const { t } = useTranslation();
  // store hooks
  const {
    activity: { getActivityAndCommentsByIssueId, getActivityById },
    comment: { getCommentById },
  } = useIssueDetail();
  // derived values
  const activityAndComments = getActivityAndCommentsByIssueId(issueId, sortOrder);

  if (!activityAndComments) return <IssueActivityLoader />;

  if (activityAndComments.length <= 0) return null;

  const filteredActivityAndComments = filterActivityOnSelectedFilters(activityAndComments, selectedFilters);

  const groups = groupActivityRuns(filteredActivityAndComments, getActivityById);

  return (
    <div>
      {groups.map(function (group, groupIndex) {
        const firstEntry = group.entries[0];
        if (!firstEntry) return null;

        const ends = groupIndex === 0 ? "top" : groupIndex === groups.length - 1 ? "bottom" : undefined;

        if (firstEntry.activity_type === "COMMENT") {
          return (
            <CommentCard
              key={firstEntry.id}
              workspaceSlug={workspaceSlug}
              entityId={issueId}
              comment={getCommentById(firstEntry.id)}
              activityOperations={activityOperations}
              ends={ends}
              showAccessSpecifier={!!showAccessSpecifier}
              showCopyLinkOption={!isIntakeIssue}
              disabled={disabled}
              projectId={projectId}
              enableReplies
            />
          );
        }

        if (!BASE_ACTIVITY_FILTER_TYPES.includes(firstEntry.activity_type as EActivityFilterType)) return null;

        if (group.entries.length === 1) {
          return <IssueActivityItem key={firstEntry.id} activityId={firstEntry.id} ends={ends} />;
        }

        const firstActivity = getActivityById(firstEntry.id);
        const latestEntry = sortOrder === E_SORT_ORDER.ASC ? group.entries[group.entries.length - 1] : firstEntry;
        const latestActivity = latestEntry ? getActivityById(latestEntry.id) : undefined;
        if (!firstActivity || !latestActivity) return null;

        return (
          <ActivityGroupSummary
            key={firstEntry.id}
            label={t("issue.activity.multiple_changes", {
              name: firstActivity.actor_detail?.display_name,
              count: group.entries.length,
            })}
            latestCreatedAt={latestActivity.created_at}
          >
            {group.entries.map(function (entry, index) {
              return (
                <ActivityGroupingContext.Provider key={entry.id} value={true}>
                  <IssueActivityItem
                    activityId={entry.id}
                    ends={index === 0 ? "top" : index === group.entries.length - 1 ? "bottom" : undefined}
                  />
                </ActivityGroupingContext.Provider>
              );
            })}
          </ActivityGroupSummary>
        );
      })}
    </div>
  );
});
