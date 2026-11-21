# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import json


# Third Party imports
from celery import shared_task

# Django imports
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone


# Module imports
from plane.app.serializers import IssueActivitySerializer
from plane.bgtasks.notification_task import notifications
from plane.db.models import (
    CommentReaction,
    Cycle,
    Issue,
    IssueActivity,
    IssueComment,
    IssueReaction,
    IssueSubscriber,
    Label,
    Module,
    Project,
    State,
    User,
    EstimatePoint,
)
from plane.settings.redis import redis_instance
from plane.utils.exception_logger import log_exception
from plane.utils.issue_relation_mapper import get_inverse_relation
from plane.utils.uuid import is_valid_uuid
from dataclasses import dataclass, field

def extract_ids(data: dict | None, primary_key: str, fallback_key: str) -> set[str]:
    if not data:
        return set()
    if primary_key in data:
        return {str(x) for x in data.get(primary_key, [])}
    return {str(x) for x in data.get(fallback_key, [])}


@dataclass
class ActivityContext:
    issue_id: str
    project_id: str
    workspace_id: str
    actor_id: str
    epoch: int
    requested_data: dict | None = None
    current_instance: dict | None = None
    issue_activities: list = field(default_factory=list)

    def record(self, *, issue_id=None, actor_id=None, **kwargs):
        """Append an IssueActivity with the common fields pre-filled."""
        self.issue_activities.append(
            IssueActivity(
                issue_id=self.issue_id if issue_id is None else issue_id,
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                actor_id=self.actor_id if actor_id is None else actor_id,
                epoch=self.epoch,
                **kwargs,
            )
        )

def _valid_uuid(value):
    """Return value if it is a valid UUID (or None), else None."""
    if value is None or is_valid_uuid(value):
        return value
    return None
# Track Changes in name
def track_name(ctx: ActivityContext):
    cur, req = ctx.current_instance, ctx.requested_data
    if cur.get("name") != req.get("name"):
        ctx.record(
            verb="updated",
            old_value=cur.get("name"),
            new_value=req.get("name"),
            field="name",
            comment="updated the name to",
        )

# Track issue description
def track_description(ctx: ActivityContext):
    if ctx.current_instance.get("description_html") != ctx.requested_data.get("description_html"):
        last_activity = (
            IssueActivity.objects.filter(issue_id=ctx.issue_id)
            .order_by("-created_at")
            .first()
        )
        if (
            last_activity is not None
            and last_activity.field == "description"
            and ctx.actor_id == str(last_activity.actor_id)
        ):
            last_activity.created_at = timezone.now()
            last_activity.save(update_fields=["created_at"])
        else:
            ctx.record(
                verb="updated",
                old_value=ctx.current_instance.get("description_html"),
                new_value=ctx.requested_data.get("description_html"),
                field="description",
                comment="updated the description to",
            )


# Track changes in parent issue

def track_parent(ctx: ActivityContext):
    current_parent_id = ctx.current_instance.get("parent_id") or ctx.current_instance.get("parent")
    requested_parent_id = ctx.requested_data.get("parent_id") or ctx.requested_data.get("parent")

    # Invalid (non-null) UUIDs abort the entire activity, matching the original
    # behavior; contrast with track_state which nulls them out.
    if current_parent_id is not None and not is_valid_uuid(current_parent_id):
        return
    if requested_parent_id is not None and not is_valid_uuid(requested_parent_id):
        return

    if current_parent_id == requested_parent_id:
        return

    old_parent = (
        Issue.objects.filter(pk=current_parent_id, project_id=ctx.project_id).first()
        if current_parent_id is not None
        else None
    )
    new_parent = (
        Issue.objects.filter(pk=requested_parent_id, project_id=ctx.project_id).first()
        if requested_parent_id is not None
        else None
    )
    if requested_parent_id is not None and new_parent is None:
        return

    ctx.record(
        verb="updated",
        old_value=(
            f"{old_parent.project.identifier}-{old_parent.sequence_id}"
            if old_parent is not None
            else ""
        ),
        new_value=(
            f"{new_parent.project.identifier}-{new_parent.sequence_id}"
            if new_parent is not None
            else ""
        ),
        field="parent",
        comment="updated the parent issue to",
        old_identifier=old_parent.id if old_parent is not None else None,
        new_identifier=new_parent.id if new_parent is not None else None,
    )


# Track changes in priority
def track_priority(ctx: ActivityContext):
    if ctx.current_instance.get("priority") != ctx.requested_data.get("priority"):
        ctx.record(
            verb="updated",
            old_value=ctx.current_instance.get("priority"),
            new_value=ctx.requested_data.get("priority"),
            field="priority",
            comment="updated the priority to",
        )


# Track changes in state of the issue
def track_state(ctx: ActivityContext):
    current_state_id = _valid_uuid_or_none(
        ctx.current_instance.get("state_id") or ctx.current_instance.get("state")
    )
    requested_state_id = _valid_uuid_or_none(
        ctx.requested_data.get("state_id") or ctx.requested_data.get("state")
    )

    if current_state_id == requested_state_id:
        return

    new_state = State.objects.filter(pk=requested_state_id, project_id=ctx.project_id).first()
    old_state = State.objects.filter(pk=current_state_id, project_id=ctx.project_id).first()

    ctx.record(
        verb="updated",
        old_value=old_state.name if old_state else None,
        new_value=new_state.name if new_state else None,
        field="state",
        comment="updated the state to",
        old_identifier=old_state.id if old_state else None,
        new_identifier=new_state.id if new_state else None,
    )


# Track changes in issue target date
def track_target_date(ctx: ActivityContext):
    if ctx.current_instance.get("target_date") != ctx.requested_data.get("target_date"):
        ctx.record(
            verb="updated",
            old_value=(
                ctx.current_instance.get("target_date")
                if ctx.current_instance.get("target_date") is not None
                else ""
            ),
            new_value=(
                ctx.requested_data.get("target_date")
                if ctx.requested_data.get("target_date") is not None
                else ""
            ),
            field="target_date",
            comment="updated the target date to",
        )


# Track changes in issue start date
def track_start_date(ctx: ActivityContext):
    if ctx.current_instance.get("start_date") != ctx.requested_data.get("start_date"):
        ctx.record(
            verb="updated",
            old_value=(
                ctx.current_instance.get("start_date")
                if ctx.current_instance.get("start_date") is not None
                else ""
            ),
            new_value=(
                ctx.requested_data.get("start_date")
                if ctx.requested_data.get("start_date") is not None
                else ""
            ),
            field="start_date",
            comment="updated the start date to ",
        )


# Track changes in issue labels
def track_labels(ctx: ActivityContext):
    requested_labels = extract_ids(ctx.requested_data, "label_ids", "labels")
    current_labels = extract_ids(ctx.current_instance, "label_ids", "labels")

    added_labels = requested_labels - current_labels
    dropped_labels = current_labels - requested_labels


    # Track added labels
    for added_label in added_labels:
        if not is_valid_uuid(added_label):
            continue
        label = Label.objects.filter(pk=added_label, project_id=ctx.project_id).first()
        if label is None:
            continue
        ctx.record(
            verb="updated",
            field="labels",
            comment="added label ",
            old_value="",
            new_value=label.name,
            new_identifier=label.id,
            old_identifier=None,
        )

    # Track removed labels
    for dropped_label in dropped_labels:
        if not is_valid_uuid(dropped_label):
            continue
        label = Label.objects.filter(pk=dropped_label, project_id=ctx.project_id).first()
        if label is None:
            continue
        ctx.record(
            verb="updated",
            old_value=label.name,
            new_value="",
            field="labels",
            comment="removed label ",
            old_identifier=label.id,
            new_identifier=None,
        )

# Track changes in issue assignees
def track_assignees(ctx: ActivityContext):
    requested_assignees = extract_ids(ctx.requested_data, "assignee_ids", "assignees")
    current_assignees = extract_ids(ctx.current_instance, "assignee_ids", "assignees")

    added_assignees = requested_assignees - current_assignees
    dropped_assignees = current_assignees - requested_assignees

    bulk_subscribers = []
    for added_assignee in added_assignees:
        if not is_valid_uuid(added_assignee):
            continue

        # Same rule as IssueCreateSerializer: active project members with role >= MEMBER
        assignee = User.objects.filter(
            pk=added_assignee,
            member_project__project_id=ctx.project_id,
            member_project__role__gte=15,
            member_project__is_active=True,
            member_project__deleted_at__isnull=True,
        ).first()
        if assignee is None:
            continue
        ctx.record(
            verb="updated",
            old_value="",
            new_value=assignee.display_name,
            field="assignees",
            comment="added assignee ",
            new_identifier=assignee.id,
        )
        bulk_subscribers.append(
            IssueSubscriber(
                subscriber_id=assignee.id,
                issue_id=ctx.issue_id,
                workspace_id=ctx.workspace_id,
                project_id=ctx.project_id,
                created_by_id=assignee.id,
                updated_by_id=assignee.id,
            )
        )

    # Create assignees subscribers to the issue and ignore if already
    IssueSubscriber.objects.bulk_create(bulk_subscribers, batch_size=10, ignore_conflicts=True)

    for dropped_assignee in dropped_assignees:
        if not is_valid_uuid(dropped_assignee):
            continue

        # Deactivated members can still be unassigned, so is_active is not required here
        assignee = User.objects.filter(
            pk=dropped_assignee,
            member_workspace__workspace_id=ctx.workspace_id,
            member_workspace__deleted_at__isnull=True,
        ).first()
        if assignee is None:
            continue
        ctx.record(
            verb="updated",
            old_value=assignee.display_name,
            new_value="",
            field="assignees",
            comment="removed assignee ",
            old_identifier=assignee.id,
        )

def track_estimate_points(ctx: ActivityContext):
    current_estimate_point = ctx.current_instance.get("estimate_point")
    requested_estimate_point = ctx.requested_data.get("estimate_point")

    if current_estimate_point == requested_estimate_point:
        return

    old_estimate = (
        EstimatePoint.objects.filter(pk=current_estimate_point, project_id=ctx.project_id).first()
        if current_estimate_point is not None
        else None
    )
    new_estimate = (
        EstimatePoint.objects.filter(pk=requested_estimate_point, project_id=ctx.project_id).first()
        if requested_estimate_point is not None
        else None
    )
    if requested_estimate_point is not None and new_estimate is None:
        return

    ctx.record(
        verb="removed" if new_estimate is None else "updated",
        old_identifier=current_estimate_point if current_estimate_point is not None else None,
        new_identifier=requested_estimate_point if requested_estimate_point is not None else None,
        old_value=old_estimate.value if old_estimate else None,
        new_value=new_estimate.value if new_estimate else None,
        field="estimate_" + new_estimate.estimate.type,
        comment="updated the estimate point to ",
    )

def track_archive_at(ctx: ActivityContext):
    if ctx.current_instance.get("archived_at") == ctx.requested_data.get("archived_at"):
        return

    if ctx.requested_data.get("archived_at") is None:
        ctx.record(
            comment="has restored the issue",
            verb="updated",
            field="archived_at",
            old_value="archive",
            new_value="restore",
        )
    else:
        if ctx.requested_data.get("automation"):
            comment = "Plane has archived the issue"
            new_value = "archive"
        else:
            comment = "Actor has archived the issue"
            new_value = "manual_archive"
        ctx.record(
            comment=comment,
            verb="updated",
            field="archived_at",
            old_value=None,
            new_value=new_value,
        )


def track_closed_to(ctx: ActivityContext):
    if ctx.requested_data.get("closed_to") is None:
        return
    updated_state = State.objects.get(pk=ctx.requested_data.get("closed_to"), project_id=ctx.project_id)
    ctx.record(
        verb="updated",
        old_value=None,
        new_value=updated_state.name,
        field="state",
        comment="Plane updated the state to ",
        old_identifier=None,
        new_identifier=updated_state.id,
    )

### Issue Activity Handling ###
def create_issue_activity(ctx: ActivityContext):
    issue = Issue.objects.get(pk=ctx.issue_id)
    # Created directly (rather than via ctx.record) so we can back-date created_at
    # and override actor_id with the original creator.
    issue_activity = IssueActivity.objects.create(
        issue_id=ctx.issue_id,
        project_id=ctx.project_id,
        workspace_id=ctx.workspace_id,
        comment="created the issue",
        verb="created",
        actor_id=ctx.actor_id,
        epoch=ctx.epoch,
    )
    issue_activity.created_at = issue.created_at
    issue_activity.actor_id = issue.created_by_id
    issue_activity.save(update_fields=["created_at", "actor_id"])

    if ctx.requested_data.get("assignee_ids") is not None:
        track_assignees(ctx)


def update_issue_activity(ctx: ActivityContext):
    for key in ctx.requested_data:
        func = ISSUE_ACTIVITY_MAPPER.get(key)
        if func is not None:
            func(ctx)

def delete_issue_activity(ctx: ActivityContext):
    ctx.record(
        comment="deleted the issue",
        verb="deleted",
        field="issue",
    )


def create_comment_activity(ctx: ActivityContext):
    ctx.record(
        comment="created a comment",
        verb="created",
        field="comment",
        new_value=ctx.requested_data.get("comment_html", ""),
        new_identifier=ctx.requested_data.get("id", None),
        issue_comment_id=ctx.requested_data.get("id", None),
    )


def update_comment_activity(ctx: ActivityContext):
    # Only a change to the comment's HTML is recorded; payloads without it (e.g. access only) are not.
    if (
        "comment_html" in ctx.requested_data
        and ctx.current_instance.get("comment_html") != ctx.requested_data["comment_html"]
    ):
        ctx.record(
            comment="updated a comment",
            verb="updated",
            field="comment",
            old_value=ctx.current_instance.get("comment_html", ""),
            old_identifier=ctx.current_instance.get("id"),
            new_value=ctx.requested_data.get("comment_html", ""),
            new_identifier=ctx.current_instance.get("id", None),
            issue_comment_id=ctx.current_instance.get("id", None),
        )

def delete_comment_activity(ctx: ActivityContext):
    ctx.record(
        issue_comment_id=ctx.requested_data.get("comment_id", None),
        comment="deleted the comment",
        verb="deleted",
        field="comment",
    )

def create_cycle_issue_activity(ctx: ActivityContext):
    updated_records = ctx.current_instance.get("updated_cycle_issues", [])
    created_records = json.loads(ctx.current_instance.get("created_cycle_issues", []))

    for updated_record in updated_records:
        old_cycle = Cycle.objects.filter(pk=updated_record.get("old_cycle_id", None), project_id=ctx.project_id).first()
        new_cycle = Cycle.objects.filter(pk=updated_record.get("new_cycle_id", None), project_id=ctx.project_id).first()
        issue = Issue.objects.filter(pk=updated_record.get("issue_id"), project_id=ctx.project_id).first()
        if issue is None:
            continue
        issue.updated_at = timezone.now()
        issue.save(update_fields=["updated_at"])

        ctx.record(
            issue_id=updated_record.get("issue_id"),
            verb="updated",
            old_value=old_cycle.name if old_cycle else "",
            new_value=new_cycle.name if new_cycle else "",
            field="cycles",
            comment=f"""updated cycle from {old_cycle.name if old_cycle else ""}
            to {new_cycle.name if new_cycle else ""}""",
            old_identifier=old_cycle.id if old_cycle else None,
            new_identifier=new_cycle.id if new_cycle else None,
        )

    for created_record in created_records:
        cycle = Cycle.objects.filter(pk=created_record.get("fields").get("cycle"), project_id=ctx.project_id).first()
        issue = Issue.objects.filter(pk=created_record.get("fields").get("issue"), project_id=ctx.project_id).first()
        if cycle is None or issue is None:
            continue
        issue.updated_at = timezone.now()
        issue.save(update_fields=["updated_at"])

        ctx.record(
            issue_id=created_record.get("fields").get("issue"),
            verb="created",
            old_value="",
            new_value=cycle.name,
            field="cycles",
            comment=f"added cycle {cycle.name}",
            new_identifier=cycle.id,
        )


def delete_cycle_issue_activity(ctx: ActivityContext):
    cycle_id = ctx.requested_data.get("cycle_id", "")
    cycle_name = ctx.requested_data.get("cycle_name", "")
    cycle = Cycle.objects.filter(pk=cycle_id, project_id=ctx.project_id).first()
    issues = ctx.requested_data.get("issues")
    for issue_id in issues:
        current_issue = Issue.objects.filter(pk=issue_id, project_id=ctx.project_id).first()
        if current_issue is None:
            continue
        current_issue.updated_at = timezone.now()
        current_issue.save(update_fields=["updated_at"])
        ctx.record(
            issue_id=issue_id,
            verb="deleted",
            old_value=cycle.name if cycle is not None else cycle_name,
            new_value="",
            field="cycles",
            comment=f"removed this issue from {cycle.name if cycle is not None else cycle_name}",
            old_identifier=cycle_id if cycle_id is not None else None,
        )

def create_module_issue_activity(ctx: ActivityContext):
    module = Module.objects.filter(pk=ctx.requested_data.get("module_id"), project_id=ctx.project_id).first()
    issue = Issue.objects.filter(pk=ctx.issue_id, project_id=ctx.project_id).first()
    if module is None or issue is None:
        return
    issue.updated_at = timezone.now()
    issue.save(update_fields=["updated_at"])
    ctx.record(
        verb="created",
        old_value="",
        new_value=module.name,
        field="modules",
        comment=f"added module {module.name}",
        new_identifier=ctx.requested_data.get("module_id"),
    )


def delete_module_issue_activity(ctx: ActivityContext):
    module_name = ctx.current_instance.get("module_name")
    current_issue = Issue.objects.filter(pk=ctx.issue_id, project_id=ctx.project_id).first()
    if ctx.issue_id is not None and current_issue is None:
        return
    if current_issue:
        current_issue.updated_at = timezone.now()
        current_issue.save(update_fields=["updated_at"])
    ctx.record(
        verb="deleted",
        old_value=module_name,
        new_value="",
        field="modules",
        comment=f"removed this issue from {module_name}",
        old_identifier=(
            ctx.requested_data.get("module_id")
            if ctx.requested_data.get("module_id") is not None
            else None
        ),
    )


def create_link_activity(ctx: ActivityContext):
    ctx.record(
        comment="created a link",
        verb="created",
        field="link",
        new_value=ctx.requested_data.get("url", ""),
        new_identifier=ctx.requested_data.get("id", None),
    )

def update_link_activity(ctx: ActivityContext):
    if ctx.current_instance.get("url") != ctx.requested_data.get("url"):
        ctx.record(
            comment="updated a link",
            verb="updated",
            field="link",
            old_value=ctx.current_instance.get("url", ""),
            old_identifier=ctx.current_instance.get("id"),
            new_value=ctx.requested_data.get("url", ""),
            new_identifier=ctx.current_instance.get("id", None),
        )


def delete_link_activity(ctx: ActivityContext):
    ctx.record(
        comment="deleted the link",
        verb="deleted",
        field="link",
        old_value=ctx.current_instance.get("url", ""),
        new_value="",
    )

def create_attachment_activity(ctx: ActivityContext):
    ctx.record(
        comment="created an attachment",
        verb="created",
        field="attachment",
        new_value=ctx.current_instance.get("asset", ""),
        new_identifier=ctx.current_instance.get("id", None),
    )


def delete_attachment_activity(ctx: ActivityContext):
    ctx.record(
        comment="deleted the attachment",
        verb="deleted",
        field="attachment",
    )


def create_issue_reaction_activity(ctx: ActivityContext):
    if ctx.requested_data and ctx.requested_data.get("reaction") is not None:
        issue_reaction = (
            IssueReaction.objects.filter(
                reaction=ctx.requested_data.get("reaction"),
                project_id=ctx.project_id,
                actor_id=ctx.actor_id,
            )
            .values_list("id", flat=True)
            .first()
        )
        if issue_reaction is not None:
            ctx.record(
                verb="created",
                old_value=None,
                new_value=ctx.requested_data.get("reaction"),
                field="reaction",
                comment="added the reaction",
                old_identifier=None,
                new_identifier=issue_reaction,
            )

def delete_issue_reaction_activity(ctx: ActivityContext):
    if ctx.current_instance and ctx.current_instance.get("reaction") is not None:
        ctx.record(
            verb="deleted",
            old_value=ctx.current_instance.get("reaction"),
            new_value=None,
            field="reaction",
            comment="removed the reaction",
            old_identifier=ctx.current_instance.get("identifier"),
            new_identifier=None,
        )


def create_comment_reaction_activity(ctx: ActivityContext):
    if ctx.requested_data and ctx.requested_data.get("reaction") is not None:
        comment_reaction_id, comment_id = (
            CommentReaction.objects.filter(
                reaction=ctx.requested_data.get("reaction"),
                project_id=ctx.project_id,
                actor_id=ctx.actor_id,
            )
            .values_list("id", "comment__id")
            .first()
        )
        comment = IssueComment.objects.get(pk=comment_id, project_id=ctx.project_id)
        if comment is not None and comment_reaction_id is not None and comment_id is not None:
            ctx.record(
                issue_id=comment.issue_id,
                verb="created",
                old_value=None,
                new_value=ctx.requested_data.get("reaction"),
                field="reaction",
                comment="added the reaction",
                old_identifier=None,
                new_identifier=comment_reaction_id,
            )

def delete_comment_reaction_activity(ctx: ActivityContext):
    if not (ctx.current_instance and ctx.current_instance.get("reaction") is not None):
        return
    issue_id = (
        IssueComment.objects.filter(pk=ctx.current_instance.get("comment_id"), project_id=ctx.project_id)
        .values_list("issue_id", flat=True)
        .first()
    )
    if issue_id is None:
        return
    ctx.record(
        issue_id=issue_id,
        verb="deleted",
        old_value=ctx.current_instance.get("reaction"),
        new_value=None,
        field="reaction",
        comment="removed the reaction",
        old_identifier=ctx.current_instance.get("identifier"),
        new_identifier=None,
    )


def create_issue_vote_activity(ctx: ActivityContext):
    if ctx.requested_data and ctx.requested_data.get("vote") is not None:
        ctx.record(
            verb="updated",
            old_value=None,
            new_value=ctx.requested_data.get("vote"),
            field="vote",
            comment="added the vote",
            old_identifier=None,
            new_identifier=None,
        )


def delete_issue_vote_activity(ctx: ActivityContext):
    if ctx.current_instance and ctx.current_instance.get("vote") is not None:
        ctx.record(
            verb="deleted",
            old_value=ctx.current_instance.get("vote"),
            new_value=None,
            field="vote",
            comment="removed the vote",
            old_identifier=ctx.current_instance.get("identifier"),
            new_identifier=None,
        )


def create_issue_relation_activity(ctx: ActivityContext):
    if ctx.current_instance is not None:
        return
    if ctx.requested_data.get("issues") is None:
        return

    current_issue = Issue.objects.filter(
        pk=ctx.issue_id, project_id=ctx.project_id, workspace_id=ctx.workspace_id
    ).first()
    if current_issue is None:
        return

    for related_issue_id in ctx.requested_data.get("issues"):
        # Relations can span projects, so only the workspace is enforced
        issue = Issue.objects.filter(pk=related_issue_id, workspace_id=ctx.workspace_id).first()
        if issue is None:
            continue

        ctx.record(
            issue_id=ctx.issue_id,
            verb="updated",
            old_value="",
            new_value=f"{issue.project.identifier}-{issue.sequence_id}",
            field=ctx.requested_data.get("relation_type"),
            comment=f"added {ctx.requested_data.get('relation_type')} relation",
            old_identifier=related_issue_id,
        )

        inverse_relation = get_inverse_relation(ctx.requested_data.get("relation_type"))
        ctx.record(
            issue_id=related_issue_id,
            verb="updated",
            old_value="",
            new_value=f"{current_issue.project.identifier}-{current_issue.sequence_id}",
            field=inverse_relation,
            comment=f"added {inverse_relation} relation",
            old_identifier=ctx.issue_id,
        )


def delete_issue_relation_activity(ctx: ActivityContext):
    current_issue = Issue.objects.filter(
        pk=ctx.issue_id, project_id=ctx.project_id, workspace_id=ctx.workspace_id
    ).first()
    related_issue_id = ctx.requested_data.get("related_issue")
    issue = Issue.objects.filter(pk=related_issue_id, workspace_id=ctx.workspace_id).first()
    if current_issue is None or issue is None:
        return

    relation_type = ctx.requested_data.get("relation_type")
    ctx.record(
        issue_id=ctx.issue_id,
        verb="deleted",
        old_value=f"{issue.project.identifier}-{issue.sequence_id}",
        new_value="",
        field=relation_type,
        comment=f"deleted {relation_type} relation",
        old_identifier=related_issue_id,
    )

    inverse_relation = (
        "blocking"
        if relation_type == "blocked_by"
        else ("blocked_by" if relation_type == "blocking" else relation_type)
    )
    ctx.record(
        issue_id=related_issue_id,
        verb="deleted",
        old_value=f"{current_issue.project.identifier}-{current_issue.sequence_id}",
        new_value="",
        field=inverse_relation,
        comment=f"deleted {relation_type} relation",
        old_identifier=related_issue_id,
    )


def create_draft_issue_activity(ctx: ActivityContext):
    ctx.record(
        comment="drafted the issue",
        field="draft",
        verb="created",
    )


def update_draft_issue_activity(ctx: ActivityContext):
    if ctx.requested_data.get("is_draft") is not None and ctx.requested_data.get("is_draft") is False:
        ctx.record(
            comment="created the issue",
            verb="updated",
        )
    else:
        ctx.record(
            comment="updated the draft issue",
            field="draft",
            verb="updated",
        )



def delete_draft_issue_activity(ctx: ActivityContext):
    # Original omits issue_id here; pass None explicitly to preserve that.
    ctx.record(
        issue_id=None,
        comment="deleted the draft issue",
        field="draft",
        verb="deleted",
    )


def create_intake_activity(ctx: ActivityContext):
    status_dict = {
        -2: "Pending",
        -1: "Rejected",
        0: "Snoozed",
        1: "Accepted",
        2: "Duplicate",
    }
    if ctx.requested_data.get("status") is not None:
        ctx.record(
            comment="updated the intake status",
            field="intake",
            verb=ctx.requested_data.get("status"),
            old_value=status_dict.get(ctx.current_instance.get("status")),
            new_value=status_dict.get(ctx.requested_data.get("status")),
        )

### Mapping of issue activity types to their corresponding tracking functions ###
ISSUE_ACTIVITY_MAPPER = {
    "name": track_name,
    "parent_id": track_parent,
    "priority": track_priority,
    "state_id": track_state,
    "description_html": track_description,
    "target_date": track_target_date,
    "start_date": track_start_date,
    "label_ids": track_labels,
    "assignee_ids": track_assignees,
    "estimate_point": track_estimate_points,
    "archived_at": track_archive_at,
    "closed_to": track_closed_to,
    # External endpoint keys
    "parent": track_parent,
    "state": track_state,
    "assignees": track_assignees,
    "labels": track_labels,
}


ACTIVITY_MAPPER = {
    "issue.activity.created": create_issue_activity,
    "issue.activity.updated": update_issue_activity,
    "issue.activity.deleted": delete_issue_activity,
    "comment.activity.created": create_comment_activity,
    "comment.activity.updated": update_comment_activity,
    "comment.activity.deleted": delete_comment_activity,
    "cycle.activity.created": create_cycle_issue_activity,
    "cycle.activity.deleted": delete_cycle_issue_activity,
    "module.activity.created": create_module_issue_activity,
    "module.activity.deleted": delete_module_issue_activity,
    "link.activity.created": create_link_activity,
    "link.activity.updated": update_link_activity,
    "link.activity.deleted": delete_link_activity,
    "attachment.activity.created": create_attachment_activity,
    "attachment.activity.deleted": delete_attachment_activity,
    "issue_relation.activity.created": create_issue_relation_activity,
    "issue_relation.activity.deleted": delete_issue_relation_activity,
    "issue_reaction.activity.created": create_issue_reaction_activity,
    "issue_reaction.activity.deleted": delete_issue_reaction_activity,
    "comment_reaction.activity.created": create_comment_reaction_activity,
    "comment_reaction.activity.deleted": delete_comment_reaction_activity,
    "issue_vote.activity.created": create_issue_vote_activity,
    "issue_vote.activity.deleted": delete_issue_vote_activity,
    "issue_draft.activity.created": create_draft_issue_activity,
    "issue_draft.activity.updated": update_draft_issue_activity,
    "issue_draft.activity.deleted": delete_draft_issue_activity,
    "intake.activity.created": create_intake_activity,
}

# Receive message from room group
@shared_task
def issue_activity(
    type,
    requested_data,
    current_instance,
    issue_id,
    actor_id,
    project_id,
    epoch,
    subscriber=True,
    notification=False,
    origin=None,
    intake=None,
):
    try:
        issue_activities = []

        # check if project_id is valid
        if not is_valid_uuid(str(project_id)):
            return

        project = Project.objects.get(pk=project_id)
        
        raw_requested_data = requested_data
        raw_current_instance = current_instance

        ctx = ActivityContext(
            issue_id=issue_id,
            project_id=project_id,
            workspace_id=project.workspace_id,
            actor_id=actor_id,
            epoch=epoch,
            requested_data=json.loads(requested_data) if requested_data is not None else None,
            current_instance=json.loads(current_instance) if current_instance is not None else None,
        )

        if issue_id is not None:
            if origin:
                redis_instance().set(str(issue_id), origin, ex=600)
            issue = Issue.objects.filter(pk=issue_id, project_id=project_id).first()
            if issue:
                try:
                    issue.updated_at = timezone.now()
                    issue.save(update_fields=["updated_at"])
                except Exception:
                    pass

        func = ACTIVITY_MAPPER.get(type)
        if func is not None:
            func(ctx)

        # Save all the values to database
        issue_activities_created = IssueActivity.objects.bulk_create(ctx.issue_activities)

        if notification:
            notifications.delay(
                type=type,
                issue_id=issue_id,
                actor_id=actor_id,
                project_id=project_id,
                subscriber=subscriber,
                issue_activities_created=json.dumps(
                    IssueActivitySerializer(issue_activities_created, many=True).data,
                    cls=DjangoJSONEncoder,
                ),
                requested_data=raw_requested_data,
                current_instance=raw_current_instance,
            )

        return
    except Exception as e:
        log_exception(e)
        return
